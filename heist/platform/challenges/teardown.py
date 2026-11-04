import time
from dotenv import find_dotenv
from heist.environment import load_backend_env as load_dotenv
import subprocess
import os
from heist.infrastructure.network.firewall import remove_network_input_filter

from heist.platform.models import (
    ChallengeTemplate,
    ChallengeSubnet,
    Challenge,
    MachineTemplate,
    Machine,
    NetworkTemplate,
    Network,
    Connection
)
from heist.infrastructure.proxmox.client import (
    vm_exists_api_call, stop_vm_api_call, delete_vm_api_call,
    delete_network_api_call,
    reload_network_api_call,
    network_device_exists_api_call
)
from heist.infrastructure.database import db_connection_context
from heist.infrastructure.locking import operation_guard

load_dotenv(find_dotenv())

CHALLENGES_ROOT_SUBNET = os.getenv("CHALLENGES_ROOT_SUBNET", "10.128.0.0")
CHALLENGES_ROOT_SUBNET_MASK = os.getenv("CHALLENGES_ROOT_SUBNET_MASK", "255.128.0.0")
CHALLENGES_ROOT_SUBNET_MASK_INT = sum(bin(int(x)).count('1') for x in CHALLENGES_ROOT_SUBNET_MASK.split('.'))
CHALLENGES_ROOT_SUBNET_CIDR = f"{CHALLENGES_ROOT_SUBNET}/{CHALLENGES_ROOT_SUBNET_MASK_INT}"

MONITORING_HOST = os.getenv("MONITORING_HOST", "10.0.0.103")
WAZUH_PORT = os.getenv("WAZUH_API_PORT", "55000")
WAZUH_USER = os.getenv("WAZUH_API_USER", "wazuh-wui")
WAZUH_PASSWORD = os.getenv("WAZUH_API_PASSWORD")

DNSMASQ_INSTANCES_DIR = "/etc/dnsmasq-instances"

def teardown_challenge(challenge_id, *, expected_template_id=None):
    directory = os.getenv('HEIST_INSTANCE_LOCK_DIRECTORY', '/run/heist-instance-operations')
    with operation_guard(directory, challenge_id):
        return _teardown_challenge(challenge_id, expected_template_id=expected_template_id)


def _teardown_challenge(challenge_id, *, expected_template_id=None):
    """
    Stop a challenge for a user.
    """

    with db_connection_context() as db_conn:
        challenge = fetch_challenge(challenge_id, db_conn, expected_template_id=expected_template_id)
        if challenge is None:
            return
        fetch_machines(challenge, db_conn)
        stop_machines(challenge)
        delete_machines(challenge)
        fetch_networks(challenge, db_conn)
        stop_dnsmasq_instances(challenge)
        delete_iptables_rules(challenge)
        delete_network_devices(challenge)
        remove_challenge_from_wazuh(challenge)
        remove_database_entries(challenge, db_conn)



def fetch_challenge(challenge_id, db_conn, *, expected_template_id=None):
    """
    Fetch the challenge for a user.
    """

    with db_conn.cursor() as cursor:
        cursor.execute("""
            WITH challenge_info AS (
                SELECT id, challenge_template_id, subnet
                FROM challenges
                WHERE id = %s
                  AND lifecycle_state IN ('READY','EXPIRED','TERMINATING')
                  AND (lifecycle_state <> 'READY' OR pre_assigned_user_id IS NULL)
                  AND NOT EXISTS(SELECT 1 FROM users WHERE running_challenge = challenges.id)
                  AND (%s::bigint IS NULL OR challenge_template_id = %s)
                FOR UPDATE SKIP LOCKED 
            )
            UPDATE challenges
            SET lifecycle_state = 'TERMINATING'
            WHERE id IN (SELECT id FROM challenge_info)
            RETURNING id, challenge_template_id, subnet    
        """, (challenge_id, expected_template_id, expected_template_id))

        row = cursor.fetchone()
        if row is None:
            return None
        challenge_id, template_id, subnet = row

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
    with db_conn.cursor() as cursor:
        cursor.execute("""
            SELECT n.id, n.network_template_id, n.subnet, n.host_device, t.accessible, t.is_dmz
            FROM networks n JOIN network_templates t ON t.id = n.network_template_id
            WHERE n.challenge_id = %s
        """, (challenge.id,))
        for identifier, template_id, subnet, device, accessible, dmz in cursor.fetchall():
            template = NetworkTemplate(template_id, accessible)
            network = Network(identifier, template, subnet, device, accessible)
            network.set_is_dmz(dmz)
            challenge.add_network(network)


def delete_wazuh_agent(machine_id):
    from heist.infrastructure.monitoring.wazuh import Wazuh
    client = Wazuh(MONITORING_HOST, WAZUH_PORT, WAZUH_USER, WAZUH_PASSWORD,
                   certificate=os.getenv('WAZUH_CA_CERTIFICATE_FILE') or True, pinned_certificate=os.getenv('WAZUH_PINNED_CERTIFICATE_FILE'))
    try:
        return client.remove_agent(machine_id)
    finally:
        client.close()


def stop_machines(challenge):
    for machine in challenge.machines.values():
        if vm_exists_api_call(machine):
            stop_vm_api_call(machine)


def delete_machines(challenge):
    for machine in challenge.machines.values():
        delete_vm_api_call(machine)


def delete_network_devices(challenge):
    """
    Delete the networks for a challenge.
    """

    for network in challenge.networks.values():
        if network_device_exists_api_call(network):
            delete_network_api_call(network)
        remove_network_input_filter(network.host_device)
    reload_network_api_call()
    wait_for_network_devices_deletion(challenge)


def wait_for_network_devices_deletion(challenge, try_timeout=3, max_tries=10):
    """
    Wait for the networks for a challenge to be deleted.
    """

    deadline = time.monotonic()+try_timeout*max_tries
    while any(os.path.exists('/sys/class/net/'+network.host_device) for network in challenge.networks.values()):
        if time.monotonic() >= deadline:
            raise TimeoutError('Challenge bridge deletion was not confirmed')
        time.sleep(.1)


def remove_iptables_rule(table, chain, arguments):
    base = ['iptables', '-w', '10', '-t', table]
    result = subprocess.run([*base, '-C', chain, *arguments], capture_output=True, timeout=15)
    if result.returncode == 1:
        return
    if result.returncode != 0:
        raise RuntimeError('Challenge firewall rule presence was not confirmed')
    subprocess.run([*base, '-D', chain, *arguments], check=True, capture_output=True, timeout=15)


def delete_iptables_rules(challenge):
    from heist.infrastructure.network.firewall import chain_name
    for network in challenge.networks.values():
        chain_name(network.host_device)
        remove_iptables_rule('filter', 'FORWARD', ['-i', network.host_device, '-o', network.host_device, '-j', 'ACCEPT'])
        for protocol in ('udp', 'tcp'):
            remove_iptables_rule('filter', 'INPUT', ['-i', network.host_device, '-d', network.router_ip, '-p', protocol, '--dport', '53', '-j', 'ACCEPT'])
        remove_iptables_rule('filter', 'INPUT', ['-d', network.router_ip, '-j', 'DROP'])
        if network.is_dmz:
            remove_iptables_rule('nat', 'POSTROUTING', ['-o', 'vmbr0', '-s', network.subnet, '!', '-d', CHALLENGES_ROOT_SUBNET_CIDR, '-j', 'MASQUERADE'])
            remove_iptables_rule('filter', 'FORWARD', ['-i', network.host_device, '-o', 'vmbr0', '-s', network.subnet, '!', '-d', CHALLENGES_ROOT_SUBNET_CIDR, '-m', 'conntrack', '--ctstate', 'NEW,ESTABLISHED,RELATED', '-j', 'ACCEPT'])
            remove_iptables_rule('filter', 'FORWARD', ['-i', 'vmbr0', '-o', network.host_device, '-d', network.subnet, '!', '-s', CHALLENGES_ROOT_SUBNET_CIDR, '-m', 'conntrack', '--ctstate', 'ESTABLISHED,RELATED', '-j', 'ACCEPT'])


def stop_dnsmasq_instances(challenge):
    from pathlib import Path
    from heist.infrastructure.network.dnsmasq_process import stop
    from heist.infrastructure.network.firewall import chain_name
    for network in challenge.networks.values():
        chain_name(network.host_device)  # Only generated owned bridge names.
        prefix = Path(DNSMASQ_INSTANCES_DIR)/('dnsmasq_'+network.host_device)
        stop(str(prefix)+'.pid')
        for extension in ('.pid', '.conf', '.leases', '.log'):
            Path(str(prefix)+extension).unlink(missing_ok=True)


def remove_challenge_from_wazuh(challenge):
    for machine in challenge.machines.values():
        if delete_wazuh_agent(machine.id) is not True:
            raise RuntimeError('Monitoring agent cleanup was not confirmed')


def remove_database_entries(challenge, db_conn):
    """
    Remove the database entries for a challenge.
    """

    with db_conn:
        with db_conn.cursor() as cursor:
            for machine in challenge.machines.values():
                cursor.execute("DELETE FROM domains WHERE machine_id = %s", (machine.id,))
                cursor.execute("DELETE FROM network_connections WHERE machine_id = %s", (machine.id,))
                cursor.execute("DELETE FROM machines WHERE id = %s", (machine.id,))

            for network in challenge.networks.values():
                cursor.execute("DELETE FROM networks WHERE id = %s", (network.id,))

            cursor.execute("DELETE FROM challenges WHERE id = %s", (challenge.id,))

            cursor.execute("UPDATE challenge_subnets SET available = TRUE WHERE subnet = %s", (challenge.subnet,))
