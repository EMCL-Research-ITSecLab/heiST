import os
from .identity import ownership_marker, ownership_tags
from heist.environment import load_backend_env as load_dotenv
import requests
import re
import subprocess

from heist.infrastructure.network.cloud_init_pool import ip_pool
from heist.infrastructure.proxmox.settings import challenge_cpu_type
from heist.infrastructure.proxmox.tasks import wait_for_task
from heist.infrastructure.locking import operation_guard

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
    response = requests.request(method, url, headers=headers, json=data, verify="/etc/pve/pve-root-ca.pem", timeout=(10, 60))

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to make API call: {endpoint} - {response.status_code} - {response.text}")


def require_vm_ownership(machine):
    response=make_api_call('GET',f'api2/json/nodes/{node}/qemu/{machine.id}/config')
    value=response.get('data')
    if not isinstance(value,dict) or not isinstance(value.get('tags'),str):
        raise RuntimeError('VM ownership is not confirmed; preserve it for reconciliation')
    tags=set(value['tags'].split(';'))
    if 'heist-managed' not in tags or {tag for tag in tags if tag.startswith('heist-vm-')}!={'heist-vm-'+str(machine.id)}:
        raise RuntimeError('VM ownership is not confirmed; preserve it for reconciliation')
    return value


def clone_vm_api_call(machine_template, machine):
    """
    Clone a virtual machine in Proxmox.
    """
    source=require_vm_ownership(machine_template)
    endpoint = f"api2/json/nodes/{node}/qemu/{machine_template.id}/clone"
    data = {
        "newid": machine.id,
        "full": False
    }
    response = make_api_call("POST", endpoint, data)
    wait_for_task(make_api_call, node, response)
    target=make_api_call('GET',f'api2/json/nodes/{node}/qemu/{machine.id}/config').get('data')
    if not isinstance(target,dict) or target.get('tags')!=source.get('tags'):
        raise RuntimeError('Cloned VM identity is not confirmed')
    make_api_call('PUT',f'api2/json/nodes/{node}/qemu/{machine.id}/config',{'tags':ownership_tags(machine.id,target.get('tags',''))})
    require_vm_ownership(machine)
    return response


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
    directory = os.getenv('HEIST_NETWORK_LOCK_DIRECTORY', '/run/heist-network-operations')
    with operation_guard(directory, 1):
        response = make_api_call('PUT', f'api2/json/nodes/{node}/network', {})
        wait_for_task(make_api_call, node, response, timeout=90)


def delete_vm_api_call(machine):
    """
    Delete a virtual machine in Proxmox.
    """
    if not vm_exists_api_call(machine):
        return {'data': None, 'already_absent': True}
    require_vm_ownership(machine)
    endpoint = f"api2/json/nodes/{node}/qemu/{machine.id}"
    response = make_api_call("DELETE", endpoint)
    wait_for_task(make_api_call, node, response)
    if vm_exists_api_call(machine):
        raise RuntimeError('VM deletion task completed but the VM is still present')
    return response


def stop_vm_api_call(machine):
    require_vm_ownership(machine)
    if vm_is_stopped_api_call(machine):
        return
    response = make_api_call('POST', f'api2/json/nodes/{node}/qemu/{machine.id}/status/stop')
    wait_for_task(make_api_call, node, response, timeout=180)
    if not vm_is_stopped_api_call(machine):
        raise RuntimeError('VM stop task completed but the VM is still running')


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


def shutdown_vm_api_call(machine):
    """Cleanly shut down an imported template; never force-freeze dirty filesystems."""
    require_vm_ownership(machine)
    subprocess.run(["qm", "shutdown", str(machine.id), "--timeout", "180", "--forceStop", "0"],
                   check=True, capture_output=True, timeout=210)


def vm_is_stopped_api_call(machine):
    """
    Check if a virtual machine is stopped in Proxmox.
    """

    endpoint = f"api2/json/nodes/{node}/qemu/{machine.id}/status/current"
    response = make_api_call("GET", endpoint)
    state = response.get('data', {}).get('status')
    if state not in ('running', 'stopped'):
        raise RuntimeError('VM status was not confirmed')
    return state == 'stopped'


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
        "cpu": challenge_cpu_type(),
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
    if type(vmid) is not int or vmid <= 0 or re.fullmatch(r'net[0-9]{1,2}', nic) is None:
        raise ValueError('Invalid temporary network device')
    configuration = make_api_call('GET', endpoint).get('data')
    if not isinstance(configuration, dict):
        raise RuntimeError('VM network configuration was not confirmed')
    if nic not in configuration:
        return {'already_absent': True}
    response = make_api_call('PUT', endpoint, {'delete': nic})
    configuration = make_api_call('GET', endpoint).get('data')
    if not isinstance(configuration, dict) or nic in configuration:
        raise RuntimeError('Temporary network detachment was not confirmed; retain its address lease')
    return response


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
    # A missing config and an unavailable API can both produce errors on the
    # per-VM endpoint. Only a successful authoritative list proves absence.
    response = make_api_call('GET', f'api2/json/nodes/{node}/qemu')
    values = response.get('data')
    if not isinstance(values, list) or any(not isinstance(value, dict) or type(value.get('vmid')) is not int for value in values):
        raise RuntimeError('VM inventory was not confirmed')
    return any(value['vmid'] == machine.id for value in values)


def vm_is_template_api_call(machine_template):
    """
    Check if a virtual machine is a template in Proxmox.
    """
    endpoint = f"api2/json/nodes/{node}/qemu/{machine_template.id}/config"
    response = make_api_call("GET", endpoint)

    return response['data'].get('template', 0) == 1


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
    response = make_api_call('GET', f'api2/json/nodes/{node}/network')
    values = response.get('data')
    if not isinstance(values, list) or any(not isinstance(value, dict) or not isinstance(value.get('iface'), str) for value in values):
        raise RuntimeError('Network inventory was not confirmed')
    return any(value['iface'] == network.host_device for value in values)
