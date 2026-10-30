import shutil
import time
from pathlib import Path

from .process import run_command

VBOXMANAGE = shutil.which("VBoxManage") or shutil.which("vboxmanage") or "VBoxManage"


def vbox_vm_exists(name):
    result = run_command([VBOXMANAGE, "list", "vms"], capture=True, check=False)
    return f'"{name}"' in result.stdout


def vbox_vm_state(name):
    result = run_command([VBOXMANAGE, "showvminfo", name, "--machinereadable"], capture=True, check=False)
    for line in result.stdout.splitlines():
        if line.startswith("VMState="):
            return line.split("=", 1)[1].strip('"')
    return "unknown"


def vbox_delete_vm(name):
    print(f"VM {name} already exists. Deleting...")
    run_command([VBOXMANAGE, "controlvm", name, "poweroff"], check=False)
    time.sleep(3)
    run_command([VBOXMANAGE, "unregistervm", name, "--delete"], check=False)


def ensure_nat_network(name, cidr):
    """Create a shared NAT Network if it doesn't exist yet."""
    result = run_command([VBOXMANAGE, "list", "natnets"], capture=True, check=False)
    if name in result.stdout:
        print(f"NAT Network {name} already exists")
        return

    print(f"Creating NAT Network {name} ({cidr})...")
    run_command([
        VBOXMANAGE, "natnetwork", "add",
        "--netname", name,
        "--network", cidr,
        "--enable",
        "--dhcp", "on",
    ])


def create_virtualbox_vm(vm_config, vm_dir: Path, working_dir: Path, windows_iso: Path, virtio_iso: Path,
                          autounattend_iso: Path, memory: int, cpus: int, disk_size_mb: int,
                          os_type: str = "Windows2016_64", natnetwork_name: str = None):
    """Create and configure the VirtualBox VM used to run the install."""
    name = vm_config["VM_NAME"]
    print(f"Creating VirtualBox VM {name}...")

    if vbox_vm_exists(name):
        vbox_delete_vm(name)

    vm_dir.mkdir(parents=True, exist_ok=True)
    disk_path = vm_dir / f"{name}.vdi"

    run_command([
        VBOXMANAGE, "createvm",
        "--name", name,
        "--ostype", os_type,
        "--basefolder", str(working_dir),
        "--register",
    ])

    modify_cmd = [
        VBOXMANAGE, "modifyvm", name,
        "--memory", str(memory),
        "--cpus", str(cpus),
        "--nic1", "nat",
    ]
    if natnetwork_name:
        modify_cmd += ["--nic2", "natnetwork", "--nat-network2", natnetwork_name]
    modify_cmd += [
        "--graphicscontroller", "vboxsvga",
        "--audio-driver", "none",
        "--boot1", "dvd",
        "--boot2", "disk",
        "--boot3", "none",
        "--boot4", "none",
    ]
    run_command(modify_cmd)

    run_command([
        VBOXMANAGE, "modifyvm", name,
        "--natpf1", f"guestssh,tcp,,{vm_config['SSH_HOST_PORT']},,22",
    ])

    run_command([
        VBOXMANAGE, "createmedium", "disk",
        "--filename", str(disk_path),
        "--size", str(disk_size_mb),
        "--format", "VDI",
    ])

    run_command([
        VBOXMANAGE, "storagectl", name,
        "--name", "SATA Controller",
        "--add", "sata",
        "--controller", "IntelAhci",
        "--portcount", "4",
        "--bootable", "on",
    ])

    run_command([
        VBOXMANAGE, "storageattach", name,
        "--storagectl", "SATA Controller",
        "--port", "0", "--device", "0",
        "--type", "hdd",
        "--medium", str(disk_path),
    ])

    run_command([
        VBOXMANAGE, "storageattach", name,
        "--storagectl", "SATA Controller",
        "--port", "1", "--device", "0",
        "--type", "dvddrive",
        "--medium", str(windows_iso),
    ])

    run_command([
        VBOXMANAGE, "storageattach", name,
        "--storagectl", "SATA Controller",
        "--port", "2", "--device", "0",
        "--type", "dvddrive",
        "--medium", str(virtio_iso),
    ])

    run_command([
        VBOXMANAGE, "storageattach", name,
        "--storagectl", "SATA Controller",
        "--port", "3", "--device", "0",
        "--type", "dvddrive",
        "--medium", str(autounattend_iso),
    ])

    print(f"VM {name} configuration complete")


def start_vm_headless(name):
    print(f"Starting VM {name} (headless)...")
    run_command([VBOXMANAGE, "startvm", name, "--type", "headless"])


def shutdown_vm(name, ssh_port=None, username=None, password=None, timeout=300):
    """Graceful shutdown: guest-side shutdown over SSH first, then ACPI, then hard poweroff."""
    if ssh_port is not None:
        from .ssh_control import ssh_run_expect_disconnect
        print(f"Shutting down VM {name} from inside the guest (SSH)...")
        try:
            ssh_run_expect_disconnect(ssh_port, "shutdown /s /t 0 /f", username, password, max_wait=30)
        except Exception as e:
            print(f"[Info] SSH shutdown call ended: {e}")
        if _wait_poweroff(name, timeout):
            return
        print("Guest-side shutdown didn't finish in time, trying ACPI...")

    run_command([VBOXMANAGE, "controlvm", name, "acpipowerbutton"], check=False)
    if _wait_poweroff(name, 60):
        return

    print("VM didn't shut down gracefully, forcing power off...")
    run_command([VBOXMANAGE, "controlvm", name, "poweroff"], check=False)
    _wait_poweroff(name, 30)


def _wait_poweroff(name, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if vbox_vm_state(name) == "poweroff":
            print(f"VM {name} powered off")
            return True
        time.sleep(5)
    return False


def detach_isos(name, ports=("1", "2", "3")):
    """Detach the DVDs before export."""
    for port in ports:
        run_command([
            VBOXMANAGE, "storageattach", name,
            "--storagectl", "SATA Controller",
            "--port", port, "--device", "0",
            "--type", "dvddrive",
            "--medium", "none",
        ], check=False)


def export_ova(name, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    print(f"Exporting {name} -> {output_path}")
    run_command([
        VBOXMANAGE, "export", name,
        "--output", str(output_path),
        "--ovf10",
        "--options", "nomacs",
    ])
    print(f"Export complete: {output_path}")
