import random
import threading
from tenacity import retry, stop_after_attempt, wait_exponential_jitter
import time
from dotenv import load_dotenv, find_dotenv
import os
import subprocess


from backend.DatabaseClasses import (
    ChallengeTemplate,
    Challenge,
    ChallengeSubnet,
    MachineTemplate,
    Machine,
    NetworkTemplate,
    Network,
    ConnectionTemplate,
    Connection,
    DomainTemplate,
    Domain,

)
from backend.proxmox_api_calls import (
    clone_vm_api_call,
    add_network_device_api_call,
    create_network_api_call,
    reload_network_api_call,
    attach_networks_to_vm_api_call,
    launch_vm_api_call,
    delete_network_api_call
)
from backend.subnet_calculations import nth_network_subnet, nth_machine_ip
from backend.teardown_challenge import remove_database_entries, stop_dnsmasq_instances,remove_challenge_from_wazuh
from backend.launch_timing_logger import launch_timing_logger
from backend.get_db_connection import db_connection_context
from backend.qemu_ga_wrapper import GuestAgent, GuestAgentError

load_dotenv(find_dotenv())

WAZUH_ENROLLMENT_PASSWORD = os.getenv("WAZUH_ENROLLMENT_PASSWORD")

DNSMASQ_INSTANCES_DIR = "/etc/dnsmasq-instances/"
os.makedirs(DNSMASQ_INSTANCES_DIR, exist_ok=True)


@retry(stop=stop_after_attempt(10), wait=wait_exponential_jitter(initial=1, max=5, exp_base=1.1, jitter=1),
       reraise=True)
def warmup_challenge(pre_assigned_user_id, challenge_template_id, vpn_monitoring_device, dmz_monitoring_device):
    """
    Launch a challenge by creating a user and network device.
    """

    with db_connection_context() as db_conn:

        print(f"[Info] Starting warmup challenge for user {pre_assigned_user_id} and template {challenge_template_id}", flush=True)

        start_time = time.time()

        try:
            start_time_db_fetch = time.time()
            print(f"[Info] Fetching database data for challenge template {challenge_template_id}", flush=True)
            challenge_template = ChallengeTemplate(challenge_template_id)
            fetch_machines(challenge_template, db_conn)
            fetch_network_and_connection_templates(challenge_template, db_conn)
            fetch_domain_templates(challenge_template, db_conn)

            launch_timing_logger(start_time_db_fetch, "[WARMUP DB FETCH COMPLETE]", challenge_template_id, pre_assigned_user_id)
        except Exception as e:
            print(f"[Error] Failed to fetch database data: {e}", flush=True)
            raise ValueError(f"Error fetching from database: {e}")

        try:
            print(f"[Info] Creating challenge for template {challenge_template_id}", flush=True)
            challenge = create_challenge(challenge_template, db_conn, pre_assigned_user_id)
            print(f"[Info] Successfully created challenge {challenge.id}", flush=True)
        except Exception as e:
            print(f"[Error] Failed to create challenge: {e}", flush=True)
            raise ValueError(f"Error creating challenge: {e}")

        try:
            start_time_machine_clone = time.time()
            print(f"[Info] Starting machine cloning for challenge {challenge.id}", flush=True)
            clone_machines(challenge_template, challenge, db_conn)
            launch_timing_logger(start_time_machine_clone, "[WARMUP MACHINE CLONE COMPLETE]", challenge_template_id, pre_assigned_user_id)

            # Network setup
            print(f"[Info] Starting network setup for challenge {challenge.id}", flush=True)
            start_time_network = time.time()
            print(f"[Info] Attaching vrtmon monitoring network to VMs", flush=True)
            attach_vrtmon_network(challenge)
            print(f"[Info] Creating networks and connections", flush=True)
            create_networks_and_connections(challenge_template, challenge, db_conn)
            print(f"[Info] Creating domains for challenge {challenge.id}", flush=True)
            create_domains(challenge_template, challenge, db_conn)
            print(f"[Info] Creating network devices", flush=True)
            create_network_devices(challenge)
            print(f"[Info] Waiting for networks to be up", flush=True)
            wait_for_networks_to_be_up(challenge)

            print(f"[Info] Attaching networks to VMs", flush=True)
            attach_networks_to_vms(challenge)
            print(f"[Info] Configuring dnsmasq instances", flush=True)
            configure_dnsmasq_instances(challenge)
            launch_timing_logger(start_time_network, "[WARMUP NETWORK SETUP COMPLETE]", challenge_template_id, pre_assigned_user_id)

            start_time_vm_boot = time.time()
            print(f"[Info] Launching VMs for challenge {challenge.id}", flush=True)
            launch_machines(challenge)
            launch_timing_logger(start_time_vm_boot, "[WARMUP VM BOOT COMPLETE]", challenge_template_id, pre_assigned_user_id)

            start_time_wazuh = time.time()
            print(f"[Info] Configuring Wazuh for challenge {challenge.id}", flush=True)
            configure_wazuh_for_challenge(challenge)
            launch_timing_logger(start_time_wazuh, "[WARMUP WAZUH CONFIG COMPLETE]", challenge_template_id, pre_assigned_user_id)

            print(f"[Info] Setting challenge {challenge.id} to READY state", flush=True)
            set_challenge_ready(challenge, db_conn)
            print(f"[Info] Challenge {challenge.id} is now READY", flush=True)

        except Exception as e:
            print(f"[Error] Failed during challenge launch: {e}", flush=True)
            undo_launch_challenge(challenge, db_conn)
            raise ValueError(f"Error launching challenge: {e}")

        elapsed_time = time.time() - start_time
        print(f"[Info] Warmup challenge {challenge.id} completed successfully in {elapsed_time:.2f}s", flush=True)
        launch_timing_logger(start_time, "[WARMUP COMPLETE]", challenge_template_id, pre_assigned_user_id)

        return challenge


def fetch_machines(challenge_template, db_conn):
    """
    Fetch machine templates for the given challenge.
    """
    print(f"[Info] Fetching machine templates for challenge template {challenge_template.id}", flush=True)

    with db_conn.cursor() as cursor:
        cursor.execute(
            "SELECT mt.id, df.guest_os "
            "FROM machine_templates mt "
            "JOIN disk_files df ON df.id = mt.disk_file_id "
            "WHERE mt.challenge_template_id = %s",
            (challenge_template.id,)
        )

        machines_fetched = cursor.fetchall()
        print(f"[Info] Retrieved {len(machines_fetched)} machine templates", flush=True)

        for row in machines_fetched:
            machine_id, guest_os = row[0], row[1]
            print(f"[Debug] Adding machine template {machine_id} (guest_os={guest_os}) to challenge", flush=True)
            machine_template = MachineTemplate(machine_template_id=machine_id, challenge_template=challenge_template)
            machine_template.set_guest_os(guest_os)

            # Add machine template to challenge template
            challenge_template.add_machine_template(machine_template)

        print(f"[Info] Successfully processed {len(machines_fetched)} machine templates", flush=True)


def fetch_network_and_connection_templates(challenge_template, db_conn):
    """
    Fetch network and connection templates for the given machine templates.
    """
    print(f"[Info] Fetching network and connection templates for challenge {challenge_template.id}", flush=True)

    total_connections = 0
    total_networks = 0

    for machine_template in challenge_template.machine_templates.values():
        with db_conn.cursor() as cursor:
            cursor.execute("""
            SELECT nt.id, nt.accessible, nt.is_dmz
            FROM network_templates nt, network_connection_templates ct
            WHERE ct.machine_template_id = %s
            AND ct.network_template_id = nt.id
            """, (machine_template.id,))

            connections = cursor.fetchall()
            print(f"[Debug] Retrieved {len(connections)} network connections for machine template {machine_template.id}", flush=True)

            for row in connections:
                network_id = row[0]
                total_connections += 1

                if challenge_template.network_templates.get(network_id) is None:
                    network_template = NetworkTemplate(network_template_id=network_id, accessible=row[1])
                    network_template.set_is_dmz(row[2])
                    challenge_template.add_network_template(network_template)
                    print(f"[Debug] Created network template {network_id} (accessible={row[1]}, is_dmz={row[2]})", flush=True)
                    total_networks += 1
                else:
                    network_template = challenge_template.network_templates[network_id]

                connection_template = ConnectionTemplate(
                    machine_template=machine_template,
                    network_template=network_template
                )

                challenge_template.add_connection_template(connection_template)
                network_template.add_connected_machine(machine_template)
                machine_template.add_connected_network(network_template)

    print(f"[Info] Successfully processed {total_networks} network templates and {total_connections} connection templates", flush=True)


def fetch_domain_templates(challenge_template, db_conn):
    """
    Fetch domain templates for the given machine templates and network templates.
    """
    print(f"[Info] Fetching domain templates for challenge {challenge_template.id}", flush=True)

    total_domains = 0

    for machine_template in challenge_template.machine_templates.values():
        with db_conn.cursor() as cursor:
            cursor.execute("""
            SELECT dt.domain_name
            FROM domain_templates dt
            WHERE dt.machine_template_id = %s
            """, (machine_template.id,))

            domains = cursor.fetchall()
            print(f"[Debug] Retrieved {len(domains)} domains for machine template {machine_template.id}", flush=True)

            for row in domains:
                domain_name = row[0]
                total_domains += 1
                print(f"[Debug] Adding domain {domain_name} to machine template {machine_template.id}", flush=True)
                domain_template = DomainTemplate(machine_template=machine_template, domain=domain_name)

                challenge_template.add_domain_template(domain_template)
                machine_template.add_domain_template(domain_template)

    print(f"[Info] Successfully processed {total_domains} domain templates", flush=True)


def create_challenge(challenge_template, db_conn, pre_assigned_user_id=None):
    """
    Create a challenge for the given user ID and challenge template.
    """
    print(f"[Info] Creating challenge in database for template {challenge_template.id} (user={pre_assigned_user_id})", flush=True)

    with db_conn.cursor() as cursor:
        cursor.execute("""
        INSERT INTO challenges (challenge_template_id, lifecycle_state, pre_assigned_user_id)
        VALUES (%s, 'PROVISIONING', %s)
        RETURNING id, subnet
        """, (challenge_template.id, pre_assigned_user_id))

        challenge_id, challenge_subnet_value = cursor.fetchone()
        challenge_subnet = ChallengeSubnet(challenge_subnet_value)
        challenge = Challenge(challenge_id=challenge_id, template=challenge_template, subnet=challenge_subnet.subnet)

        print(f"[Info] Created challenge {challenge_id} with subnet {challenge_subnet.subnet}", flush=True)

    return challenge


def clone_machines(challenge_template, challenge, db_conn):
    """
    Clone machines from the given machine template IDs.
    """
    print(f"[Info] Cloning machines for challenge {challenge.id}", flush=True)

    max_machine_id = 899_999_999
    machines_cloned = 0

    for machine_template in challenge_template.machine_templates.values():
        with db_conn.cursor() as cursor:
            cursor.execute("""
            INSERT INTO machines (machine_template_id, challenge_id)
            VALUES (%s, %s)
            RETURNING id
            """, (machine_template.id, challenge.id))

            machine_id = cursor.fetchone()[0]

            if machine_id > max_machine_id:
                print(f"[Error] Machine ID {machine_id} exceeds maximum limit {max_machine_id}", flush=True)
                raise ValueError("Machine ID exceeds maximum limit")

            print(f"[Info] Cloning VM template {machine_template.id} as machine {machine_id}", flush=True)
            machine = Machine(machine_id=machine_id, template=machine_template, challenge=challenge)

            # Add machine template to challenge template
            challenge.add_machine(machine)
            machine_template.set_child(machine)
            machines_cloned += 1

        clone_vm_api_call(machine_template, machine)

    print(f"[Info] Successfully cloned {machines_cloned} machines for challenge {challenge.id}", flush=True)


def attach_vrtmon_network(challenge):
    """
    Attach the vrtmon management network (net31) to all VMs.
    This network is used for monitoring and Wazuh communication.
    """
    print(f"[Info] Attaching vrtmon network (net31) to all VMs for challenge {challenge.id}", flush=True)

    for machine in challenge.machines.values():
        print(f"[Debug] Attaching vrtmon network to VM {machine.id}", flush=True)
        add_network_device_api_call(
            machine.id,
            nic="net31",
            bridge="vrtmon",
            model="e1000",
            mac_index="0A:01"
        )

    print(f"[Info] Successfully attached vrtmon network to {len(challenge.machines)} VMs", flush=True)


def vmid_to_ipv6(vmid, offset=0x1000):
    """
    Create ipv6 address from a VMID.
    """
    host_id = offset + vmid
    high = (host_id >> 16) & 0xFFFF
    low  = host_id & 0xFFFF
    return f"fd12:3456:789a:1::{high:x}:{low:x}"


def configure_wazuh_for_challenge(challenge, manager_ip="fd12:3456:789a:1::101"):
    """
    Configure Wazuh for all machines in parallel. Creates one thread per machine, starts all simultaneously, then joins.
    """

    threads = []
    exceptions = []

    def worker(machine):
        try:
            if machine.template.guest_os == 'windows':
                configure_ipv6_and_wazuh_windows(machine, manager_ip)
            else:
                configure_ipv6_and_wazuh_linux(machine, manager_ip)
        except Exception as e:
            print(f"[Error] Failed to configure Wazuh for VM {machine.id}: {e}", flush=True)
            exceptions.append(e)

    # Create one thread per machine
    for machine in challenge.machines.values():
        thread = threading.Thread(target=worker, args=(machine,))
        threads.append(thread)

    # Start all threads simultaneously
    for thread in threads:
        thread.start()

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    # If any thread failed, raise the first exception
    if exceptions:
        raise exceptions[0]


def wait_for_qemu_guest_agent(machine, timeout=120):
    """
    Wait until QEMU Guest Agent is ready.
    """
    start_time = time.time()
    deadline = time.monotonic() + timeout

    with GuestAgent(vmid=machine.id) as ga:
        while time.monotonic() < deadline:
            if ga.ping():
                launch_timing_logger(start_time, "[GUEST AGENT RESPONDED]", machine.challenge.template.id, None, VM_ID=machine.id)
                return True
            time.sleep(5)

    raise TimeoutError(f"QEMU Guest Agent timeout for VM {machine.id}")


def configure_ipv6_and_wazuh_linux(machine, manager_ip="fd12:3456:789a:1::101"):
    """
    Configure IPv6 and Wazuh agent via QEMU Guest Agent
    """
    ipv6 = vmid_to_ipv6(machine.id)
    vrtmon_gw = "fd12:3456:789a:1::1"
    agent_name = f"Agent_{machine.id}"

    full_start_time = time.time()

    aggregated_cmd = (
        f'iface=$(ip -o link | awk "/0a:01/ {{print \\$2; exit}}" | tr -d :) && '
        f'ip -6 addr add {ipv6}/64 dev $iface && '
        f'ip -6 route add default via {vrtmon_gw} && '
        f'systemctl stop wazuh-agent 2>/dev/null || true && '
        f'/var/monitoring/wazuh-agent/setup_wazuh.sh '
        f'    --register '
        f'    --manager={manager_ip} '
        f'    --name={agent_name} '
        f'    --password={WAZUH_ENROLLMENT_PASSWORD} '
        f'    --yes && '
        f'systemctl daemon-reload && '
        f'systemctl enable wazuh-agent && '
        f'systemctl start wazuh-agent'
    )

    try:
        with GuestAgent(vmid=machine.id) as ga:
            result = ga.exec(aggregated_cmd, timeout=120)
    except GuestAgentError as e:
        raise RuntimeError(f"Guest agent error configuring Wazuh for VM {machine.id}: {e}") from e

    if not result:
        raise RuntimeError(f"Wazuh config failed on VM {machine.id}: {result.stderr}")

    launch_timing_logger(
        full_start_time,
        "[WAZUH FULL CONFIG COMPLETE]",
        machine.challenge.template.id,
        None,
        VM_ID=machine.id,
    )


def configure_ipv6_and_wazuh_windows(machine, manager_ip="fd12:3456:789a:1::101"):
    """
    Configure IPv6 and register the Wazuh agent on a Windows VM via QEMU Guest Agent.
    """
    ipv6 = vmid_to_ipv6(machine.id)
    vrtmon_gw = "fd12:3456:789a:1::1"
    agent_name = f"Agent_{machine.id}"

    full_start_time = time.time()

    ipv6_cmd = (
        '$mac = "0A-01"; '
        '$nic = Get-NetAdapter | Where-Object { $_.MacAddress -like "$mac*" } | Select-Object -First 1; '
        f'if (-not (Get-NetIPAddress -InterfaceIndex $nic.ifIndex -AddressFamily IPv6 '
        f'-IPAddress "{ipv6}" -ErrorAction SilentlyContinue)) '
        f'{{ New-NetIPAddress -InterfaceIndex $nic.ifIndex -IPAddress "{ipv6}" -PrefixLength 64 -ErrorAction Stop }}; '
        f'if (-not (Get-NetRoute -InterfaceIndex $nic.ifIndex -DestinationPrefix "::/0" '
        f'-NextHop "{vrtmon_gw}" -ErrorAction SilentlyContinue)) '
        f'{{ New-NetRoute -InterfaceIndex $nic.ifIndex -DestinationPrefix "::/0" -NextHop "{vrtmon_gw}" -ErrorAction Stop }}'
    )

    try:
        with GuestAgent(vmid=machine.id, windows=True) as ga:

            result = ga.exec(
                ["powershell.exe", "-ExecutionPolicy", "Bypass", "-Command", ipv6_cmd],
                capture_output=True,
                timeout=120,
            )
            if result.exit_code != 0:
                raise RuntimeError(
                    f"IPv6 config failed on Windows VM {machine.id} "
                    f"(exit={result.exit_code}): {result.stderr.strip()!r}"
                )
            print(f"[Info] IPv6 configured on Windows VM {machine.id} ({ipv6})", flush=True)

            result = ga.exec(
                [
                    "powershell.exe", "-ExecutionPolicy", "Bypass",
                    "-File", r"C:\Windows\Temp\wazuh-agent\setup_wazuh.ps1",
                    "-Register",
                    "-Manager", manager_ip,
                    "-Name", agent_name,
                    "-Password", WAZUH_ENROLLMENT_PASSWORD,
                    "-Yes",
                ],
                capture_output=True,
                timeout=120,
            )
            if result.exit_code != 0:
                raise RuntimeError(
                    f"Wazuh register failed on Windows VM {machine.id} "
                    f"(exit={result.exit_code}): {result.stderr.strip()!r}"
                )
            print(f"[Info] Wazuh registered and started on Windows VM {machine.id} as {agent_name}", flush=True)

    except GuestAgentError as e:
        raise RuntimeError(f"Guest agent error while configuring Wazuh for Windows VM {machine.id}: {e}") from e

    launch_timing_logger(
        full_start_time,
        "[WAZUH FULL CONFIG COMPLETE]",
        machine.challenge.template.id,
        None,
        VM_ID=machine.id
    )


def generate_mac_address(machine_id, local_network_id, local_connection_id):
    """
    Generate a MAC address based on the machine ID, network ID, and connection ID.
    local_network_id, local_connection_id : 1-15 -> 2 nibbles combined
    machine_id : 100000000 -> 899999999 -> 8 nibbles -> hash to
    """
    machine_hex = hex(machine_id)[2:].zfill(8)[-8:]
    machine_bytes = [machine_hex[i:i + 2] for i in range(0, len(machine_hex), 2)]
    network_hex = hex(local_network_id)[2:]
    connection_hex = hex(local_connection_id)[2:]

    if len(machine_bytes) != 4:
        raise ValueError(f"Challenge ID must be 8 hex digits, got {len(machine_bytes) * 2} hex digits")

    if len(network_hex) > 1 or len(connection_hex) > 1:
        raise ValueError(f"Network ID and Connection ID must be 1 hex digit, got {len(network_hex)} and "
                         f"{len(connection_hex)} hex digits")

    mac = (f"02:{machine_bytes[0]}:{machine_bytes[1]}:{machine_bytes[2]}:{machine_bytes[3]}"
           f":{network_hex}{connection_hex}")
    return mac


def create_networks_and_connections(challenge_template, challenge, db_conn):
    """
    Create networks and connections for the given challenge.
    """
    print(f"[Info] Creating networks and connections for challenge {challenge.id}", flush=True)

    possible_network_subnets = []

    for i in range(2**4):
        possible_network_subnets.append(nth_network_subnet(challenge.subnet_ip, i))

    network_subnets = random.sample(possible_network_subnets, len(challenge_template.network_templates))
    print(f"[Info] Selected {len(network_subnets)} random network subnets from {len(possible_network_subnets)} possible subnets", flush=True)

    local_network_id = 0
    networks_created = 0
    connections_created = 0

    for network_template, network_subnet in zip(challenge_template.network_templates.values(), network_subnets):
        local_network_id += 1
        available_client_ips = {nth_machine_ip(network_subnet[:-3], i) for i in range(2, 15)}

        challenge_id_hex = f"{challenge.id:06x}"
        local_network_id_hex = f"{local_network_id:01x}"

        network_host_device = f"vrt{challenge_id_hex}{local_network_id_hex}"

        if len(network_host_device) != 10:
            print(f"[Error] Network host device must be 10 hex digits, got {len(network_host_device)} hex digits ({network_host_device})", flush=True)
            raise ValueError(f"Network host device must be 10 hex digits, got {len(network_host_device)} hex digits "
                             f"({network_host_device})")

        print(f"[Debug] Creating network with subnet {network_subnet} on device {network_host_device}", flush=True)

        with db_conn.cursor() as cursor:
            cursor.execute("""
            INSERT INTO networks (network_template_id, subnet, host_device, challenge_id)
            VALUES (%s, %s, %s, %s)
            RETURNING id""", (network_template.id, network_subnet, network_host_device, challenge.id))

            network_id = cursor.fetchone()[0]
            network = Network(
                network_id=network_id,
                template=network_template,
                subnet=network_subnet,
                host_device=network_host_device,
                accessible=network_template.accessible
            )
            network.set_is_dmz(network_template.is_dmz)
            challenge.add_network(network)
            networks_created += 1

        for local_connection_id, machine_template in enumerate(network_template.connected_machines.values()):
            machine = machine_template.child

            client_mac = generate_mac_address(machine.id, local_network_id, local_connection_id)
            client_ip = random.choice(list(available_client_ips))
            available_client_ips.remove(client_ip)

            if machine is None:
                print(f"[Error] Machine not found in machine template {machine_template.id}", flush=True)
                raise ValueError("Machine ID not found")

            print(f"[Debug] Creating connection: machine {machine.id} to network {network_id} with IP {client_ip} and MAC {client_mac}", flush=True)

            with db_conn.cursor() as cursor:
                cursor.execute("""
                INSERT INTO network_connections (machine_id, network_id, client_mac, client_ip)
                VALUES (%s, %s, %s, %s)
                """, (machine.id, network.id, client_mac, client_ip))

                connection = Connection(machine=machine, network=network, client_mac=client_mac, client_ip=client_ip)
                challenge.add_connection(connection)
                network.add_connection(connection)
                machine.add_connection(connection)
                connections_created += 1

    print(f"[Info] Successfully created {networks_created} networks and {connections_created} connections for challenge {challenge.id}", flush=True)


def create_domains(challenge_template, challenge, db_conn):
    """
    Create domains for the given challenge.
    """
    print(f"[Info] Creating domains for challenge {challenge.id}", flush=True)

    domains_created = 0

    for domain_template in challenge_template.domain_templates.values():
        machine = domain_template.machine_template.child
        domain_name = domain_template.domain

        print(f"[Debug] Creating domain {domain_name} for machine {machine.id}", flush=True)

        with db_conn.cursor() as cursor:
            cursor.execute("""
            INSERT INTO domains (machine_id, domain_name)
            VALUES (%s, %s)
            """, (machine.id, domain_name))

            domain = Domain(machine=machine, domain=domain_name)
            challenge.add_domain(domain)

            machine.add_domain(domain)
            domains_created += 1

    print(f"[Info] Successfully created {domains_created} domains for challenge {challenge.id}", flush=True)


def create_network_devices(challenge):
    """
    Configure network devices for the given challenge and user ID.
    """
    print(f"[Info] Creating network devices for challenge {challenge.id}", flush=True)

    devices_created = 0
    for network in challenge.networks.values():
        print(f"[Debug] Creating network device {network.host_device} with subnet {network.subnet}", flush=True)
        create_network_api_call(network)
        devices_created += 1

    print(f"[Info] Created {devices_created} network devices, reloading network configuration", flush=True)
    reload_network_api_call()
    print(f"[Info] Network configuration reloaded successfully", flush=True)


def wait_for_networks_to_be_up(challenge, try_timeout=3, max_tries=10):
    """
    Wait for networks to be up.
    """
    print(f"[Info] Waiting for network devices to be up for challenge {challenge.id} (timeout={try_timeout}s, max_tries={max_tries})", flush=True)

    host_devices = [network.host_device for network in challenge.networks.values()]
    print(f"[Debug] Waiting for {len(host_devices)} network devices: {', '.join(host_devices)}", flush=True)

    all_devices_up = False

    tries = 0
    last_log_time = 0
    log_interval = 2

    while not all_devices_up and tries < max_tries:
        tries += 1
        try_start = time.time()

        while time.time() - try_start < try_timeout and not all_devices_up:
            all_devices_up = True
            missing_devices = [d for d in host_devices if not os.path.exists(f"/sys/class/net/{d}")]

            if missing_devices:
                all_devices_up = False
                now = time.time()
                if now - last_log_time >= log_interval:
                    last_log_time = now
                    print(f"[Debug] Devices not yet available: {', '.join(missing_devices)}", flush=True)

            time.sleep(0.1)

        if not all_devices_up:
            if tries < max_tries:
                print(f"[Debug] Networks not ready on try {tries}/{max_tries}, reloading configuration", flush=True)
                reload_network_api_call()
            else:
                print(f"[Error] Networks did not come up after {max_tries} attempts", flush=True)

    if not all_devices_up:
        raise TimeoutError("Timed out waiting for networks to be up")

    print(f"[Info] All network devices are up on try {tries}", flush=True)


def configure_dnsmasq_instances(challenge):
    """
    Start a dnsmasq process per network that needs DNS/DHCP, isolated by interface.
    Each instance will only answer for its configured domains and will ignore unknown zones,
    causing the client to move to the next nameserver on timeout rather than receiving NXDOMAIN.
    """
    print(f"[Info] Configuring dnsmasq instances for challenge {challenge.id}", flush=True)

    machines_with_user_routes = {}
    machines_with_internet_access = {}

    # Collect upstream DNS servers per machine
    dns_servers_by_machine = {machine_id: [] for machine_id in challenge.machines.keys()}
    for machine in challenge.machines.values():
        for connection in machine.connections.values():
            dns_servers_by_machine[machine.id].append(connection.network.router_ip)

    configs_created = 0

    for network in challenge.networks.values():
        config_path = os.path.join(DNSMASQ_INSTANCES_DIR, f"dnsmasq_{network.host_device}.conf")

        print(f"[Info] Configuring dnsmasq for network {network.id} on device {network.host_device}", flush=True)
        print(f"[Debug] Config path: {config_path}", flush=True)

        with open(config_path, "w") as f:
            # Interface binding
            f.write(f"interface={network.host_device}\n")
            f.write("bind-interfaces\n")
            f.write("except-interface=lo\n")

            # DHCP range and router option
            f.write(f"dhcp-range={network.available_start_ip},{network.available_end_ip},24h\n")
            f.write(f"dhcp-option=option:router,{network.router_ip}\n")

            # Ensure dnsmasq only answers known domains and ignores unknown
            f.write("no-resolv\n")          # ignore /etc/resolv.conf
            f.write("no-poll\n")            # don't poll resolv.conf

            # For each connected machine, set DHCP and DNS behavior
            connections_configured = 0
            for connection in network.connections.values():
                tag = f"{connection.machine.id}"

                # DHCP host mapping and per-machine DNS
                f.write(f"dhcp-host={connection.client_mac},{connection.client_ip},set:{tag}\n")
                upstream = ",".join(dns_servers_by_machine[connection.machine.id])

                # Fallback to public DNS only if desired
                f.write(f"dhcp-option=tag:{tag},option:dns-server,{upstream},1.1.1.1,1.0.0.1\n")

                if network.is_dmz:
                    if connection.machine.id not in machines_with_internet_access:
                        machines_with_internet_access[connection.machine.id] = connection
                        f.write(f"dhcp-option=tag:{tag},option:classless-static-route,0.0.0.0/0,{network.router_ip}\n")

                # Add only authoritative server for each domain
                for domain in connection.machine.domains:
                    f.write(f"address=/{domain}/{connection.client_ip}\n")

                connections_configured += 1
                print(f"[Debug] Configured DHCP/DNS for machine {connection.machine.id} with IP {connection.client_ip}", flush=True)

            print(f"[Debug] Wrote dnsmasq config for {connections_configured} connections", flush=True)

        configs_created += 1

    print(f"[Info] Successfully created dnsmasq configurations for {configs_created} networks", flush=True)


def attach_networks_to_vms(challenge):
    """
    Attach networks to virtual machines.
    """
    print(f"[Info] Attaching networks to VMs for challenge {challenge.id}", flush=True)

    vms_updated = 0
    for machine in challenge.machines.values():
        print(f"[Debug] Attaching {len(machine.connections)} networks to VM {machine.id}", flush=True)
        attach_networks_to_vm_api_call(machine)
        vms_updated += 1

    print(f"[Info] Successfully attached networks to {vms_updated} VMs", flush=True)


def launch_machines(challenge):
    """
    Launch machines.
    """
    print(f"[Info] Launching {len(challenge.machines)} VMs for challenge {challenge.id}", flush=True)

    for machine in challenge.machines.values():
        print(f"[Info] Launching VM {machine.id}", flush=True)
        launch_vm_api_call(machine)

    print(f"[Info] All VMs launched, waiting for QEMU Guest Agent to respond on all VMs", flush=True)

    # Wait for all VMs to boot and qemu-ga to be ready
    for machine in challenge.machines.values():
        print(f"[Info] Waiting for QEMU Guest Agent on VM {machine.id}", flush=True)
        wait_for_qemu_guest_agent(machine)

    print(f"[Info] All VMs are ready with QEMU Guest Agent responding", flush=True)


def set_challenge_ready(challenge, db_conn):
    """
    Set the challenge lifecycle state to READY.
    """
    print(f"[Info] Setting challenge {challenge.id} lifecycle state to READY in database", flush=True)

    with db_conn.cursor() as cursor:
        cursor.execute("""
        UPDATE challenges
        SET lifecycle_state = 'READY'
        WHERE id = %s
        """, (challenge.id,))

    print(f"[Info] Challenge {challenge.id} lifecycle state set to READY", flush=True)


def undo_launch_challenge(challenge, db_conn):
    """
    Undo the launch of a challenge by stopping and deleting the machines and networks.
    """

    if challenge is None:
        print(f"[Warning] Cannot undo launch: challenge is None", flush=True)
        return

    print(f"[Error] Undoing launch for challenge {challenge.id}", flush=True)

    print(f"[Info] Stopping and deleting machines", flush=True)
    stop_and_delete_machines(challenge)

    print(f"[Info] Deleting network devices", flush=True)
    delete_network_devices(challenge)

    print(f"[Info] Stopping dnsmasq instances", flush=True)
    stop_dnsmasq_instances(challenge)

    print(f"[Info] Removing database entries", flush=True)
    remove_database_entries(challenge, db_conn)

    print(f"[Info] Removing challenge from Wazuh", flush=True)
    remove_challenge_from_wazuh(challenge)

    print(f"[Info] Challenge {challenge.id} cleanup completed", flush=True)


def stop_and_delete_machines(challenge):
    """
    Stop and delete the machines for a challenge.
    """
    print(f"[Info] Stopping and deleting {len(challenge.machines)} VMs for challenge {challenge.id}", flush=True)

    for machine in challenge.machines.values():
        try:
            print(f"[Debug] Stopping VM {machine.id}", flush=True)
            out = subprocess.run(["qm", "stop", str(machine.id), "--skiplock"], check=True, capture_output=True)
            print(f"[Info] VM {machine.id} stopped successfully", flush=True)
        except Exception as e:
            print(f"[Warning] Failed to stop VM {machine.id}: {e}", flush=True)
            try:
                print(out.stdout.decode(), flush=True)
                print(out.stderr.decode(), flush=True)
            except Exception:
                pass

        try:
            print(f"[Debug] Destroying VM {machine.id}", flush=True)
            out = subprocess.run(["qm", "destroy", str(machine.id), "--skiplock"], check=True, capture_output=True)
            print(f"[Info] VM {machine.id} destroyed successfully", flush=True)
        except Exception as e:
            print(f"[Warning] Failed to destroy VM {machine.id}: {e}", flush=True)
            try:
                print(out.stdout.decode(), flush=True)
                print(out.stderr.decode(), flush=True)
            except Exception:
                pass


def delete_network_devices(challenge):
    """
    Delete network devices for the given challenge.
    """
    print(f"[Info] Deleting {len(challenge.networks)} network devices for challenge {challenge.id}", flush=True)

    for network in challenge.networks.values():
        try:
            print(f"[Debug] Deleting network device {network.host_device}", flush=True)
            delete_network_api_call(network)
            print(f"[Info] Network device {network.host_device} deleted successfully", flush=True)
        except Exception as e:
            print(f"[Warning] Failed to delete network device {network.host_device}: {e}", flush=True)