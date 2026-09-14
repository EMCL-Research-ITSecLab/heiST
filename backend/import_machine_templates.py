from hashlib import sha256
import random
import os
import subprocess
import time


from backend.qemu_ga_wrapper import GuestAgent, GuestAgentError
from backend.DatabaseClasses import MachineTemplate, ChallengeTemplate
from backend.proxmox_api_calls import (
    add_network_device_api_call,
    initial_configuration_api_call,
    launch_vm_api_call,
    shutdown_vm_api_call,
    vm_is_stopped_api_call,
    detach_network_device_api_call,
    convert_vm_to_template_api_call,
    delete_vm_api_call
)

PROXMOX_STORAGE_BASE_DIR = "/var/lib/vz/import"
_LINUX_AGENT_CONFIG_DIR  = "/root/heiST/monitoring/wazuh/agent/linux"
_WINDOWS_AGENT_CONFIG_DIR = "/root/heiST/monitoring/wazuh/agent/windows"

_LINUX_REMOTE_BASE   = "/var/monitoring/wazuh-agent"
_WINDOWS_REMOTE_BASE = r"C:\Windows\Temp\wazuh-agent"

_LINUX_SETUP_FLAG   = "/var/run/wazuh-setup-complete.flag"
_WINDOWS_SETUP_FLAG = r"C:\ProgramData\WazuhSetup\wazuh-setup-complete.flag"

_DNS_SERVERS = ("8.8.8.8", "1.1.1.1")

def import_machine_templates(challenge_template_id, db_conn, ip_pool):
    """
    Import a machine template from a disk image file and associate it with a challenge.
    """
    print(f"[Info] Starting machine template import process for challenge template {challenge_template_id}", flush=True)
    start_time = time.time()

    try:
        print(f"[Info] Fetching challenge template {challenge_template_id} from database", flush=True)
        challenge_template = fetch_challenge_template(challenge_template_id, db_conn)
        print(f"[Info] Successfully fetched challenge template {challenge_template_id}", flush=True)

        print(f"[Info] Fetching machine templates for challenge {challenge_template_id}", flush=True)
        fetch_machine_templates(challenge_template, db_conn)
        print(f"[Info] Successfully fetched {len(challenge_template.machine_templates)} machine templates", flush=True)
    except Exception as e:
        print(f"[Error] Failed to fetch challenge template: {e}", flush=True)
        raise RuntimeError(f"Failed to fetch challenge template: {e}")

    try:
        print(f"[Info] Starting disk image import for {len(challenge_template.machine_templates)} machine templates", flush=True)
        import_disk_images_to_vm_templates(challenge_template)

        print(f"[Info] Configuring VMs for challenge {challenge_template_id}", flush=True)
        configure_vms(challenge_template, ip_pool)

        print(f"[Info] Converting machine template VMs to Proxmox templates", flush=True)
        convert_machine_template_vms_to_templates(challenge_template)

        print(f"[Info] Marking challenge template {challenge_template_id} as ready", flush=True)
        mark_challenge_template_as_ready(challenge_template, db_conn)

        elapsed_time = time.time() - start_time
        print(f"[Info] Machine template import completed successfully in {elapsed_time:.2f}s", flush=True)
    except Exception as e:
        print(f"[Error] Failed during import process: {e}", flush=True)
        print(f"[Info] Undoing machine template import for challenge {challenge_template_id}", flush=True)
        undo_import_machine_templates(challenge_template)
        raise RuntimeError(f"Failed to import disk images: {e}")


def fetch_challenge_template(challenge_id, db_conn):
    """
    Fetch the challenge details from the database.
    """
    print(f"[Debug] Querying database for challenge template {challenge_id}", flush=True)

    with db_conn.cursor() as cursor:
        cursor.execute("SELECT id FROM challenge_templates WHERE id = %s", (challenge_id,))
        result = cursor.fetchone()

    if result is None:
        print(f"[Error] Challenge template {challenge_id} not found in database", flush=True)
        raise ValueError(f"Challenge with ID {challenge_id} not found.")

    challenge_template = ChallengeTemplate(challenge_template_id=result[0])
    print(f"[Info] Successfully retrieved challenge template {challenge_id}", flush=True)

    return challenge_template


def fetch_machine_templates(challenge_template, db_conn):
    """
    Fetch the machine templates associated with the challenge from the database.
    """
    print(f"[Info] Fetching machine templates for challenge {challenge_template.id}", flush=True)

    machines_fetched = 0

    with db_conn.cursor() as cursor:
        cursor.execute(
            "SELECT mt.id, df.proxmox_filename, mt.cores, mt.ram_gb, df.guest_os "
            "FROM machine_templates mt "
            "JOIN disk_files df ON df.id = mt.disk_file_id "
            "WHERE mt.challenge_template_id = %s",
            (challenge_template.id,)
        )

        for machine_template_id, proxmox_filename, cores, ram_gb, guest_os in cursor.fetchall():
            print(f"[Debug] Processing machine template {machine_template_id} (guest_os={guest_os})", flush=True)

            disk_file_path = os.path.join(PROXMOX_STORAGE_BASE_DIR, proxmox_filename)

            # Check if the disk file path is valid
            if not os.path.exists(disk_file_path):
                print(f"[Error] Disk file path does not exist: {disk_file_path}", flush=True)
                raise ValueError(f"Disk file path {disk_file_path} does not exist.")
            if not os.path.isfile(disk_file_path):
                print(f"[Error] Disk file path is not a file: {disk_file_path}", flush=True)
                raise ValueError(f"Disk file path {disk_file_path} is not a file.")
            if not disk_file_path.endswith(('.ova', '.iso')):
                print(f"[Error] Disk file path is not valid OVA or ISO: {disk_file_path}", flush=True)
                raise ValueError(f"Disk file path {disk_file_path} is not a valid OVA or ISO file.")

            print(f"[Info] Creating machine template {machine_template_id} with {cores} cores, {ram_gb}GB RAM", flush=True)
            print(f"[Debug] Disk file: {disk_file_path}", flush=True)

            machine_template = MachineTemplate(
                machine_template_id=machine_template_id,
                challenge_template=challenge_template
            )
            machine_template.set_cores(cores)
            machine_template.set_ram(ram_gb * 1024)  # Convert GB to MB
            machine_template.set_disk_file_path(disk_file_path)
            machine_template.set_guest_os(guest_os)
            challenge_template.add_machine_template(machine_template)
            machines_fetched += 1
            print(f"[Info] Successfully added machine template {machine_template_id} to challenge", flush=True)

    print(f"[Info] Successfully fetched {machines_fetched} machine templates for challenge {challenge_template.id}", flush=True)


def check_user_input(user_input):
    """
    Sanitize user input to prevent command injection attacks.
    """
    import re

    blacklist_pattern = r"""[;&|><`$\\'"*?{}\[\]~!#()=]+"""
    if re.search(blacklist_pattern, user_input):
        print(f"[Error] Input validation failed - potentially dangerous characters detected", flush=True)
        raise ValueError("Input contains potentially dangerous characters.")

    print(f"[Debug] Input validation passed", flush=True)


def import_disk_images_to_vm_templates(challenge_template):
    """
    Import the disk images to VM templates.
    """
    print(f"[Info] Importing disk images for {len(challenge_template.machine_templates)} machine templates", flush=True)

    images_imported = 0
    for machine_template in challenge_template.machine_templates.values():
        disk_file_path = machine_template.disk_file_path
        print(f"[Info] Validating disk file for machine template {machine_template.id}", flush=True)
        check_user_input(disk_file_path)

        disk_file_extension = os.path.splitext(disk_file_path)[1].lower()
        print(f"[Debug] Disk file extension: {disk_file_extension}", flush=True)

        if disk_file_extension == ".ova":
            print(f"[Info] Converting OVA file to machine template {machine_template.id}", flush=True)
            convert_ova_to_machine_template(disk_file_path, machine_template.id)
            images_imported += 1

        elif disk_file_extension == ".iso":
            print(f"[Info] Converting ISO file to machine template {machine_template.id}", flush=True)
            convert_iso_to_machine_template(disk_file_path, machine_template.id)
            images_imported += 1

    print(f"[Info] Successfully imported {images_imported} disk images for challenge", flush=True)


def convert_ova_to_machine_template(disk_file_path, machine_template_id):
    """
    Convert an OVA disk image file to a machine template.
    """
    print(f"[Info] Starting OVA to machine template conversion for VM {machine_template_id}", flush=True)
    print(f"[Debug] OVA file path: {disk_file_path}", flush=True)

    tmp_dir_name = f"proxmox_import_{sha256(str(time.time()).encode() + b' ' + str(random.randint(0, 2**20)).encode()).hexdigest()}"

    tmp_dir = os.path.join("/tmp", tmp_dir_name)
    print(f"[Debug] Creating temporary extraction directory: {tmp_dir}", flush=True)
    os.makedirs(tmp_dir, exist_ok=True)

    # Extract the OVA file
    try:
        print(f"[Info] Extracting OVA file to {tmp_dir}", flush=True)
        subprocess.run(["tar", "-xvf", disk_file_path, "-C", tmp_dir], check=True, capture_output=True)
        print(f"[Info] OVA file extraction completed successfully", flush=True)
    except Exception as e:
        print(f"[Error] Failed to extract OVA file: {e}", flush=True)
        raise RuntimeError(f"Failed to extract OVA file: {e}")

    # Find the OVF file
    print(f"[Info] Searching for OVF file in extracted archive", flush=True)
    ovf_file_count = 0
    ovf_file = None
    for file in os.listdir(tmp_dir):
        if file.endswith(".ovf"):
            ovf_file = os.path.join(tmp_dir, file)
            ovf_file_count += 1
            print(f"[Debug] Found OVF file: {file}", flush=True)

    if not ovf_file:
        print(f"[Error] No OVF file found in OVA archive", flush=True)
        raise ValueError("No OVF file found in the OVA archive.")

    if ovf_file_count > 1:
        print(f"[Error] Multiple OVF files found: {ovf_file_count}", flush=True)
        raise ValueError("Multiple OVF files found in the OVA archive. Please provide a single OVF file.")

    # Convert the OVF file to a Proxmox template
    try:
        print(f"[Info] Importing OVF to Proxmox as machine template {machine_template_id}", flush=True)
        importovf_command = f"qm importovf {machine_template_id} '{ovf_file}' local-lvm"
        if "|" in importovf_command or ";" in importovf_command or "&" in importovf_command:
            print(f"[Error] Invalid characters in import command", flush=True)
            raise ValueError("Invalid characters in import command.")
        subprocess.run(importovf_command, shell=True, check=True, capture_output=True)
        print(f"[Info] OVF import completed successfully for machine template {machine_template_id}", flush=True)
    except Exception as e1:
        print(f"[Error] Failed to import OVF file: {e1}", flush=True)
        print(f"[Info] Cleaning up failed import - unlocking and destroying VM {machine_template_id}", flush=True)
        try:
            subprocess.run(["qm", "unlock", str(machine_template_id)], check=True, capture_output=True)
            subprocess.run(["qm", "destroy", str(machine_template_id)], check=True, capture_output=True)
            print(f"[Info] Cleanup completed for VM {machine_template_id}", flush=True)
        except Exception:
            pass

        raise RuntimeError(f"Failed to import OVA file: {e1}")

    # Clean up the temporary directory
    try:
        print(f"[Info] Removing temporary extraction directory: {tmp_dir}", flush=True)
        subprocess.run(["rm", "-rf", tmp_dir], check=True, capture_output=True)
        print(f"[Info] Temporary directory cleanup completed", flush=True)
    except Exception as e:
        print(f"[Error] Failed to clean up temporary directory: {e}", flush=True)
        raise RuntimeError(f"Failed to clean up temporary directory: {e}")


def convert_iso_to_machine_template(disk_file_path, machine_template_id):
    """
    Convert an ISO disk image file to a machine template.
    """
    print(f"[Info] Starting ISO to machine template conversion for VM {machine_template_id}", flush=True)
    print(f"[Debug] ISO file path: {disk_file_path}", flush=True)

    # Convert the ISO file to a Proxmox template
    try:
        if "|" in disk_file_path or ";" in disk_file_path or "&" in disk_file_path:
            print(f"[Error] Invalid characters in disk file path", flush=True)
            raise ValueError("Invalid characters in disk file path.")

        print(f"[Info] Importing ISO to Proxmox as machine template {machine_template_id}", flush=True)
        importdisk_command = f"qm importdisk {machine_template_id} \"{disk_file_path}\" local-lvm"
        subprocess.run(importdisk_command, shell=True, check=True, capture_output=True)
        print(f"[Info] ISO import completed successfully for machine template {machine_template_id}", flush=True)
    except Exception as e1:
        print(f"[Error] Failed to import ISO file: {e1}", flush=True)
        print(f"[Info] Cleaning up failed import - unlocking and destroying VM {machine_template_id}", flush=True)
        try:
            subprocess.run(["qm", "unlock", str(machine_template_id)], check=True, capture_output=True)
            subprocess.run(["qm", "destroy", str(machine_template_id)], check=True, capture_output=True)
            print(f"[Info] Cleanup completed for VM {machine_template_id}", flush=True)
        except Exception as e2:
            pass

        raise RuntimeError(f"Failed to import ISO file: {e1}")

def _collect_agent_files(config_dir):
    """
    Walk config_dir and return a list of (local_abs_path, rel_path) tuples
    """
    files = []

    config_subdir = os.path.join(config_dir, "config")
    if os.path.isdir(config_subdir):
        for root, _, fnames in os.walk(config_subdir):
            for fname in fnames:
                abs_path = os.path.join(root, fname)
                rel_path = os.path.relpath(abs_path, config_dir)
                files.append((abs_path, rel_path))

    for script in ("setup_wazuh.sh", "setup_wazuh.ps1"):
        script_path = os.path.join(config_dir, script)
        if os.path.isfile(script_path):
            files.append((script_path, script))

    return files


def _copy_agent_files_linux(ga, config_dir, remote_base, vmid):
    """
    Copy all agent files to a Linux guest via GA, preserving the relative directory structure under remote_base.
    """
    files = _collect_agent_files(config_dir)
    print(f"[Info] Copying {len(files)} agent files to Linux VM {vmid}", flush=True)

    for abs_path, rel_path in files:
        remote_path = remote_base + "/" + rel_path.replace("\\", "/")
        remote_dir  = remote_path.rsplit("/", 1)[0]

        ga.exec(["mkdir", "-p", remote_dir], capture_output=False, timeout=10)
        ga.write_local_file(abs_path, remote_path)  # preserves local mode bits
        print(f"[Debug] Wrote {rel_path} -> {remote_path} on VM {vmid}", flush=True)

    print(f"[Info] Agent files staged on Linux VM {vmid}", flush=True)


def _copy_agent_files_windows(ga, config_dir, remote_base, vmid):
    """
    Copy all agent files to a Windows guest via GA, preserving the relative directory structure under remote_base.
    """
    files = _collect_agent_files(config_dir)
    print(f"[Info] Copying {len(files)} agent files to Windows VM {vmid}", flush=True)

    for abs_path, rel_path in files:
        remote_path = remote_base + "\\" + rel_path.replace("/", "\\")
        remote_dir  = remote_path.rsplit("\\", 1)[0]

        ga.exec(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
             f'New-Item -ItemType Directory -Force -Path "{remote_dir}" | Out-Null'],
            capture_output=False,
            timeout=90,
        )

        with open(abs_path, "rb") as f:
            data = f.read()
        ga.write_file(remote_path, data)
        print(f"[Debug] Wrote {rel_path} -> {remote_path} on VM {vmid}", flush=True)

    print(f"[Info] Agent files staged on Windows VM {vmid}", flush=True)


def _wait_for_ga(ga, vmid, ping_timeout, poll_interval=2):
    ping_deadline = time.monotonic() + ping_timeout
    while not ga.ping():
        if time.monotonic() > ping_deadline:
            raise TimeoutError(
                f"QEMU GA on VM {vmid} did not become responsive within {ping_timeout}s"
            )
        time.sleep(poll_interval)
    print(f"[Info] GA responsive on VM {vmid}", flush=True)


def configure_vms(challenge_template, ip_pool):
    """
    Configure VMs with proper IP pool management
    """
    print(f"[Info] Starting VM configuration for {len(challenge_template.machine_templates)} machines", flush=True)
    vms_configured = 0
    allocated_ips = {}

    for machine_template in challenge_template.machine_templates.values():
        try:
            print(f"[Info] Configuring machine template {machine_template.id} (guest_os={machine_template.guest_os})", flush=True)

            allocated_ip = ip_pool.allocate_ip(machine_template.id)
            if not allocated_ip:
                raise RuntimeError(f"Could not allocate IP for VM {machine_template.id}")
            allocated_ips[machine_template.id] = allocated_ip
            print(f"[Debug] Allocated IP {allocated_ip} for VM {machine_template.id}", flush=True)

            add_network_device_api_call(machine_template.id)
            print(f"[Debug] Temporary cloud NIC attached to VM {machine_template.id}", flush=True)

            initial_configuration_api_call(machine_template)
            print(f"[Debug] Base Proxmox config applied for VM {machine_template.id}", flush=True)

            time.sleep(5)
            launch_vm_api_call(machine_template)
            vms_configured += 1
            print(f"[Info] VM {machine_template.id} launched", flush=True)

        except Exception as e:
            print(f"[Error] Failed to configure VM {machine_template.id}: {e}", flush=True)
            raise RuntimeError(f"Failed to configure VM {machine_template.id}: {e}")

    print(f"[Info] Launched {vms_configured} VMs, starting GA-based setup", flush=True)

    vms_completed = 0
    for machine_template in challenge_template.machine_templates.values():
        try:
            allocated_ip = allocated_ips[machine_template.id]
            if machine_template.guest_os == 'windows':
                install_wazuh_windows(machine_template=machine_template, allocated_ip=allocated_ip)
            else:
                install_wazuh_linux(machine_template=machine_template, allocated_ip=allocated_ip)

            print(f"[Info] Setup complete on VM {machine_template.id}, shutting down", flush=True)
            shutdown_vm_api_call(machine_template)

            max_wait = 900
            start_time = time.time()
            while time.time() - start_time < max_wait:
                if vm_is_stopped_api_call(machine_template):
                    print(f"[Info] VM {machine_template.id} stopped", flush=True)
                    break
                elapsed = int(time.time() - start_time)
                if elapsed % 60 == 0:
                    print(f"[Debug] Waiting for VM {machine_template.id} to stop ({elapsed}s elapsed)", flush=True)
                time.sleep(30)
            else:
                raise RuntimeError(f"VM {machine_template.id} did not stop within {max_wait}s")

            detach_network_device_api_call(vmid=machine_template.id, nic="net30")
            print(f"[Debug] Temporary cloud NIC detached from VM {machine_template.id}", flush=True)

            ip_pool.release_ip(machine_template.id)
            vms_completed += 1
            print(f"[Info] VM {machine_template.id} cleanup complete", flush=True)

        except Exception as e:
            print(f"[Error] Failed to complete setup for VM {machine_template.id}: {e}", flush=True)
            raise

    print(f"[Info] Successfully configured {vms_completed} VMs", flush=True)


def install_wazuh_linux(machine_template, allocated_ip,timeout=600):
    """
    Install Wazuh on a Linux VM via QEMU Guest Agent
    """

    _PING_TIMEOUT    = 120
    _INSTALL_TIMEOUT = max(timeout - 60, 120)
    _FAST_TIMEOUT    = 15

    start_time = time.monotonic()
    deadline   = start_time + timeout

    print(f"[Info] Starting Linux Wazuh install on VM {machine_template.id}", flush=True)

    with GuestAgent(vmid=machine_template.id) as ga:
        _wait_for_ga(ga, machine_template.id, _PING_TIMEOUT)

        nic_cmd = (
            "iface=$(ip -o link | awk '/0a:00/ {print $2; exit}' | tr -d :) && "
            "ip link set $iface up && "
            f"ip addr add {allocated_ip}/20 dev $iface && "
            "ip route add default via 10.32.0.1 && "
            f"printf 'nameserver {_DNS_SERVERS[0]}\\nnameserver {_DNS_SERVERS[1]}\\n' > /etc/resolv.conf"
        )
        result = ga.exec(nic_cmd, capture_output=True, timeout=30)
        if result.exit_code != 0:
            print(f"[Warning] NIC setup non-zero on VM {machine_template.id}: {result.stderr.strip()!r}", flush=True)

        _copy_agent_files_linux(ga, _LINUX_AGENT_CONFIG_DIR, _LINUX_REMOTE_BASE, machine_template.id)

        install_cmd = (
            f"{_LINUX_REMOTE_BASE}/setup_wazuh.sh --install --yes"
        )
        print(f"[Info] Running setup_wazuh.sh --install on VM {machine_template.id}", flush=True)
        result = ga.exec(install_cmd, capture_output=True, timeout=_INSTALL_TIMEOUT)
        if result.exit_code != 0:
            raise RuntimeError(
                f"setup_wazuh.sh --install failed on VM {machine_template.id} "
                f"(exit={result.exit_code}): {result.stderr.strip()!r}"
            )
        print(f"[Info] setup_wazuh.sh --install completed on VM {machine_template.id}", flush=True)

        while time.monotonic() < deadline:
            elapsed = int(time.monotonic() - start_time)
            try:
                flag_result = ga.exec(
                    ["test", "-f", _LINUX_SETUP_FLAG],
                    capture_output=False,
                    timeout=_FAST_TIMEOUT,
                )
                timer_result = ga.exec(
                    ["systemctl", "is-active", "bash_loggin_timer.timer"],
                    capture_output=True,
                    timeout=_FAST_TIMEOUT,
                )
                if flag_result.exit_code == 0 and timer_result.stdout.strip() == "active":
                    time.sleep(15)  # stability buffer
                    print(f"[Info] Linux setup complete on VM {machine_template.id}", flush=True)
                    return
                print(
                    f"[{elapsed}s] waiting: "
                    f"flag={'present' if flag_result.exit_code == 0 else 'missing'} "
                    f"timer={timer_result.stdout.strip()!r}",
                    flush=True,
                )
            except GuestAgentError as e:
                print(f"[{elapsed}s] GA error on VM {machine_template.id}: {type(e).__name__}: {e}", flush=True)
            except Exception as e:
                print(f"[{elapsed}s] Unexpected error on VM {machine_template.id}: {type(e).__name__}: {e}", flush=True)
            time.sleep(10)

    raise TimeoutError(f"Linux setup did not complete within {timeout}s for VM {machine_template.id}")


def install_wazuh_windows(machine_template, allocated_ip, timeout=900):
    """
    Install Wazuh on a Windows VM via QEMU Guest Agent
    """
    _PING_TIMEOUT    = 180
    _INSTALL_TIMEOUT = max(timeout - 120, 300)
    _FAST_TIMEOUT    = 40

    start_time = time.monotonic()
    deadline   = start_time + timeout

    print(f"[Info] Starting Windows Wazuh install on VM {machine_template.id}", flush=True)

    with GuestAgent(vmid=machine_template.id, windows=True) as ga:
        _wait_for_ga(ga, machine_template.id, _PING_TIMEOUT, poll_interval=5)

        nic_cmd = (
            '$nic = Get-NetAdapter | Where-Object { $_.MacAddress -like "0A-00*" } | Select-Object -First 1; '
            'Remove-NetIPAddress -InterfaceIndex $nic.ifIndex -AddressFamily IPv4 -Confirm:$false -ErrorAction SilentlyContinue; '
            'Remove-NetRoute -InterfaceIndex $nic.ifIndex -DestinationPrefix "0.0.0.0/0" -Confirm:$false -ErrorAction SilentlyContinue; '
            f'New-NetIPAddress -InterfaceIndex $nic.ifIndex -IPAddress {allocated_ip} -PrefixLength 20 -DefaultGateway 10.32.0.1; '
            f'Set-DnsClientServerAddress -InterfaceIndex $nic.ifIndex -ServerAddresses ("{_DNS_SERVERS[0]}","{_DNS_SERVERS[1]}")'
        )
        result = ga.exec(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", nic_cmd],
            capture_output=True,
            timeout=90,
        )
        if result.exit_code != 0:
            print(f"[Warning] NIC setup non-zero on Windows VM {machine_template.id}: {result.stderr.strip()!r}", flush=True)

        _copy_agent_files_windows(ga, _WINDOWS_AGENT_CONFIG_DIR, _WINDOWS_REMOTE_BASE, machine_template.id)

        ps1_remote = _WINDOWS_REMOTE_BASE + "\\setup_wazuh.ps1"
        print(f"[Info] Running setup_wazuh.ps1 --install on VM {machine_template.id}", flush=True)
        result = ga.exec(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1_remote, "--install", "--yes"],
            capture_output=True,
            timeout=_INSTALL_TIMEOUT,
        )
        if result.exit_code != 0:
            raise RuntimeError(
                f"setup_wazuh.ps1 --install failed on VM {machine_template.id} "
                f"(exit={result.exit_code}): {result.stderr.strip()!r}"
            )
        print(f"[Info] setup_wazuh.ps1 --install completed on VM {machine_template.id}", flush=True)

        while time.monotonic() < deadline:
            elapsed = int(time.monotonic() - start_time)
            try:
                flag_result = ga.exec(
                    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                     f'if (Test-Path "{_WINDOWS_SETUP_FLAG}") {{ exit 0 }} else {{ exit 1 }}'],
                    capture_output=False,
                    timeout=_FAST_TIMEOUT,
                )
                if flag_result.exit_code == 0:
                    time.sleep(15)  # stability buffer
                    print(f"[Info] Windows setup complete on VM {machine_template.id}", flush=True)
                    return
                print(f"[{elapsed}s] waiting: setup flag not yet present on VM {machine_template.id}", flush=True)
            except GuestAgentError as e:
                print(f"[{elapsed}s] GA error on Windows VM {machine_template.id}: {type(e).__name__}: {e}", flush=True)
            except Exception as e:
                print(f"[{elapsed}s] Unexpected error on Windows VM {machine_template.id}: {type(e).__name__}: {e}", flush=True)
            time.sleep(15)

    raise TimeoutError(f"Windows setup did not complete within {timeout}s for VM {machine_template.id}")

def convert_machine_template_vms_to_templates(challenge_template):
    """
    Convert the VM to a template in Proxmox.
    """
    print(f"[Info] Converting {len(challenge_template.machine_templates)} VMs to Proxmox templates", flush=True)
    templates_converted = 0

    for machine_template in challenge_template.machine_templates.values():
        try:
            print(f"[Info] Converting VM {machine_template.id} to template", flush=True)
            convert_vm_to_template_api_call(machine_template.id)
            templates_converted += 1
            print(f"[Info] Successfully converted VM {machine_template.id} to template", flush=True)
        except Exception as e:
            print(f"[Error] Failed to convert VM {machine_template.id} to template: {e}", flush=True)
            raise RuntimeError(f"Failed to convert VM to template: {e}")

    print(f"[Info] Successfully converted {templates_converted} VMs to templates", flush=True)


def mark_challenge_template_as_ready(challenge_template, db_conn):
    """
    Mark the challenge template as ready in the database.
    """
    print(f"[Info] Marking challenge template {challenge_template.id} as ready_to_launch in database", flush=True)

    with db_conn.cursor() as cursor:
        cursor.execute("UPDATE challenge_templates SET ready_to_launch = TRUE WHERE id = %s", (challenge_template.id,))
        db_conn.commit()

    print(f"[Info] Challenge template {challenge_template.id} successfully marked as ready", flush=True)


def undo_import_machine_templates(challenge_template):
    """
    Undo the import of machine templates.
    """
    print(f"[Error] Undoing machine template import for challenge {challenge_template.id}", flush=True)
    vms_deleted = 0

    for machine_template in challenge_template.machine_templates.values():
        try:
            print(f"[Info] Attempting to delete VM {machine_template.id}", flush=True)
            delete_vm_api_call(machine_template)
            vms_deleted += 1
            print(f"[Info] Successfully deleted VM {machine_template.id}", flush=True)
        except Exception as e:
            print(f"[Warning] Failed to delete VM {machine_template.id} via API: {e}", flush=True)
            try:
                print(f"[Debug] Attempting to unlock VM {machine_template.id}", flush=True)
                subprocess.run(["qm", "unlock", str(machine_template.id)], check=True, capture_output=True)
            except Exception:
                pass
            try:
                subprocess.run(["qm", "stop", str(machine_template.id)], check=True, capture_output=True)
            except Exception:
                pass
            try:
                print(f"[Debug] Attempting to destroy VM {machine_template.id}", flush=True)
                subprocess.run(["qm", "destroy", str(machine_template.id), "--skiplock"], check=True, capture_output=True)
                vms_deleted += 1
                print(f"[Info] Successfully destroyed VM {machine_template.id}", flush=True)
            except Exception as e3:
                print(f"[Warning] Failed to destroy VM {machine_template.id}: {e3}", flush=True)

    print(f"[Info] Cleanup completed - {vms_deleted} VMs deleted during undo process", flush=True)