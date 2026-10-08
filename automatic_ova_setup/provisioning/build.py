import sys
from pathlib import Path

from .vbox import create_virtualbox_vm, start_vm_headless
from .ssh_control import wait_for_ssh, wait_for_setup_complete
from .windows2016 import generate_setup_script, generate_autounattend_xml, create_autounattend_iso


def build_and_boot_vm(vm_config, iso_dir: Path, working_dir: Path, windows_iso: Path, virtio_iso: Path,
                       memory: int, cpus: int, disk_size_mb: int, admin_username: str, admin_password: str,
                       os_type: str = "Windows2016_64", natnetwork_name: str = None):
    """Download ISOs (once), create the VM, boot it, and wait for first-boot setup to finish."""
    name = vm_config["VM_NAME"]
    vm_dir = working_dir / name
    port = vm_config["SSH_HOST_PORT"]

    vm_dir.mkdir(parents=True, exist_ok=True)
    autounattend_iso = iso_dir / f"autounattend-{name}.iso"

    setup_script_path = generate_setup_script(vm_dir)
    autounattend_path = generate_autounattend_xml(vm_dir, vm_config["COMPUTER_NAME"], admin_username, admin_password)
    create_autounattend_iso(vm_dir, autounattend_iso, autounattend_path, setup_script_path)

    create_virtualbox_vm(vm_config, vm_dir, working_dir, windows_iso, virtio_iso, autounattend_iso,
                          memory, cpus, disk_size_mb, os_type=os_type, natnetwork_name=natnetwork_name)
    start_vm_headless(name)

    if not wait_for_ssh(port):
        print(f"ERROR: SSH never came up for {name} - check the install (e.g. VBoxManage --type gui, "
              f"or screenshot via VBoxManage controlvm {name} screenshotpng).")
        sys.exit(1)

    wait_for_setup_complete(port, admin_username, admin_password)
