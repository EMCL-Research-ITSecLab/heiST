import time
import urllib3
from tenacity import retry, stop_after_attempt, wait_fixed
from dotenv import load_dotenv, find_dotenv
import random
import requests
import subprocess
import os
from backend.network_input import remove_network_input_filter

from backend.DatabaseClasses import (
    ChallengeTemplate,
    ChallengeSubnet,
    Challenge,
    MachineTemplate,
    Machine,
    NetworkTemplate,
    Network,
    Connection
)
from backend.proxmox_api_calls import (
    vm_exists_api_call,
    delete_network_api_call,
    reload_network_api_call,
    network_device_exists_api_call
)
from backend.get_db_connection import db_connection_context

load_dotenv(find_dotenv())

CHALLENGES_ROOT_SUBNET = os.getenv("CHALLENGES_ROOT_SUBNET", "10.128.0.0")
CHALLENGES_ROOT_SUBNET_MASK = os.getenv("CHALLENGES_ROOT_SUBNET_MASK", "255.128.0.0")
CHALLENGES_ROOT_SUBNET_MASK_INT = sum(bin(int(x)).count('1') for x in CHALLENGES_ROOT_SUBNET_MASK.split('.'))
CHALLENGES_ROOT_SUBNET_CIDR = f"{CHALLENGES_ROOT_SUBNET}/{CHALLENGES_ROOT_SUBNET_MASK_INT}"

MONITORING_HOST = os.getenv("MONITORING_HOST", "10.0.0.103")
WAZUH_PORT = os.getenv("WAZUH_API_PORT", "55000")
WAZUH_USER = os.getenv("WAZUH_API_USER", "wazuh-wui")
WAZUH_PASSWORD = os.getenv("WAZUH_API_PASSWORD", "MyS3cr37P450r.*-")

DNSMASQ_INSTANCES_DIR = "/etc/dnsmasq-instances"

def teardown_challenge(challenge_id):
    """
    Stop a challenge for a user.
    """

    with db_connection_context() as db_conn:
        challenge = fetch_challenge(challenge_id, db_conn)
        fetch_machines(challenge, db_conn)
        stop_machines(challenge)
        delete_machines(challenge)
        fetch_networks(challenge, db_conn)
        delete_network_devices(challenge)
        stop_dnsmasq_instances(challenge)
        remove_challenge_from_wazuh(challenge)
        remove_database_entries(challenge, db_conn)



def fetch_challenge(challenge_id, db_conn):
    """
    Fetch the challenge for a user.
    """

    with db_conn.cursor() as cursor:
        cursor.execute("""
            WITH challenge_info AS (
                SELECT id, challenge_template_id, subnet
                FROM challenges
                WHERE id = %s
                FOR UPDATE SKIP LOCKED 
            )
            UPDATE challenges
            SET lifecycle_state = 'TERMINATING'
            WHERE id IN (SELECT id FROM challenge_info)
            RETURNING id, challenge_template_id, subnet    
        """, (challenge_id,))

        challenge_id, template_id, subnet = cursor.fetchone()

    challenge_template = ChallengeTemplate(template_id)
    challenge_subnet = ChallengeSubnet(subnet)
    challenge = Challenge(challenge_id, challenge_template, challenge_subnet.subnet)

    return challenge


def fetch_machines(challenge, db_conn):
    """
    Fetch the machines for a challenge.
    """

    with db_conn.cursor() as cursor:
        cursor.execute("SELECT id, machine_template_id FROM machines WHERE challenge_id = %s", (challenge.id,))

        for machine_id, template_id in cursor.fetchall():
            machine_template = MachineTemplate(machine_id, challenge.template)

            machine = Machine(machine_id, machine_template, challenge)

            challenge.add_machine(machine)


def fetch_networks(challenge, db_conn):
    """
    Fetch the networks for a challenge.
    """

    for machine in challenge.machines.values():
        with db_conn.cursor() as cursor1:
            cursor1.execute("""
                SELECT n.id, n.network_template_id, n.subnet, n.host_device, c.client_ip, c.client_mac
                FROM networks n, network_connections c
                WHERE c.network_id = n.id
                AND c.machine_id = %s
            """, (machine.id,))

            for network_id, template_id, subnet, host_device, client_ip, client_mac in cursor1.fetchall():
                if network_id not in challenge.networks:
                    with db_conn.cursor() as cursor2:
                        cursor2.execute("SELECT accessible, is_dmz "
                                        "FROM network_templates "
                                        "WHERE id = %s", (template_id,))
                        accessible, is_dmz = cursor2.fetchone()

                    network_template = NetworkTemplate(template_id, accessible)
                    network = Network(network_id, network_template, subnet, host_device, accessible)
                    network.set_is_dmz(is_dmz)

                    challenge.add_network(network)

                connection = Connection(machine, challenge.networks[network_id], client_mac, client_ip)
                challenge.networks[network_id].add_connection(connection)


def delete_wazuh_agent(machine_id):
    """
    Delete a Wazuh agent by machine ID using Wazuh Manager API.

    Args:
        machine_id: The VM ID used to identify the agent

    Returns:
        bool: True if deletion was successful, False otherwise
    """

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    agent_name = f"agent_{machine_id}"
    base_url = f"https://{MONITORING_HOST}:{WAZUH_PORT}"

    try:
        auth_response = requests.post(
            f"{base_url}/security/user/authenticate?raw=true",
            auth=(WAZUH_USER, WAZUH_PASSWORD),
            verify=False,
            timeout=10
        )

        if auth_response.status_code != 200:
            return False

        token = auth_response.text.strip()
        headers = {"Authorization": f"Bearer {token}"}

        search_response = requests.get(
            f"{base_url}/agents",
            headers=headers,
            params={"name": agent_name},
            verify=False,
            timeout=10
        )

        if search_response.status_code != 200:
            return False

        data = search_response.json()
        agents = data.get("data", {}).get("affected_items", [])

        if not agents:
            return False

        agent_id = agents[0]["id"]

        delete_response = requests.delete(
            f"{base_url}/agents",
            headers=headers,
            params={
                "agents_list": agent_id,
                "status": "all",
                "older_than": "0s"
            },
            verify=False,
            timeout=10
        )

        if delete_response.status_code == 200:
            return True
        else:
            return False

    except Exception as e:
        return False


@retry(stop=stop_after_attempt(5), wait=wait_fixed(1))
def stop_machines(challenge):
    """
    Stop the machines for a challenge.
    """
    existing_machines = {}

    # Remove nonexistent machines
    for machine in challenge.machines.values():
        if vm_exists_api_call(machine):
            existing_machines[machine.id] = machine

    for machine in existing_machines.values():
        try:
            out = subprocess.run(["qm", "stop", str(machine.id), "--skiplock"], check=True, capture_output=True)
        except Exception as e:
            print(f"[Warning] Failed to stop VM {machine.id}: {e}", flush=True)
            try:
                print(out.stdout.decode(), flush=True)
                print(out.stderr.decode(), flush=True)
            except Exception:
                pass


@retry(stop=stop_after_attempt(5), wait=wait_fixed(1))
def delete_machines(challenge):
    """
    Delete the machines for a challenge.
    """

    existing_machines = {}

    # Remove nonexistent machines
    for machine in challenge.machines.values():
        if vm_exists_api_call(machine):
            existing_machines[machine.id] = machine

    for machine in existing_machines.values():
        max_retries = 5
        retries = 0
        while retries < max_retries:
            try:
                out = subprocess.run(["qm", "destroy", str(machine.id), "--skiplock"], check=True, capture_output=True)
            except Exception as e:
                print(f"[Warning] Failed to destroy VM {machine.id}: {e}", flush=True)
                try:
                    print(out.stdout.decode(), flush=True)
                    print(out.stderr.decode(), flush=True)
                except Exception:
                    pass

            time.sleep(random.randint(1, 10) // 10.)
            retries += 1


def delete_network_devices(challenge):
    """
    Delete the networks for a challenge.
    """

    for network in challenge.networks.values():
        try:
            delete_network_api_call(network)
        except Exception:
            pass

        remove_network_input_filter(network.host_device)

    reload_network_api_call()


def wait_for_network_devices_deletion(challenge, try_timeout=3, max_tries=10):
    """
    Wait for the networks for a challenge to be deleted.
    """

    all_networks_deleted = False
    tries = 0
    while not all_networks_deleted and tries < max_tries:
        tries += 1
        try_start = time.time()

        while not time.time() - try_start < try_timeout and not all_networks_deleted:
            all_networks_deleted = True
            for network in challenge.networks.values():
                if os.path.exists(f"/sys/class/net/{network.host_device}"):
                    all_networks_deleted = False

        if not all_networks_deleted:
            reload_network_api_call()

    if not all_networks_deleted:
        raise Exception(f"Not all network devices could be deleted. Existing devices: {', '.join(str(n.host_device) for n in challenge.networks.values() if network_device_exists_api_call(n))}.")


def delete_iptables_rules(challenge):
    """
    Remove iptables rules previously added for the given user VPN IP.
    """

    for network in challenge.networks.values():
        # Allow intra-network traffic
        subprocess.run(
            ["iptables", "-D", "FORWARD", "-i", network.host_device, "-o", network.host_device, "-j", "ACCEPT"],
            check=False, capture_output=True)

        # Allow DNS traffic to the router IP
        subprocess.run(
            ["iptables", "-D", "INPUT", "-i", network.host_device, "-d", network.router_ip, "-p", "udp", "--dport",
             "53", "-j", "ACCEPT"], check=False, capture_output=True)
        subprocess.run(
            ["iptables", "-D", "INPUT", "-i", network.host_device, "-d", network.router_ip, "-p", "tcp", "--dport",
             "53", "-j", "ACCEPT"], check=False, capture_output=True)

        # Disallow traffic to the router IP
        subprocess.run(["iptables", "-D", "INPUT", "-d", network.router_ip, "-j", "DROP"], check=False,
                       capture_output=True)

        if network.is_dmz:
            # Allow traffic from the DMZ to the outside
            subprocess.run(
                ["iptables", "-t", "nat", "-D", "POSTROUTING", "-o", "vmbr0", "-s", network.subnet, "!", "-d",
                 CHALLENGES_ROOT_SUBNET_CIDR, "-j", "MASQUERADE"], check=False, capture_output=True)
            subprocess.run(
                ["iptables", "-D", "FORWARD", "-i", network.host_device, "-o", "vmbr0", "-s", network.subnet, "!",
                 "-d", CHALLENGES_ROOT_SUBNET_CIDR, "-m", "conntrack", "--ctstate", "NEW,ESTABLISHED,RELATED", "-j",
                 "ACCEPT"], check=False, capture_output=True)
            subprocess.run(
                ["iptables", "-D", "FORWARD", "-i", "vmbr0", "-o", network.host_device, "-d", network.subnet, "!",
                 "-s", CHALLENGES_ROOT_SUBNET_CIDR, "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j",
                 "ACCEPT"], check=False, capture_output=True)


def stop_dnsmasq_instances(challenge):
    """
    Delete the dnsmasq configs for a challenge.
    """

    for network in challenge.networks.values():
        config_path = os.path.join(DNSMASQ_INSTANCES_DIR, f"dnsmasq_{network.host_device}.conf")
        pid_path = os.path.join(DNSMASQ_INSTANCES_DIR, f"dnsmasq_{network.host_device}.pid")
        leases_path = os.path.join(DNSMASQ_INSTANCES_DIR, f"dnsmasq_{network.host_device}.leases")
        log_path = os.path.join(DNSMASQ_INSTANCES_DIR, f"dnsmasq_{network.host_device}.log")

        if os.path.exists(config_path):
            os.remove(config_path)

        if os.path.exists(pid_path):
            with open(pid_path, "r") as f:
                try:
                    pid = int(f.read().strip())
                except ValueError:
                    continue
            try:
                os.kill(pid, 9)

            except ProcessLookupError:
                pass

            os.remove(pid_path)

        if os.path.exists(leases_path):
            os.remove(leases_path)

        if os.path.exists(log_path):
            os.remove(log_path)


def remove_challenge_from_wazuh(challenge):
    """
    Remove challenge from wazuh manager.
    """

    for machine in challenge.machines.values():
        try:
            delete_wazuh_agent(machine.id)
            pass
        except requests.RequestException:
            pass

def remove_database_entries(challenge, db_conn):
    """
    Remove the database entries for a challenge.
    """

    with db_conn.cursor() as cursor:
        for machine in challenge.machines.values():
            cursor.execute("DELETE FROM domains WHERE machine_id = %s", (machine.id,))
            cursor.execute("DELETE FROM network_connections WHERE machine_id = %s", (machine.id,))
            cursor.execute("DELETE FROM machines WHERE id = %s", (machine.id,))

        for network in challenge.networks.values():
            cursor.execute("DELETE FROM networks WHERE id = %s", (network.id,))

        cursor.execute("DELETE FROM challenges WHERE id = %s", (challenge.id,))

        cursor.execute("UPDATE challenge_subnets SET available = TRUE WHERE subnet = %s", (challenge.subnet,))
