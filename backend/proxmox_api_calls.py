import os
from dotenv import load_dotenv
import requests
import subprocess
import fcntl

from backend.cloud_init_ip_pool import ip_pool

load_dotenv()
node = os.getenv("PROXMOX_HOSTNAME", "pve")


def make_api_call(method, endpoint, data=None):
    """
    Make an API call to Proxmox.
    """
    proxmox_url = os.getenv("PROXMOX_URL")
    proxmox_api_token = os.getenv("PROXMOX_API_TOKEN")

    headers = {}
    if data is not None:
        headers = {"Content-Type": "application/json"}

    if proxmox_api_token:
        headers["Authorization"] = f"PVEAPIToken={proxmox_api_token}"

    url = f"{proxmox_url}/{endpoint}"
    response = requests.request(method, url, headers=headers, json=data, verify="/etc/pve/pve-root-ca.pem")

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to make API call: {endpoint} - {response.status_code} - {response.text}")


def clone_vm_api_call(machine_template, machine):
    """
    Clone a virtual machine in Proxmox.
    """
    endpoint = f"api2/json/nodes/{node}/qemu/{machine_template.id}/clone"
    data = {
        "newid": machine.id,
        "full": False
    }
    return make_api_call("POST", endpoint, data)


def create_network_api_call(network):
    """
    Create a network in Proxmox.
    """
    endpoint = f"api2/json/nodes/{node}/network"
    data = {
        "iface": network.host_device,
        "type": "bridge",
        "cidr": network.router_ip + "/" + network.subnet_mask,
        "autostart": True,
    }
    return make_api_call("POST", endpoint, data)


def reload_network_api_call():
    """
    Reload a network in Proxmox.
    """
    RELOAD_LOCK_FILE = "/var/lock/reload_network.lock"
    with open(RELOAD_LOCK_FILE, "w") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)

            endpoint = f"api2/json/nodes/{node}/network"
            data = {}
            make_api_call("PUT", endpoint, data)

            fcntl.flock(lock_file, fcntl.LOCK_UN)
        except BlockingIOError:
            pass


def delete_vm_api_call(machine):
    """
    Delete a virtual machine in Proxmox.
    """
    endpoint = f"api2/json/nodes/{node}/qemu/{machine.id}"
    return make_api_call("DELETE", endpoint)


def delete_network_api_call(network):
    """
    Delete a network in Proxmox.
    """
    endpoint = f"api2/json/nodes/{node}/network/{network.host_device}"
    return make_api_call("DELETE", endpoint)


def attach_networks_to_vm_api_call(machine):
    """
    Attach networks to a virtual machine in Proxmox.
    """
    responses = []

    for local_connection_id, connection in enumerate(machine.connections.values()):
        endpoint = f"api2/json/nodes/{node}/qemu/{machine.id}/config"
        data = {
            f"net{local_connection_id}": f"model=e1000,"
                                         f"bridge={connection.network.host_device},"
                                         f"macaddr={connection.client_mac}"
        }

        responses.append(make_api_call("PUT", endpoint, data))

    return responses


def launch_vm_api_call(machine):
    """
    Launch a virtual machine in Proxmox.
    """
    endpoint = f"api2/json/nodes/{node}/qemu/{machine.id}/status/start"
    return make_api_call("POST", endpoint)


def stop_vm_api_call(machine):
    """
    Stop a virtual machine in Proxmox.
    """

    subprocess.run(["qm", "stop", str(machine.id), "--skiplock"], check=True, capture_output=True)

    """
    endpoint = f"api2/json/nodes/{node}/qemu/{machine.id}/status/stop"
    return make_api_call("POST", endpoint)
    """


def shutdown_vm_api_call(machine):
    """
    Shutdown a virtual machine in Proxmox.
    """

    subprocess.run(["qm", "stop", str(machine.id), "--skiplock"], check=True, capture_output=True)


def vm_is_stopped_api_call(machine):
    """
    Check if a virtual machine is stopped in Proxmox.
    """

    out = subprocess.run(["qm", "status", str(machine.id)], check=True, capture_output=True, text=True)
    return "stopped" in out.stdout

    """
    endpoint = f"api2/json/nodes/{node}/qemu/{machine.id}/status/current"
    response = make_api_call("GET", endpoint)

    return response["data"]["status"] == "stopped"
    """


def attach_cloud_init_drive(machine_template_id, storage="local-lvm"):
    """
    Attach a Cloud-Init disk to the VM so that cicustom will work.
    """
    endpoint = f"api2/json/nodes/{node}/qemu/{machine_template_id}/config"
    data = {
        "ide2": f"{storage}:cloudinit"
    }
    return make_api_call("PUT", endpoint, data)


def detach_cloud_init_drive(machine_template_id):
    """
    Detach the Cloud-Init disk after configuration is done.
    """
    endpoint = f"api2/json/nodes/{node}/qemu/{machine_template_id}/config"
    data = {
        "ide2": "none"
    }
    return make_api_call("PUT", endpoint, data)


def generate_prefixed_mac_address(vm_id: int, mac_index) -> str:
    """
    Generate a unique MAC address from a VM ID.
    Uses a locally administered prefix and encodes the VM ID in the last 4 bytes.
    Supports VM IDs up to 999,999,999.
    """
    if not (0 <= vm_id <= 999_999_999):
        raise ValueError("VM ID must be between 0 and 999,999,999")

    base_mac = mac_index # locally administered prefix (first 2 bytes)

    vm_bytes = vm_id.to_bytes(4, 'big')
    mac_suffix = ":".join(f"{b:02x}" for b in vm_bytes)

    mac_address = f"{base_mac}:{mac_suffix}"
    return mac_address.lower()


def initial_configuration_api_call(machine_template):
    """
    Initial configuration of a virtual machine in Proxmox.
    """
    endpoint = f"api2/json/nodes/{node}/qemu/{machine_template.id}/config"
    data = {
        "memory": machine_template.ram,
        "cores": machine_template.cores,
        "sockets": 1,
        "cpu": "kvm64",
        "scsihw": "virtio-scsi-pci",
        "agent": 1
    }
    return make_api_call("PUT", endpoint, data)


def add_cloud_ipconfig(machine_template, init_ip, nic=30, gw="10.32.0.1"):
    endpoint = f"api2/json/nodes/{node}/qemu/{machine_template.id}/config"
    data = {
        f"ipconfig{nic}": f"ip={init_ip}/20,gw={gw}"
    }

    return make_api_call("PUT", endpoint, data)


def add_cloud_ipconfig_ipv6(machine_template, init_ip, nic=31, gw="fd12:3456:789a:1::1"):
    endpoint = f"api2/json/nodes/{node}/qemu/{machine_template.id}/config"
    data = {
        f"ipconfig{nic}": f"ip6={init_ip}/64,gw6={gw}"
    }

    return make_api_call("PUT", endpoint, data)


def set_cicustom_api_call(machine_id,user_custom_path,meta_custom_path):
    endpoint = f"api2/json/nodes/{node}/qemu/{machine_id}/config"
    data = {
        "cicustom": f"user={user_custom_path},meta={meta_custom_path}"
    }

    return make_api_call("PUT", endpoint, data)


def add_network_device_api_call(machine_id, nic="net30" ,bridge="vmbr-cloud", model="e1000", mac_index="0A:00"):
    """
    Add a network device to a virtual machine for internet access.
    """
    mac_address = generate_prefixed_mac_address(machine_id, mac_index)
    endpoint = f"api2/json/nodes/{node}/qemu/{machine_id}/config"
    data = {
        nic: f"model={model},bridge={bridge},macaddr={mac_address}"
    }
    return make_api_call("PUT", endpoint, data)


def detach_network_device_api_call(vmid, nic="net30"):
    """
    Remove a network device from a VM.
    """
    endpoint = f"api2/json/nodes/{node}/qemu/{vmid}/config"
    data = {
        "delete": nic
    }
    return make_api_call("PUT", endpoint, data)


def convert_vm_to_template_api_call(machine_template_id):
    """
    Convert a virtual machine to a template in Proxmox.
    """
    endpoint = f"api2/json/nodes/{node}/qemu/{machine_template_id}/template"
    return make_api_call("POST", endpoint)


def vm_exists_api_call(machine):
    """
    Check if a virtual machine exists in Proxmox.
    """
    endpoint = f"api2/json/nodes/{node}/qemu/{machine.id}/status/current"
    try:
        make_api_call("GET", endpoint)
        return True
    except Exception:
        return False


def vm_is_template_api_call(machine_template):
    """
    Check if a virtual machine is a template in Proxmox.
    """
    endpoint = f"api2/json/nodes/{node}/qemu/{machine_template.id}/config"
    response = make_api_call("GET", endpoint)

    return response["data"]["template"] == 0 if "template" in response["data"] else False


def get_sockets_api_call(machine_template):
    """
    Get the number of sockets for a virtual machine in Proxmox.
    """
    endpoint = f"api2/json/nodes/{node}/qemu/{machine_template.id}/config"
    response = make_api_call("GET", endpoint)

    return response["data"]["sockets"] if "sockets" in response["data"] else 1


def get_memory_api_call(machine_template):
    """
    Get the memory size for a virtual machine in Proxmox.
    """
    endpoint = f"api2/json/nodes/{node}/qemu/{machine_template.id}/config"
    response = make_api_call("GET", endpoint)

    return response["data"]["memory"]


def network_device_exists_api_call(network):
    """
    Check if a network device exists in Proxmox.
    """
    endpoint = f"api2/json/nodes/{node}/network/{network.host_device}"
    try:
        make_api_call("GET", endpoint)
        return True
    except Exception:
        return False