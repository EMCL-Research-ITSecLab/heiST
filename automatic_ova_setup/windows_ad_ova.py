import sys
import random
import shutil
from pathlib import Path

from provisioning.download import download_file
from provisioning.vbox import VBOXMANAGE, ensure_nat_network, shutdown_vm, detach_isos, export_ova
from provisioning.ssh_control import _get_paramiko, get_adapter_ip
from provisioning.build import build_and_boot_vm
from provisioning.ad import promote_dc, join_domain

DOMAIN_NAME = "corp.local"
DOMAIN_NETBIOS = "CORP"
DOMAIN_SAFE_MODE_PASSWORD = "P@ssw0rd123!"

ADMIN_USERNAME = "ctf_admin"
VM_PASSWORD = "Admin123"

VM_MEMORY = 4096
VM_CPUS = 2
VM_DISK_SIZE_MB = 32 * 1024

WORKING_DIR = Path(__file__).resolve().parent / "vm-build-ad"
ISO_DIR = WORKING_DIR / "iso"
OVA_OUTPUT_DIR = WORKING_DIR / "ova"

WINDOWS_ISO_URL = "https://go.microsoft.com/fwlink/p/?LinkID=2195174&clcid=0x409&culture=en-us&country=US"
VIRTIO_ISO_URL = "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/archive-virtio/virtio-win-0.1.285-1/virtio-win-0.1.285.iso"
WINDOWS_ISO_NAME = "windows_server_2016.iso"
VIRTIO_ISO_NAME = "virtio-win-0.1.285.iso"
WINDOWS_ISO = ISO_DIR / WINDOWS_ISO_NAME
VIRTIO_ISO = ISO_DIR / VIRTIO_ISO_NAME

NATNETWORK_NAME = "ctf-ad-natnet"
NATNETWORK_CIDR = "10.50.0.0/24"
NATNETWORK_PREFIX = "10.50.0."

VMS = {
    "dc": {
        "VM_NAME": "dc01-corp",
        "COMPUTER_NAME": "DC01",
        "ROLE": "dc",
        "SSH_HOST_PORT": random.randint(20000, 30000),
    },
    "member": {
        "VM_NAME": "srv01-corp",
        "COMPUTER_NAME": "SRV01",
        "ROLE": "member",
        "SSH_HOST_PORT": random.randint(30001, 40000),
    },
}


def main():
    if shutil.which(VBOXMANAGE) is None:
        print("ERROR: VBoxManage not found. Install VirtualBox on this host first.")
        sys.exit(1)

    _get_paramiko()

    print("=" * 60)
    print("Active Directory Domain Environment - Automated Setup (VirtualBox -> OVA)")
    print("=" * 60)
    print(f"Domain: {DOMAIN_NAME} ({DOMAIN_NETBIOS})")
    for vm_config in VMS.values():
        print(f"  - {vm_config['VM_NAME']} (role={vm_config['ROLE']}, "
              f"SSH forwarded port: {vm_config['SSH_HOST_PORT']})")
    print("=" * 60)

    WORKING_DIR.mkdir(parents=True, exist_ok=True)
    ISO_DIR.mkdir(parents=True, exist_ok=True)

    download_file(WINDOWS_ISO_URL, WINDOWS_ISO, "Windows Server 2016 ISO")
    download_file(VIRTIO_ISO_URL, VIRTIO_ISO, "VirtIO drivers ISO")

    ensure_nat_network(NATNETWORK_NAME, NATNETWORK_CIDR)

    dc_config = VMS["dc"]
    member_config = VMS["member"]

    def build(vm_config):
        build_and_boot_vm(
            vm_config, ISO_DIR, WORKING_DIR, WINDOWS_ISO, VIRTIO_ISO,
            memory=VM_MEMORY, cpus=VM_CPUS, disk_size_mb=VM_DISK_SIZE_MB,
            admin_username=ADMIN_USERNAME, admin_password=VM_PASSWORD,
            natnetwork_name=NATNETWORK_NAME,
        )

    print("\n--- Building Domain Controller ---")
    build(dc_config)
    dc_internal_ip = promote_dc(dc_config["SSH_HOST_PORT"], DOMAIN_NAME, DOMAIN_NETBIOS,
                                DOMAIN_SAFE_MODE_PASSWORD, ADMIN_USERNAME, VM_PASSWORD,
                                NATNETWORK_PREFIX)

    print("\n--- Building Domain Member ---")
    build(member_config)
    join_domain(member_config["SSH_HOST_PORT"], dc_internal_ip, DOMAIN_NAME, DOMAIN_NETBIOS, NATNETWORK_PREFIX,
                ADMIN_USERNAME, VM_PASSWORD, VM_PASSWORD)

    print("\n--- Finalizing (shutdown, detach ISOs, export OVAs) ---")
    for vm_config in VMS.values():
        name = vm_config["VM_NAME"]
        ova_path = OVA_OUTPUT_DIR / f"{name}.ova"
        shutdown_vm(name, vm_config["SSH_HOST_PORT"], ADMIN_USERNAME, VM_PASSWORD)
        detach_isos(name)
        export_ova(name, ova_path)
    print("\n" + "=" * 60)
    print("Setup Complete")
    print("=" * 60)
    print(f"Domain: {DOMAIN_NAME}")
    print(f"Domain Admin: {DOMAIN_NETBIOS}\\Administrator / {VM_PASSWORD}")
    print(f"Local Admin: Administrator / {ADMIN_USERNAME} - both / {VM_PASSWORD}")
    for vm_config in VMS.values():
        name = vm_config["VM_NAME"]
        print(f"  {name} OVA: {OVA_OUTPUT_DIR / f'{name}.ova'}")
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