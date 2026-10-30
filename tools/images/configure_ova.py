#!/usr/bin/env python3
import posixpath
import shlex
import subprocess
import hashlib
import time
import paramiko
import random
import os
import logging

def check_virtualbox_installed():
    try:
        result = subprocess.run(["vboxmanage", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"VirtualBox is installed. Version: {result.stdout.strip()}")
            return True
        else:
            print("VirtualBox is not installed.")
            return False
    except FileNotFoundError:
        print("VirtualBox is not installed.")
        return False


class VMHandler:
    def __init__(self, import_path, export_path, vmname, setup_user, setup_identity_file, setup_ssh_port, shell="/bin/bash", ssh_timeout=60):

        self.import_path = import_path
        self.export_path = export_path
        self.vmname = vmname
        self.setup_user = setup_user
        self.setup_identity_file = setup_identity_file
        self.setup_ssh_port = setup_ssh_port
        self.forwarded_setup_ssh_port = random.randint(20000, 60000)
        self.machine_ip = "127.0.0.1"
        self.shell = shell
        self.ssh_connection = None
        self.ssh_timeout = ssh_timeout

    def import_ova(self):
        print(f"Importing from OVA: {self.import_path} as VM '{self.vmname}'")
        import_command = ["vboxmanage", "import", self.import_path, "--vsys", "0", "--vmname", self.vmname, "--eula", "accept"]
        result = subprocess.run(import_command, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Successfully imported OVA: {self.import_path} as VM '{self.vmname}'")
        else:
            print(f"Failed to import OVA: {self.import_path}. Error: {result.stderr}")

    def export_ova(self):
        if os.path.exists(self.export_path):
            print(f"Export path {self.export_path} already exists. Removing it.")
            os.remove(self.export_path)

        print(f"Exporting VM '{self.vmname}' to OVA: {self.export_path}")
        export_command = ["vboxmanage", "export", self.vmname, "--output", self.export_path, "--ovf10", "--options", "nomacs", "--vsys", "0", "--vmname", self.vmname]
        result = subprocess.run(export_command, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Successfully exported VM '{self.vmname}' to OVA: {self.export_path}")
        else:
            print(f"Failed to export VM '{self.vmname}'. Error: {result.stderr}")

    def remove_vm(self):
        delete_command = ["vboxmanage", "unregistervm", self.vmname, "--delete-all"]
        result = subprocess.run(delete_command, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Successfully removed VM: {self.vmname}")
        else:
            print(f"Failed to remove VM: {self.vmname}. Error: {result.stderr}")

    def _setup_nat_with_forwarding(self):
        print()
        print(f"Setting up NAT with forwarding for SSH on VM: {self.vmname}")
        nat_command = [
            "vboxmanage", "modifyvm", self.vmname,
            "--nic1", "nat",
            "--natpf1", f"ssh,tcp,,{self.forwarded_setup_ssh_port},,{self.setup_ssh_port}"
        ]
        result = subprocess.run(nat_command, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Successfully set up NAT with port forwarding for VM: {self.vmname}")
        else:
            print(f"Failed to set up NAT for VM: {self.vmname}. Error: {result.stderr}")

    def start_vm(self):
        self._setup_nat_with_forwarding()

        print()
        print(f"Starting VM: {self.vmname}")
        start_command = ["vboxmanage", "startvm", self.vmname, "--type", "headless"]
        result = subprocess.run(start_command, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Successfully started VM: {self.vmname}")
        else:
            print(f"Failed to start VM: {self.vmname}. Error: {result.stderr}")

        timeout_per_try = 10
        start_time = time.time()
        last_error = None
        while time.time() - start_time < self.ssh_timeout:
            try:
                self.ssh_connection = paramiko.SSHClient()
                self.ssh_connection.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                self.ssh_connection.connect(
                    hostname=self.machine_ip,
                    username=self.setup_user,
                    key_filename=self.setup_identity_file,
                    port=self.forwarded_setup_ssh_port,
                    timeout=timeout_per_try,
                    banner_timeout=60,
                    look_for_keys=False,
                    allow_agent=False
                )
                print(f"SSH connection established to VM: {self.vmname}")
                return
            except Exception as e:
                last_error = e
        raise Exception(f"Failed to establish SSH connection to VM: {self.vmname} within timeout. Last error: {last_error}")

    def stop_vm(self):
        orig_level = logging.getLogger("paramiko.transport").level
        logging.getLogger("paramiko.transport").setLevel(logging.CRITICAL)

        try:
            self.ssh_connection.close()
        except Exception:
            pass

        stop_command = ["vboxmanage", "controlvm", self.vmname, "acpipowerbutton"]
        result = subprocess.run(stop_command, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Successfully sent ACPI shutdown signal to VM: {self.vmname}")
        else:
            print(f"Failed to send ACPI shutdown signal to VM: {self.vmname}. Error: {result.stderr}")

        check_vm_stopped_command = ["vboxmanage", "showvminfo", self.vmname, "--machinereadable"]
        still_running = True
        while still_running:
            result = subprocess.run(check_vm_stopped_command, capture_output=True, text=True)

            if 'VMState="poweroff"' in result.stdout:
                still_running = False
                print(f"VM '{self.vmname}' has powered off.")

                break
            time.sleep(1)

        if still_running:
            print(f"VM '{self.vmname}' did not power off within the expected time.")

        logging.getLogger("paramiko.transport").setLevel(orig_level)

    def execute_remote_command(self, command, user="root"):
        stdin, stdout, stderr = self.ssh_connection.exec_command(f"sudo -u {user} {self.shell} -c {shlex.quote(command)}")
        exit_status = stdout.channel.recv_exit_status()
        if exit_status == 0:
            print(f"Successfully executed command on VM: {self.vmname}: {command}")
            return stdout.read().decode()
        else:
            error_msg = stderr.read().decode()
            print(f"Failed to execute command on VM: {self.vmname}: {command}. Error: {error_msg}")
            return None

    def upload(self, local_path, remote_path):
        print(f"Uploading to VM: {self.vmname}: {local_path} -> {remote_path}")
        try:
            sftp = self.ssh_connection.open_sftp()

            if os.path.isdir(local_path):
                print("Detected directory, performing recursive upload")

                # Create a unique temporary directory on remote
                remote_tmp_dir = f"/tmp/{hashlib.sha256((local_path + str(time.time())).encode()).hexdigest()}"
                self.execute_remote_command(f"mkdir -p {remote_tmp_dir}")
                self.execute_remote_command(f"chmod 777 {remote_tmp_dir}")

                # Recursively upload contents
                for root, dirs, files in os.walk(local_path):
                    rel_path = os.path.relpath(root, local_path)
                    remote_subdir = posixpath.join(remote_tmp_dir, rel_path).replace("\\", "/")
                    self.execute_remote_command(f"mkdir -p {remote_subdir}")
                    self.execute_remote_command(f"chmod 777 {remote_subdir}")

                    for filename in files:
                        local_file = os.path.join(root, filename)
                        remote_file = posixpath.join(remote_subdir, filename).replace("\\", "/")
                        sftp.put(local_file, remote_file)
                        print(f"Uploaded file: {local_file} → {remote_file}")

                # Move temporary directory to final location
                self.execute_remote_command(f"rm -rf {remote_path}")
                self.execute_remote_command(f"mv {remote_tmp_dir} {remote_path}")
                print(f"Successfully uploaded directory {local_path} to {remote_path} on VM: {self.vmname}")

            else:
                print("Detected file, uploading normally")
                remote_tmp_file = f"/tmp/{hashlib.sha256((local_path + str(time.time())).encode()).hexdigest()}"
                sftp.put(local_path, remote_tmp_file)
                print(f"File uploaded to temporary location: {remote_tmp_file}")
                self.execute_remote_command(f"mv {remote_tmp_file} {remote_path}")
                print(f"Successfully uploaded file {local_path} to {remote_path} on VM: {self.vmname}")

            sftp.close()

        except Exception as e:
            print(f"Failed to upload {local_path} to {remote_path} on VM: {self.vmname}. Error: {e}")


class BuildParser:
    def __init__(self, build_file_path):
        self.build_file_path = build_file_path
        self.meta_data = {
            "FROM": None,
            "VM_NAME": None,
            "SETUP_USER": None,
            "SETUP_PORT": None,
            "SETUP_IDENTITY_FILE": None
        }
        self.build_flow = []  # List of dictionaries representing instructions

    def parse_build_file(self):
        current_section = "meta"
        current_user = "root"
        current_service = None
        service_block = {}

        with open(self.build_file_path, 'r') as file:
            for line in file:
                line = line.strip()
                if line.startswith("#") or line == "":
                    continue

                if current_section == "meta":
                    # Parse meta data
                    if line.startswith("FROM "):
                        self._set_meta("FROM", line)
                    elif line.startswith("VM_NAME "):
                        self._set_meta("VM_NAME", line)
                    elif line.startswith("SETUP_USER "):
                        self._set_meta("SETUP_USER", line)
                    elif line.startswith("SETUP_PORT "):
                        self._set_meta("SETUP_PORT", line)
                    elif line.startswith("SETUP_IDENTITY_FILE "):
                        self._set_meta("SETUP_IDENTITY_FILE", line)
                    else:
                        raise ValueError(f"Unknown statement in meta section: {line}")

                    # Check if meta section is complete
                    if all(value is not None for value in self.meta_data.values()):
                        current_section = "build"

                elif current_section == "build":
                    # Parse build instructions
                    if line.startswith("USER "):
                        current_user = line.split(" ", 1)[1].strip()
                        self.build_flow.append({"instruction": "USER", "user": current_user})

                    elif line.startswith("COPY "):
                        _, src, dest = line.split(" ", 2)
                        self.build_flow.append({"instruction": "COPY", "src": src, "dest": dest, "user": current_user})

                    elif line.startswith("RUN "):
                        command = line.split(" ", 1)[1].strip()
                        self.build_flow.append({"instruction": "RUN", "command": command, "user": current_user})

                    elif line.startswith("SERVICE "):
                        if "{" in line:  # Start of service block
                            service_name = line.split(" ", 1)[1].split("{")[0].strip()
                            if service_name.endswith(".service"):
                                service_name = service_name[:-8]
                            service_block = {"name": service_name}
                            current_service = service_block
                        else:  # Simple service command
                            service_name = line.split(" ", 1)[1].strip()
                            self.build_flow.append({"instruction": "SERVICE", "name": service_name})

                    elif current_service:
                        # Inside service block
                        if line == "}":
                            self.build_flow.append({"instruction": "SERVICE_BLOCK", **current_service})
                            current_service = None
                        else:
                            if " " in line:
                                key, value = line.split(" ", 1)
                                current_service[key.upper()] = value.strip().strip('"')
                            else:
                                current_service[line.upper()] = True

    def _set_meta(self, key, line):
        if self.meta_data[key] is not None:
            raise ValueError(f"Multiple {key} statements found in meta section.")
        self.meta_data[key] = line.split(" ", 1)[1].strip()


class VMProvisioner:
    def __init__(self, vm_handler, build_parser):
        self.vm = vm_handler
        self.build = build_parser

    def provision(self):
        self.vm.start_vm()

        for step in self.build.build_flow:
            instr = step["instruction"]

            if instr == "COPY":
                print(f"\nCopying {step['src']} to {step['dest']}")
                self.vm.upload(step["src"], step["dest"])

            elif instr == "RUN":
                print(f"\nRunning command: {step['command']} as {step['user']}")
                self.vm.execute_remote_command(step["command"], user=step["user"])

            elif instr == "SERVICE_BLOCK":
                print(f"\nSetting up service: {step['name']}")
                self._setup_service(step)

            elif instr == "USER":
                # User already tracked in step["user"]
                pass

        print("\nProvisioning complete. Stopping VM.")
        self.vm.stop_vm()

    def _setup_service(self, service):
        # Create a systemd service file on the VM
        service_content = [
            f"[Unit]",
            f"Description={service.get('DESCRIPTION', service['name'])}",
            f"After={service.get('AFTER', 'network.target')}",
            "",
            "[Service]"
        ]
        if "CMD" in service:
            service_content.append(f"ExecStart={service['CMD']}")
        if "TYPE" in service:
            service_content.append(f"Type={service['TYPE']}")
        if "RESTART" in service:
            service_content.append(f"Restart={service['RESTART']}")
        if "RESTART_SEC" in service:
            service_content.append(f"RestartSec={service['RESTART_SEC']}")
        if "USER" in service:
            service_content.append(f"User={service['USER']}")

        service_content.extend([
            "[Install]",
            "WantedBy=multi-user.target\n"
        ])

        remote_service_file = f"/etc/systemd/system/{service['name']}.service"
        tmp_file = f"/tmp/{service['name']}.service"
        with open(tmp_file, "w") as f:
            f.write("\n".join(service_content))

        self.vm.upload(tmp_file, remote_service_file)
        self.vm.execute_remote_command(f"chown root:root {remote_service_file}")
        self.vm.execute_remote_command(f"chmod 755 {remote_service_file}")

        self.vm.execute_remote_command(f"systemctl daemon-reload")
        self.vm.execute_remote_command(f"systemctl enable {service['name']}")

def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="VM Provisioning Tool using VirtualBox"
    )
    parser.add_argument(
        "build_file_path",
        help="Path to the build file defining the provisioning steps."
    )
    parser.add_argument(
        "output_ova_path",
        help="Path to the build file defining the provisioning steps."
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite the output OVA file if it already exists."
    )

    args = parser.parse_args()

    build_file_path = args.build_file_path
    build_file_path = os.path.abspath(build_file_path)
    build_script_base_dir = os.path.dirname(os.path.abspath(build_file_path))

    output_ova_path = args.output_ova_path
    output_ova_path = os.path.abspath(output_ova_path)

    os.chdir(build_script_base_dir)

    if os.path.exists(output_ova_path):
        if not args.overwrite:
            overwrite = input("Output OVA file already exists. Overwrite it? [y/N]: ")
            if overwrite.lower() != 'y':
                print("Exiting without overwriting the existing OVA file.")
                sys.exit(0)

    print("""
    
=================================================================
                    Starting VM OVA Setup Tool
=================================================================
""")

    if not check_virtualbox_installed():
        sys.exit(1)

    build_parser = BuildParser(build_file_path)
    build_parser.parse_build_file()
    meta = build_parser.meta_data
    vm_handler = VMHandler(
        import_path=meta["FROM"],
        export_path=output_ova_path,
        vmname=meta["VM_NAME"],
        setup_user=meta["SETUP_USER"],
        setup_identity_file=meta["SETUP_IDENTITY_FILE"],
        setup_ssh_port=meta["SETUP_PORT"]
    )
    print("""
    
=================================================================
                    Importing VM from OVA
=================================================================
""")
    vm_handler.import_ova()

    provisioner = VMProvisioner(vm_handler, build_parser)

    print("""
    
=================================================================
                        VM Provisioning
=================================================================
""")
    provisioner.provision()

    print("""
    
=================================================================
                    Exporting VM to OVA
=================================================================
""")
    vm_handler.export_ova()

    print("""
    
=================================================================
                    Cleaning up VM Instance
=================================================================
""")
    vm_handler.remove_vm()


if __name__ == "__main__":
    main()