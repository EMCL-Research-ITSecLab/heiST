import sys
import random
import shutil
from pathlib import Path

from provisioning.download import download_file
from provisioning.vbox import VBOXMANAGE, shutdown_vm, detach_isos, export_ova
from provisioning.ssh_control import _get_paramiko
from provisioning.build import build_and_boot_vm

ADMIN_USERNAME = "ctf_admin"
VM_PASSWORD = "Admin123"

VM_MEMORY = 4096
VM_CPUS = 2
VM_DISK_SIZE_MB = 32 * 1024

VM_NAME = "windows-server-2016"
WORKING_DIR = Path(__file__).resolve().parent / "vm-build"
ISO_DIR = WORKING_DIR / "iso"
OVA_OUTPUT_DIR = WORKING_DIR / "ova"
OVA_PATH = OVA_OUTPUT_DIR / f"{VM_NAME}.ova"

WINDOWS_ISO_URL = "https://go.microsoft.com/fwlink/p/?LinkID=2195174&clcid=0x409&culture=en-us&country=US"
VIRTIO_ISO_URL = "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/archive-virtio/virtio-win-0.1.285-1/virtio-win-0.1.285.iso"
WINDOWS_ISO_NAME = "windows_server_2016.iso"
VIRTIO_ISO_NAME = "virtio-win-0.1.285.iso"
WINDOWS_ISO = ISO_DIR / WINDOWS_ISO_NAME
VIRTIO_ISO = ISO_DIR / VIRTIO_ISO_NAME

VM_CONFIG = {
    "VM_NAME": VM_NAME,
    "COMPUTER_NAME": "WIN2016",
    "SSH_HOST_PORT": random.randint(20000, 60000),
}


def main():
    if shutil.which(VBOXMANAGE) is None:
        print("ERROR: VBoxManage not found. Install VirtualBox on this host first.")
        sys.exit(1)

    _get_paramiko()

    print("=" * 60)
    print("Windows Server 2016 - Automated Setup (VirtualBox -> OVA)")
    print("=" * 60)
    print(f"VM name: {VM_NAME}")
    print(f"Password: {VM_PASSWORD}")
    print(f"SSH forwarded port (127.0.0.1): {VM_CONFIG['SSH_HOST_PORT']}")
    print(f"Output OVA: {OVA_PATH}")
    print("=" * 60)

    WORKING_DIR.mkdir(parents=True, exist_ok=True)
    ISO_DIR.mkdir(parents=True, exist_ok=True)

    download_file(WINDOWS_ISO_URL, WINDOWS_ISO, "Windows Server 2016 ISO")
    download_file(VIRTIO_ISO_URL, VIRTIO_ISO, "VirtIO drivers ISO")

    build_and_boot_vm(
        VM_CONFIG, ISO_DIR, WORKING_DIR, WINDOWS_ISO, VIRTIO_ISO,
        memory=VM_MEMORY, cpus=VM_CPUS, disk_size_mb=VM_DISK_SIZE_MB,
        admin_username=ADMIN_USERNAME, admin_password=VM_PASSWORD,
    )

    shutdown_vm(VM_NAME)
    detach_isos(VM_NAME)
    export_ova(VM_NAME, OVA_PATH)

    print("\n" + "=" * 60)
    print("Setup Complete")
    print("=" * 60)
    print(f"OVA ready at: {OVA_PATH}")
    print(f"Username: Administrator / {ADMIN_USERNAME}")
    print(f"Password: {VM_PASSWORD}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
