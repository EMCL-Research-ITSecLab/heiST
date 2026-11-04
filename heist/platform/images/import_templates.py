import os
import subprocess
import time


from heist.infrastructure.proxmox.guest_agent import GuestAgent, GuestAgentError
from heist.platform.models import MachineTemplate, ChallengeTemplate
from heist.infrastructure.proxmox.client import (
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
PROXMOX_IMAGE_STORAGE = os.getenv("PROXMOX_LVM_STORAGE", "local-lvm")
_LINUX_AGENT_CONFIG_DIR  = "/root/heiST/heist/monitoring/wazuh/agent/linux"
_WINDOWS_AGENT_CONFIG_DIR = "/root/heiST/heist/monitoring/wazuh/agent/windows"

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
        # Preserve identifiers and native tasks for explicit reconciliation.
        # A failed response does not prove that create/import has stopped.
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

            from pathlib import Path
            if not isinstance(proxmox_filename, str) or Path(proxmox_filename).name != proxmox_filename or not proxmox_filename.endswith('.ova'):
                raise ValueError('Invalid managed image filename')
            disk_file_path = os.path.join(PROXMOX_STORAGE_BASE_DIR, proxmox_filename)
            if Path(disk_file_path).is_symlink():
                raise ValueError('Managed images must not be symlinks')

            # Check if the disk file path is valid
            if not os.path.exists(disk_file_path):
                print(f"[Error] Disk file path does not exist: {disk_file_path}", flush=True)
                raise ValueError(f"Disk file path {disk_file_path} does not exist.")
            if not os.path.isfile(disk_file_path):
                print(f"[Error] Disk file path is not a file: {disk_file_path}", flush=True)
                raise ValueError(f"Disk file path {disk_file_path} is not a file.")
            if not disk_file_path.endswith('.ova'):
                print(f"[Error] Disk file path is not a supported OVA: {disk_file_path}", flush=True)
                raise ValueError(f"Disk file path {disk_file_path} is not a supported OVA file.")

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


def import_disk_images_to_vm_templates(challenge_template):
    from heist.platform.images.provision import import_normalized
    for machine_template in challenge_template.machine_templates.values():
        import_normalized(machine_template.disk_file_path, machine_template.id, PROXMOX_IMAGE_STORAGE)


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
