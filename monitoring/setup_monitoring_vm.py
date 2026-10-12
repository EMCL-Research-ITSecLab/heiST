#!/usr/bin/env python3
"""
Monitoring Stack Setup Script
Automates Proxmox VM creation and monitoring stack deployment
"""

import os
import time
import datetime
import sys
import argparse
from proxmoxer import ProxmoxAPI
from dotenv import load_dotenv

sys.stdout.reconfigure(line_buffering=True)

# Load environment variables
load_dotenv()
IPTABLES_FILE = os.getenv("IPTABLES_FILE", "/etc/iptables-backend/iptables.sh")

from monitoring.utils.script_helper import (
    log_info, log_debug, log_error, log_warning, log_success, log_section,
    execute_remote_command, execute_remote_command_with_key, scp_file,
    run_cmd, run_cmd_with_realtime_output, remote_setup_user_ssh_keys,
    Timer, time_function, DEBUG_MODE
)

# Configuration constants from environment variables
MONITORING_VM_ID = os.getenv("MONITORING_VM_ID", "9000")
MONITORING_VM_NAME = os.getenv("MONITORING_VM_NAME", "monitoring-vm")
MONITORING_VM_MAC_ADDRESS = os.getenv("MONITORING_VM_MAC_ADDRESS", "00:16:3e:00:00:03")
UBUNTU_BASE_SERVER_URL = os.getenv("UBUNTU_BASE_SERVER_URL")
BACKEND_NETWORK_DEVICE = os.getenv("BACKEND_NETWORK_DEVICE", "vrt_backend")
VM_MEMORY = os.getenv("MONITORING_VM_MEMORY", "10240")
VM_CORES = os.getenv("MONITORING_VM_CORES", "2")
STORAGE = os.getenv("PROXMOX_LVM_STORAGE", "local-lvm")
DISK_SIZE = os.getenv("MONITORING_VM_DISK", "32G")
VM_IP = os.getenv("MONITORING_HOST", "10.0.0.103")
GATEWAY = os.getenv("BACKEND_NETWORK_ROUTER", "10.0.0.1")
SSH_USER = os.getenv("MONITORING_VM_USER", "ubuntu")
DEFAULT_SSH_PASSWORD = "admin"
NEW_SSH_PASSWORD = os.getenv("MONITORING_VM_PASSWORD", "meow1234")
DNSMASQ_BACKEND_DIR = os.getenv("DNSMASQ_BACKEND_DIR", "/etc/dnsmasq-backend")
DNSMASQ_BACKEND_CONFIG = os.path.join(DNSMASQ_BACKEND_DIR, "dnsmasq.conf")
PROXMOX_IP = os.getenv("PROXMOX_HOST", "10.0.0.1")
FRONTEND_IP = os.getenv("WEBSERVER_HOST", "10.0.0.101")
DATABASE_IP = os.getenv("DATABASE_HOST", "10.0.0.102")
DATABASE_PORT = os.getenv("DATABASE_PORT", "5432")
POSTGRES_EXPORTER_PASSWORD = os.getenv("POSTGRES_EXPORTER_PASSWORD", "meow1234")
DATABASE_VM_EXPORTER_PORT = os.getenv("DATABASE_VM_EXPORTER_PORT", "9100")
WEBSERVER_VM_EXPORTER_PORT = os.getenv("WEBSERVER_VM_EXPORTER_PORT", "9100")
MONITORING_VM_EXPORTER_PORT = os.getenv("MONITORING_VM_EXPORTER_PORT", "9100")
WEBSERVER_APACHE_EXPORTER_PORT = os.getenv("WEBSERVER_APACHE_EXPORTER_PORT", "9117")
GRAFANA_PORT = os.getenv("GRAFANA_PORT", "3000")
PROMETHEUS_PORT = os.getenv("PROMETHEUS_PORT", "9090")
PROXMOX_INTERNAL_IP = os.getenv("PROXMOX_INTERNAL_IP", "10.0.2.3")
PROXMOX_SSH_KEYFILE = os.getenv("PROXMOX_SSH_KEYFILE", "/root/.ssh/id_rsa.pub")
PROXMOX_EXPORTER_TOKEN_NAME = os.getenv("PROXMOX_EXPORTER_TOKEN_NAME", "pve_exporter_token")
PVE_EXPORTER_DIR = os.getenv("PVE_EXPORTER_DIR", "/etc/pve-exporter")
PVE_EXPORTER_ENV = f"{PVE_EXPORTER_DIR}/.env"
PROXMOX_PORT = os.getenv("PROXMOX_PORT", "8006")
PROXMOX_NODE_EXPORTER_PORT = os.getenv("PROXMOX_NODE_EXPORTER_PORT", "9101")

# Proxmox API connection settings
PROXMOX_HOST = os.getenv("PROXMOX_HOST", "localhost")
PROXMOX_USER = os.getenv("PROXMOX_USER", "root@pam")
PROXMOX_PASSWORD = os.getenv("PROXMOX_PASSWORD")
PROXMOX_HOSTNAME = os.getenv("PROXMOX_HOSTNAME", "pve")
PROXMOX_EXPORTER_PORT = os.getenv("PROXMOX_EXPORTER_PORT", "9221")
POSTGRES_EXPORTER_PORT = os.getenv("POSTGRES_EXPORTER_PORT", "9187")

VM_NETMASK = "24"
UBUNTU_BASE_DIR = "/root/heiST/setup/ubuntu-base-server"
UBUNTU_BASE_OVA = "/root/heiST/setup/ubuntu-base-server/ubuntu-base-server.ova"
UBUNTU_BASE_OVF = "/root/heiST/setup/ubuntu-base-server/ubuntu-base-server Clone.ovf"

# Initialize Proxmox API connection
try:
    proxmox = ProxmoxAPI(
        PROXMOX_HOST,
        user=PROXMOX_USER,
        password=PROXMOX_PASSWORD,
        verify_ssl=False
    )
except Exception as e:
    log_error(f"Failed to initialize Proxmox API: {e}")
    sys.exit(1)


@time_function
def wait_for_ssh(ip, timeout=600):
    """Wait for SSH service to become available on target VM"""
    log_info(f"Waiting for SSH on {ip}")
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            execute_remote_command(ip, "echo SSH check", SSH_USER, DEFAULT_SSH_PASSWORD, timeout=10)
            log_success("SSH is available")
            return True
        except Exception:
            time.sleep(10)
    raise Exception("Timed out waiting for SSH to become available")


def test_ssh_key_access(ip):
    """Verify SSH key authentication works before proceeding"""
    log_debug(f"Testing SSH key access to {ip}")
    execute_remote_command_with_key(ip, "echo SSH key test successful", SSH_USER, PROXMOX_SSH_KEYFILE)


@time_function
def add_monitoring_to_dnsmasq():
    """Add monitoring VM to dnsmasq configuration for DHCP assignment"""
    log_section("Adding Monitoring VM to DNSMasq")

    try:
        # Verify dnsmasq-backend service exists
        result = run_cmd(["systemctl", "status", "dnsmasq-backend"], check=False)

        # Create configuration backup
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = f"{DNSMASQ_BACKEND_CONFIG}.bak.{timestamp}"
        run_cmd(["cp", DNSMASQ_BACKEND_CONFIG, backup_path], check=True)

        with open(DNSMASQ_BACKEND_CONFIG, 'r') as f:
            current_config = f.readlines()

        # Check for existing MAC address configuration
        mac_configured = any(MONITORING_VM_MAC_ADDRESS in line for line in current_config)

        # Check if IP address is already assigned to another host
        ip_in_use = any(f",{VM_IP}" in line or f",{VM_IP}\n" in line
                        for line in current_config
                        if line.startswith("dhcp-host") and MONITORING_VM_MAC_ADDRESS not in line)

        if mac_configured:
            log_info("Monitoring host already in dnsmasq config")
            return True

        if ip_in_use:
            raise Exception(f"IP address {VM_IP} is already in use by another host in dnsmasq config")

        # Add new configuration entries
        new_lines = [
            f"\n# Added by monitoring setup on {timestamp}\n",
            f"dhcp-host={MONITORING_VM_MAC_ADDRESS},{MONITORING_VM_NAME},{VM_IP}\n"
        ]

        # Test configuration syntax before applying
        test_config = current_config + new_lines
        with open(f"{DNSMASQ_BACKEND_CONFIG}.test", 'w') as f:
            f.writelines(test_config)

        run_cmd(
            ["dnsmasq", "--test", f"--conf-file={DNSMASQ_BACKEND_CONFIG}.test"],
            check=True
        )
        os.remove(f"{DNSMASQ_BACKEND_CONFIG}.test")

        # Apply new configuration
        with open(DNSMASQ_BACKEND_CONFIG, 'a') as f:
            f.writelines(new_lines)

        # Validate final configuration
        run_cmd(["dnsmasq", "--test", f"--conf-file={DNSMASQ_BACKEND_CONFIG}"], check=True)

        # Restart service with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                run_cmd(["systemctl", "restart", "dnsmasq-backend"], check=True)
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                log_warning(f"Restart attempt {attempt + 1} failed, retrying...")
                time.sleep(2)

        log_success("Successfully added monitoring VM to dnsmasq")
        return True

    except Exception as e:
        log_error(f"Failed to update dnsmasq: {str(e)}")
        # Restore backup on failure
        if 'backup_path' in locals() and os.path.exists(backup_path):
            log_info("Restoring original config")
            try:
                run_cmd(["mv", backup_path, DNSMASQ_BACKEND_CONFIG], check=True)
                run_cmd(["systemctl", "restart", "dnsmasq-backend"], check=True)
            except Exception as restore_error:
                log_error(f"Failed to restore config: {str(restore_error)}")
        return False


@time_function
def download_ubuntu_base_server_ova():
    """Download Ubuntu base server OVA template if not present"""
    log_section("Downloading Ubuntu Base Server OVA")
    os.makedirs(UBUNTU_BASE_DIR, exist_ok=True)

    if not os.path.exists(UBUNTU_BASE_OVA):
        log_info("Downloading Ubuntu Base Server OVA")
        import requests
        response = requests.get(UBUNTU_BASE_SERVER_URL, stream=True)
        if response.status_code == 200:
            with open(UBUNTU_BASE_OVA, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
            log_success("OVA download completed")
        else:
            raise Exception(f"Failed to download OVA: {response.status_code}")
    else:
        log_info("OVA already exists")


@time_function
def extract_ova():
    """Extract OVA file to access OVF template"""
    log_section("Extracting OVA File")
    if not os.path.exists(UBUNTU_BASE_OVF):
        exit_code = run_cmd_with_realtime_output([
            "tar", "-xf", UBUNTU_BASE_OVA,
            "-C", UBUNTU_BASE_DIR
        ], check=True)
        log_success("OVA extraction completed")
    else:
        log_info("OVF already exists")


@time_function
def import_monitoring_vm():
    """Import and configure monitoring VM from OVA template"""
    log_section("Importing Monitoring VM")

    # Download and extract OVA if needed
    download_ubuntu_base_server_ova()
    extract_ova()

    # Import OVF template into Proxmox - use real-time output for visibility
    log_info("Importing OVF template (this may take a while)...")
    exit_code = run_cmd_with_realtime_output([
        "qm", "importovf",
        str(MONITORING_VM_ID),
        UBUNTU_BASE_OVF,
        STORAGE
    ], check=True)

    # Configure VM settings
    proxmox.nodes(PROXMOX_HOSTNAME).qemu(MONITORING_VM_ID).config.put(
        name=MONITORING_VM_NAME,
        memory=VM_MEMORY,
        cores=VM_CORES,
        cpu="x86-64-v2",
        net0=f"virtio,bridge={BACKEND_NETWORK_DEVICE},macaddr={MONITORING_VM_MAC_ADDRESS}",
        ipconfig0=f"ip={VM_IP}/{VM_NETMASK},gw={GATEWAY}"
    )

    # Configure DHCP reservation
    add_monitoring_to_dnsmasq()

    # Start VM and wait for boot completion
    proxmox.nodes(PROXMOX_HOSTNAME).qemu(MONITORING_VM_ID).status.start.post()
    log_info("VM started, waiting for boot...")
    wait_for_ssh(VM_IP)

    log_success("Monitoring VM imported and started")


@time_function
def install_packages():
    """Install base system packages on monitoring VM"""
    log_section("Installing Base Packages")
    commands = [
        "sudo systemctl stop unattended-upgrades",
        "sudo systemctl mask unattended-upgrades",
        "sudo apt install -y ntpsec-ntpdate",
        "sudo ntpdate time.google.com",
        "sudo apt update",
        #"sudo DEBIAN_FRONTEND=noninteractive apt upgrade -y",
        "sudo apt install -y wget curl gnupg2 software-properties-common apt-transport-https ufw"
    ]

    for cmd in commands:
        execute_remote_command_with_key(VM_IP, cmd, SSH_USER, ssh_key_path=PROXMOX_SSH_KEYFILE, timeout=1800)

    log_success("Base packages installed")


@time_function
def setup_grafana():
    """Install and configure Grafana monitoring dashboard"""
    log_section("Setting up Grafana")
    commands = [
        "sudo mkdir -p /etc/apt/keyrings",
        "wget -q -O - https://packages.grafana.com/gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/grafana.gpg",
        "echo 'deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://packages.grafana.com/oss/deb stable main' | sudo tee /etc/apt/sources.list.d/grafana.list",
        "sudo apt update",
        "sudo apt install -y grafana",
        "sudo systemctl daemon-reload",
        "sudo systemctl enable grafana-server",
        "sudo systemctl start grafana-server"
    ]

    for cmd in commands:
        execute_remote_command_with_key(VM_IP, cmd, SSH_USER, ssh_key_path=PROXMOX_SSH_KEYFILE, shell=True)

    log_success("Grafana setup completed")


@time_function
def setup_prometheus():
    """Install and configure Prometheus metrics collection"""
    log_section("Setting up Prometheus")

    commands = [
        "wget -q https://github.com/prometheus/prometheus/releases/download/v2.47.0/prometheus-2.47.0.linux-amd64.tar.gz",
        "tar xfz prometheus-2.47.0.linux-amd64.tar.gz",
        "sudo mv prometheus-2.47.0.linux-amd64 /opt/prometheus",
        "rm prometheus-2.47.0.linux-amd64.tar.gz",
        "id -u prometheus &>/dev/null || sudo useradd --no-create-home --shell /bin/false prometheus",
        "sudo mkdir -p /etc/prometheus /var/lib/prometheus",
        "sudo cp -f /opt/prometheus/prometheus /usr/local/bin/",
        "sudo cp -f /opt/prometheus/promtool /usr/local/bin/",
        "sudo cp -r /opt/prometheus/consoles /etc/prometheus/",
        "sudo cp -r /opt/prometheus/console_libraries /etc/prometheus/",
        "if [ ! -f /etc/prometheus/prometheus.yml ]; then sudo cp -f /opt/prometheus/prometheus.yml /etc/prometheus/; fi",
        "sudo chown -R prometheus:prometheus /etc/prometheus /var/lib/prometheus",
        "sudo chown prometheus:prometheus /usr/local/bin/prometheus /usr/local/bin/promtool"
    ]

    for cmd in commands:
        execute_remote_command_with_key(VM_IP, cmd, SSH_USER, ssh_key_path=PROXMOX_SSH_KEYFILE, shell=True)

    # Create systemd service for Prometheus
    service_content = """[Unit]
Description=Prometheus
Wants=network-online.target
After=network-online.target

[Service]
User=prometheus
Group=prometheus
Type=simple
ExecStart=/usr/local/bin/prometheus \\
    --config.file /etc/prometheus/prometheus.yml \\
    --storage.tsdb.path /var/lib/prometheus/ \\
    --web.console.templates=/etc/prometheus/consoles \\
    --web.console.libraries=/etc/prometheus/console_libraries

[Install]
WantedBy=multi-user.target
"""

    with open("prometheus.service", "w") as f:
        f.write(service_content)

    scp_file("prometheus.service", "/tmp/prometheus.service", VM_IP, SSH_USER, NEW_SSH_PASSWORD)
    os.remove("prometheus.service")

    commands = [
        "sudo mv /tmp/prometheus.service /etc/systemd/system/prometheus.service",
        "sudo systemctl daemon-reload",
        "sudo systemctl enable prometheus",
        "sudo systemctl start prometheus"
    ]

    for cmd in commands:
        execute_remote_command_with_key(VM_IP, cmd, SSH_USER, ssh_key_path=PROXMOX_SSH_KEYFILE)

    log_success("Prometheus setup completed")


@time_function
def configure_prometheus_yml():
    """Configure Prometheus scraping targets and intervals"""
    log_section("Configuring Prometheus")

    prometheus_yml_content = f"""global:
  scrape_interval: 15s
  evaluation_interval: 15s

alerting:
  alertmanagers:
    - static_configs:
        - targets:

scrape_configs:
  - job_name: 'monitoring-vm'
    static_configs:
      - targets: ['localhost:{MONITORING_VM_EXPORTER_PORT}']
        labels:
          instance: 'monitoring-vm'
          node_type: 'monitoring'

  - job_name: 'proxmox-node'
    static_configs:
      - targets: ['{PROXMOX_IP}:{PROXMOX_NODE_EXPORTER_PORT}']
        labels:
          instance: 'proxmox-host'
          node_type: 'hypervisor'

  - job_name: 'proxmox-pve'
    metrics_path: '/pve'
    static_configs:
      - targets: ['{PROXMOX_IP}:{PROXMOX_EXPORTER_PORT}']
        labels:
          instance: 'proxmox-api'

  - job_name: 'apache'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['{FRONTEND_IP}:{WEBSERVER_APACHE_EXPORTER_PORT}']

  - job_name: 'webserver-node'
    static_configs:
      - targets: ['{FRONTEND_IP}:{WEBSERVER_VM_EXPORTER_PORT}']
        labels:
          instance: 'webserver'
          node_type: 'application'

  - job_name: 'database-node'
    static_configs:
      - targets: ['{DATABASE_IP}:{DATABASE_VM_EXPORTER_PORT}']
        labels:
          instance: 'database-server'
          node_type: 'database'

  - job_name: 'postgres'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['{DATABASE_IP}:{POSTGRES_EXPORTER_PORT}']
        labels:
          instance: 'database-server'
"""

    with open("prometheus.yml", "w") as f:
        f.write(prometheus_yml_content)

    scp_file("prometheus.yml", "/tmp/prometheus.yml", VM_IP, SSH_USER, NEW_SSH_PASSWORD)
    os.remove("prometheus.yml")

    commands = [
        "sudo mv /tmp/prometheus.yml /etc/prometheus/prometheus.yml",
        "sudo chown prometheus:prometheus /etc/prometheus/prometheus.yml",
        "sudo promtool check config /etc/prometheus/prometheus.yml",
        "sudo systemctl restart prometheus"
    ]

    for cmd in commands:
        execute_remote_command_with_key(VM_IP, cmd, SSH_USER, ssh_key_path=PROXMOX_SSH_KEYFILE)

    log_success("Prometheus configuration with systemd targets completed")


@time_function
def setup_node_exporter():
    """Install Node Exporter for system metrics collection"""
    log_section("Setting up Node Exporter")

    commands = [
        "wget https://github.com/prometheus/node_exporter/releases/download/v1.9.1/node_exporter-1.9.1.linux-amd64.tar.gz",
        "tar -xzf node_exporter-1.9.1.linux-amd64.tar.gz",
        "sudo cp node_exporter-1.9.1.linux-amd64/node_exporter /usr/local/bin/",
        "sudo useradd --no-create-home --shell /usr/sbin/nologin prometheus 2>/dev/null || true",
        "rm -rf node_exporter-1.9.1.linux-amd64*"
    ]

    for cmd in commands:
        execute_remote_command_with_key(VM_IP, cmd, SSH_USER, ssh_key_path=PROXMOX_SSH_KEYFILE, shell=True)

    systemd_units = [
        "docker.service",
        "clickhouse-server.service",
        "banner-server.service"
    ]
    unit_filter = "|".join(systemd_units)

    node_exporter_service = f"""[Unit]
Description=Node Exporter
Wants=network-online.target
After=network-online.target

[Service]
User=prometheus
Group=prometheus
Type=simple
ExecStart=/usr/local/bin/node_exporter \\
    --collector.systemd \\
    --collector.systemd.unit-include='{unit_filter}'

[Install]
WantedBy=default.target
"""

    with open("node_exporter.service", "w") as f:
        f.write(node_exporter_service)

    scp_file("node_exporter.service", "/tmp/node_exporter.service", VM_IP, SSH_USER, NEW_SSH_PASSWORD)
    os.remove("node_exporter.service")

    commands = [
        "sudo mv /tmp/node_exporter.service /etc/systemd/system/node_exporter.service",
        "sudo systemctl daemon-reload",
        "sudo systemctl enable --now node_exporter"
    ]

    for cmd in commands:
        execute_remote_command_with_key(VM_IP, cmd, SSH_USER, ssh_key_path=PROXMOX_SSH_KEYFILE)

    time.sleep(2)
    try:
        execute_remote_command_with_key(
            VM_IP,
            "curl -s http://localhost:9100/metrics | grep systemd_unit_state | head -5",
            SSH_USER,
            ssh_key_path=PROXMOX_SSH_KEYFILE
        )
        log_success("Node Exporter with systemd collector setup completed")
    except Exception as e:
        log_warning(f"Could not verify systemd metrics, but service is running: {e}")

    log_success("Node Exporter setup completed")


@time_function
def setup_node_exporter_on_proxmox():
    """Install Node Exporter with systemd collector on Proxmox host"""
    log_section("Setting up Node Exporter with systemd collector on Proxmox Host")

    commands = [
        "wget -q https://github.com/prometheus/node_exporter/releases/download/v1.9.1/node_exporter-1.9.1.linux-amd64.tar.gz",
        "tar -xzf node_exporter-1.9.1.linux-amd64.tar.gz",
        "cp node_exporter-1.9.1.linux-amd64/node_exporter /usr/local/bin/",
        "chmod +x /usr/local/bin/node_exporter",
        "useradd --no-create-home --shell /usr/sbin/nologin prometheus 2>/dev/null || true",
        "rm -rf node_exporter-1.9.1.linux-amd64*"
    ]

    for cmd in commands:
        run_cmd(cmd, check=True, shell=True)

    proxmox_units = [
        "suricata-vpn.service",
        "suricata-dmz.service",
        "suricata-backend.service",
        "zeek.service",
        "vector-vpn.service",
        "vector-dmz.service",
        "vector-backend.service",
        "vector-zeek.service"
    ]
    unit_filter = "|".join(proxmox_units)

    service_content = f"""[Unit]
Description=Node Exporter
Wants=network-online.target
After=network-online.target

[Service]
User=prometheus
Group=prometheus
Type=simple
ExecStart=/usr/local/bin/node_exporter \\
    --web.listen-address={PROXMOX_IP}:{PROXMOX_NODE_EXPORTER_PORT} \\
    --collector.systemd \\
    --collector.systemd.unit-include='{unit_filter}'

[Install]
WantedBy=default.target
"""

    with open("/etc/systemd/system/node_exporter.service", "w") as f:
        f.write(service_content)

    commands = [
        "systemctl daemon-reload",
        "systemctl enable node_exporter",
        "systemctl start node_exporter"
    ]

    for cmd in commands:
        run_cmd(cmd.split(), check=True)

    time.sleep(2)
    try:
        result = run_cmd(
            f"curl -s http://{PROXMOX_IP}:{PROXMOX_NODE_EXPORTER_PORT}/metrics | grep 'node_exporter_build_info'",
            check=True,
            shell=True,
            capture_output=True
        )
        log_info(f"Node Exporter on Proxmox running on port {PROXMOX_NODE_EXPORTER_PORT}")

        result = run_cmd(
            f"curl -s http://{PROXMOX_IP}:{PROXMOX_NODE_EXPORTER_PORT}/metrics | grep systemd_unit_state | head -5",
            check=False,
            shell=True,
            capture_output=True
        )
        if result.stdout:
            log_success("Systemd metrics confirmed")

    except Exception as e:
        log_error("Node Exporter verification failed")
        raise

    log_success("Node Exporter on Proxmox host setup completed")


@time_function
def configure_firewall():
    """Configure UFW firewall rules for monitoring services"""
    log_section("Configuring Firewall")
    commands = [
        f"sudo ufw allow {GRAFANA_PORT}/tcp",  # Grafana
        f"sudo ufw allow {PROMETHEUS_PORT}/tcp",  # Prometheus
        f"sudo ufw allow {MONITORING_VM_EXPORTER_PORT}/tcp",  # Node Exporter
        "sudo ufw allow ssh",
        "sudo ufw --force enable"
    ]

    for cmd in commands:
        execute_remote_command_with_key(VM_IP, cmd, SSH_USER, ssh_key_path=PROXMOX_SSH_KEYFILE)

    log_success("Firewall configuration completed")


@time_function
def setup_apache_exporter():
    """Install Apache Exporter on web server for Apache metrics"""
    log_section("Setting up Apache Exporter on Web Server")

    try:
        test_ssh_key_access(FRONTEND_IP)
    except Exception as e:
        raise Exception(f"SSH key access to web server failed: {str(e)} - Please set up SSH key authentication first")

    commands = [
        "wget -q https://github.com/Lusitaniae/apache_exporter/releases/download/v1.0.10/apache_exporter-1.0.10.linux-amd64.tar.gz",
        "tar -xzf apache_exporter-*.tar.gz",
        "sudo mv apache_exporter-*/apache_exporter /usr/local/bin/",
        "rm -rf apache_exporter-*",
        "sudo tee /etc/systemd/system/apache_exporter.service <<EOF\n"
        "[Unit]\n"
        "Description=Apache Exporter\n"
        "After=network.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        "ExecStart=/usr/local/bin/apache_exporter --scrape_uri=http://localhost/server-status?auto\n"
        "Restart=on-failure\n"
        "RestartSec=5\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
        "EOF",
        "sudo systemctl daemon-reload",
        "sudo systemctl start apache_exporter",
        "sudo systemctl enable apache_exporter",
        f"sudo ufw allow {WEBSERVER_APACHE_EXPORTER_PORT}/tcp"
    ]

    for cmd in commands:
        execute_remote_command_with_key(FRONTEND_IP, cmd, SSH_USER, PROXMOX_SSH_KEYFILE)

    log_success("Apache Exporter setup completed")


@time_function
def setup_node_exporter_on_webserver():
    """Install Node Exporter on web server for system metrics"""
    log_section("Setting up Node Exporter on Web Server")

    try:
        test_ssh_key_access(FRONTEND_IP)
    except Exception as e:
        raise Exception(f"SSH key access to web server failed: {str(e)} - Please set up SSH key authentication first")

    commands = [
        "wget -q https://github.com/prometheus/node_exporter/releases/download/v1.9.1/node_exporter-1.9.1.linux-amd64.tar.gz",
        "tar -xzf node_exporter-1.9.1.linux-amd64.tar.gz",
        "sudo cp node_exporter-1.9.1.linux-amd64/node_exporter /usr/local/bin/",
        "sudo useradd --no-create-home --shell /usr/sbin/nologin prometheus 2>/dev/null || true",
        "rm -rf node_exporter-1.9.1.linux-amd64*",
        "sudo tee /etc/systemd/system/node_exporter.service <<EOF\n"
        "[Unit]\n"
        "Description=Node Exporter\n"
        "Wants=network-online.target\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        "User=prometheus\n"
        "Group=prometheus\n"
        "Type=simple\n"
        "ExecStart=/usr/local/bin/node_exporter\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
        "EOF",
        "sudo systemctl daemon-reload",
        "sudo systemctl start node_exporter",
        "sudo systemctl enable node_exporter",
        f"sudo ufw allow {WEBSERVER_VM_EXPORTER_PORT}/tcp"
    ]

    for cmd in commands:
        execute_remote_command_with_key(FRONTEND_IP, cmd, SSH_USER, PROXMOX_SSH_KEYFILE)

    log_success("Node Exporter on web server setup completed")


@time_function
def setup_pve_exporter_token():
    """
    Creates an API-Token for the Prometheus PVE Exporter with minimal permissions
    """

    log_section("Creating API token for PVE exporter")

    proxmox = ProxmoxAPI(PROXMOX_IP, user=PROXMOX_USER, password=PROXMOX_PASSWORD, verify_ssl=False)

    existing_tokens = proxmox.access.users(PROXMOX_USER).token.get()
    if any(t["tokenid"] == PROXMOX_EXPORTER_TOKEN_NAME for t in existing_tokens):
        log_error(f"Token '{PROXMOX_EXPORTER_TOKEN_NAME}' already exists!")
        raise Exception("Failed to create API token for PVE exporter")
    else:
        result = proxmox.access.users(PROXMOX_USER).token(PROXMOX_EXPORTER_TOKEN_NAME).post(
            comment="Prometheus Exporter API Token",
            privsep=1
        )
        token_value = result["value"]

    full_token_id = f"{PROXMOX_USER}!{PROXMOX_EXPORTER_TOKEN_NAME}"

    proxmox.access.acl.put(
        path="/",
        roles="PVEAuditor",
        tokens=full_token_id
    )

    log_success(f"Token created:\nUser: {PROXMOX_USER}\nToken ID: {full_token_id}")

    os.makedirs(os.path.dirname(PVE_EXPORTER_ENV), exist_ok=True)
    with open(PVE_EXPORTER_ENV, "w") as env_file:
        env_file.write(f"PROXMOX_USER={PROXMOX_USER}\n")
        env_file.write(f"PROXMOX_EXPORTER_TOKEN_NAME={PROXMOX_EXPORTER_TOKEN_NAME}\n")
        env_file.write(f"PROXMOX_EXPORTER_TOKEN_VALUE={token_value}\n")
        env_file.write(f"PROXMOX_IP={PROXMOX_IP}\n")
        env_file.write(f"PROXMOX_EXPORTER_PORT={PROXMOX_EXPORTER_PORT}\n")

    os.chmod(PVE_EXPORTER_ENV, 0o600)
    log_success(f".env written to {PVE_EXPORTER_ENV}")

    return full_token_id, token_value


@time_function
def setup_proxmox_exporter():
    """Install and configure Proxmox Exporter for Proxmox metrics"""
    log_section("Setting up Proxmox Exporter")

    service_content = f"""
[Unit]
Description=Prometheus exporter for Proxmox VE
After=network.target

[Service]
Type=simple
User=root
EnvironmentFile={PVE_EXPORTER_ENV}
ExecStart=/bin/bash -c '\\
  source {PVE_EXPORTER_ENV} && \\
  export PVE_USER="$PROXMOX_USER" && \\
  export PVE_TOKEN_NAME="$PROXMOX_EXPORTER_TOKEN_NAME" && \\
  export PVE_TOKEN_VALUE="$PROXMOX_EXPORTER_TOKEN_VALUE" && \\
  export PVE_URL=https://localhost:{PROXMOX_PORT}/ && \\
  export PVE_VERIFY_SSL=false && \\
  exec /usr/local/bin/pve_exporter --web.listen-address {PROXMOX_IP}:{PROXMOX_EXPORTER_PORT}'
Restart=on-failure
RestartSec=5s
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""
    with open("/etc/systemd/system/prometheus-pve-exporter.service", "w") as f:
        f.write(service_content)

    commands = [
        "pip3 install --upgrade prometheus-pve-exporter --break-system-packages",
        "systemctl daemon-reload",
        "systemctl enable prometheus-pve-exporter",
        "systemctl start prometheus-pve-exporter"
    ]

    for cmd in commands:
        try:
            if "pip3 install" in cmd:
                exit_code = run_cmd_with_realtime_output(cmd.split(), check=True)
            else:
                run_cmd(cmd.split(), check=True)
        except Exception as e:
            log_warning(f"Warning during setup: {e}")
            if "systemctl start" in cmd:
                raise Exception("Failed to start exporter service")

    # Verify exporter is working
    time.sleep(1)
    try:
        result = run_cmd(
            f"curl -s http://{PROXMOX_IP}:{PROXMOX_EXPORTER_PORT}/pve | grep pve_up",
            check=True,
            shell=True,
            capture_output=True
        )
        if not any("pve_up" in line and " 1.0" in line for line in result.stdout.splitlines()):
            raise Exception("Exporter not returning valid metrics")
        log_success("Proxmox exporter running successfully")
    except Exception as e:
        log_error("Exporter verification failed, checking logs...")
        run_cmd("journalctl -u prometheus-pve-exporter -n 20 --no-pager", check=False, shell=True)
        raise Exception(f"Exporter verification failed: {str(e)}")


@time_function
def setup_postgres_exporter():
    """Install Postgres Exporter on database server for PostgreSQL metrics"""
    log_section("Setting up Postgres Exporter")

    try:
        test_ssh_key_access(DATABASE_IP)
    except Exception as e:
        raise Exception(
            f"SSH key access to database server failed: {str(e)} - Please set up SSH key authentication first")

    # SQL commands to create monitoring user
    sql_commands = [
        f"CREATE USER postgres_exporter WITH PASSWORD '{POSTGRES_EXPORTER_PASSWORD}';",
        "ALTER USER postgres_exporter SET SEARCH_PATH TO postgres_exporter,pg_catalog;",
        "GRANT CONNECT ON DATABASE heist TO postgres_exporter;",
        "GRANT pg_monitor TO postgres_exporter;"
    ]

    commands = [
        "sudo useradd -rs /bin/false postgres_exporter || true",
        "sudo mkdir -p /etc/postgres_exporter",
        "sudo chown postgres_exporter:postgres_exporter /etc/postgres_exporter",
        "wget -q https://github.com/prometheus-community/postgres_exporter/releases/download/v0.17.1/postgres_exporter-0.17.1.linux-amd64.tar.gz",
        "tar -xzf postgres_exporter-*.tar.gz",
        "sudo mv postgres_exporter-*/postgres_exporter /usr/local/bin/",
        "sudo chmod +x /usr/local/bin/postgres_exporter",
        "sudo useradd -rs /bin/false postgres_exporter || true",
        f"sudo tee /etc/default/postgres_exporter <<EOF\n"
        f'DATA_SOURCE_NAME="postgresql://postgres_exporter:{POSTGRES_EXPORTER_PASSWORD}@localhost:{DATABASE_PORT}/heist?sslmode=disable"\n'
        "EOF",
        "sudo tee /etc/systemd/system/postgres_exporter.service <<EOF\n"
        "[Unit]\n"
        "Description=PostgreSQL Exporter\n"
        "Wants=network-online.target\n"
        "After=network-online.target postgresql.service\n\n"
        "[Service]\n"
        "User=postgres_exporter\n"
        "EnvironmentFile=/etc/default/postgres_exporter\n"
        "ExecStart=/usr/local/bin/postgres_exporter \\\n"
        f"   --web.listen-address=:{POSTGRES_EXPORTER_PORT} \\\n"
        "   --extend.query-path=/etc/postgres_exporter/queries.yaml\n"
        "Restart=always\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
        "EOF",
        "sudo systemctl daemon-reload",
        "sudo systemctl start postgres_exporter",
        "sudo systemctl enable postgres_exporter",
        f"sudo ufw allow {POSTGRES_EXPORTER_PORT}/tcp"
    ]

    try:
        # Create database monitoring user
        for sql in sql_commands:
            execute_remote_command_with_key(
                DATABASE_IP,
                f'sudo -u postgres psql -d heist -c "{sql}"',
                SSH_USER,
                PROXMOX_SSH_KEYFILE
            )

        # Install and configure exporter
        for cmd in commands:
            execute_remote_command_with_key(DATABASE_IP, cmd, SSH_USER, PROXMOX_SSH_KEYFILE)

        log_success("Postgres Exporter installed successfully")

    except Exception as e:
        raise Exception(f"Failed to setup Postgres Exporter: {str(e)}")


@time_function
def setup_node_exporter_on_database_server():
    """Install Node Exporter on database server for system metrics"""
    log_section("Setting up Node Exporter on Database Server")

    try:
        test_ssh_key_access(DATABASE_IP)
    except Exception as e:
        raise Exception(
            f"SSH key access to database server failed: {str(e)} - Please set up SSH key authentication first")

    commands = [
        "wget -q https://github.com/prometheus/node_exporter/releases/download/v1.9.1/node_exporter-1.9.1.linux-amd64.tar.gz",
        "tar -xzf node_exporter-1.9.1.linux-amd64.tar.gz",
        "sudo cp node_exporter-1.9.1.linux-amd64/node_exporter /usr/local/bin/",
        "sudo useradd --no-create-home --shell /usr/sbin/nologin prometheus 2>/dev/null || true",
        "rm -rf node_exporter-1.9.1.linux-amd64*",
        "sudo tee /etc/systemd/system/node_exporter.service <<EOF\n"
        "[Unit]\n"
        "Description=Node Exporter\n"
        "Wants=network-online.target\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        "User=prometheus\n"
        "Group=prometheus\n"
        "Type=simple\n"
        "ExecStart=/usr/local/bin/node_exporter\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
        "EOF",
        "sudo systemctl daemon-reload",
        "sudo systemctl start node_exporter",
        "sudo systemctl enable node_exporter",
        f"sudo ufw allow {DATABASE_VM_EXPORTER_PORT}/tcp"
    ]

    for cmd in commands:
        execute_remote_command_with_key(DATABASE_IP, cmd, SSH_USER, PROXMOX_SSH_KEYFILE)

    log_success("Node Exporter on database server setup completed")


@time_function
def verify_services():
    """Verify all monitoring services are running correctly"""
    log_section("Verifying Services")

    # Check Proxmox exporter services
    local_commands = [
        "systemctl is-active prometheus-pve-exporter",
        "systemctl is-active node_exporter"
    ]

    for cmd in local_commands:
        try:
            run_cmd(cmd.split(), check=True)
        except Exception as e:
            raise Exception(f"Proxmox service check failed: {cmd}")

    # Check monitoring VM services
    vm_commands = [
        "sudo systemctl is-active prometheus",
        "sudo systemctl is-active grafana-server",
        "sudo systemctl is-active node_exporter"
    ]

    for cmd in vm_commands:
        execute_remote_command_with_key(VM_IP, cmd, SSH_USER, ssh_key_path=PROXMOX_SSH_KEYFILE)

    # Check web server services
    web_server_commands = [
        "sudo systemctl is-active apache_exporter",
        "sudo systemctl is-active node_exporter"
    ]

    for cmd in web_server_commands:
        execute_remote_command_with_key(FRONTEND_IP, cmd, SSH_USER, PROXMOX_SSH_KEYFILE)

    # Check database server services
    database_server_commands = [
        "sudo systemctl is-active postgres_exporter",
        "sudo systemctl is-active node_exporter"
    ]

    for cmd in database_server_commands:
        execute_remote_command_with_key(DATABASE_IP, cmd, SSH_USER, PROXMOX_SSH_KEYFILE)

    log_success("All services verified and running")


@time_function
def configure_proxmox_iptables():
    """Configure iptables rules for port forwarding to monitoring VM"""
    log_section("Configuring Proxmox IPTables")

    monitoring_vm_ip = VM_IP
    backend_interface = BACKEND_NETWORK_DEVICE

    iptables_commands = [
        # Port forwarding for Grafana
        f"iptables -t nat -A PREROUTING -p tcp -d {PROXMOX_INTERNAL_IP} --dport {GRAFANA_PORT} -j DNAT --to-destination {monitoring_vm_ip}:{GRAFANA_PORT}",
        # Masquerade traffic from monitoring VM
        f"iptables -t nat -A POSTROUTING -s {monitoring_vm_ip} -o {backend_interface} -j MASQUERADE",
        # Allow forwarded Grafana traffic
        f"iptables -A FORWARD -p tcp -d {monitoring_vm_ip} --dport {GRAFANA_PORT} -m state --state NEW,ESTABLISHED,RELATED -j ACCEPT",
        f"iptables -A FORWARD -p tcp -s {monitoring_vm_ip} --sport {GRAFANA_PORT} -m state --state ESTABLISHED,RELATED -j ACCEPT",
    ]

    for cmd in iptables_commands:
        try:
            log_debug(f"Executing iptables command: {cmd}")
            run_cmd(cmd, check=True, shell=True)
            try:
                with open(IPTABLES_FILE, "a") as f:
                    f.write(cmd + "\n")
            except Exception as file_err:
                log_warning(f"Failed to write rule to {IPTABLES_FILE}: {file_err}")

        except Exception as e:
            log_warning(f"Failed to execute iptables command: {cmd}")
            log_warning(f"Error: {e}")
            continue

    log_success("Proxmox iptables configuration completed")


@time_function
def cleanup_on_failure():
    """Clean up monitoring VM if setup fails"""
    log_section("Cleaning Up Failed Setup")
    try:
        proxmox.nodes(PROXMOX_HOSTNAME).qemu(MONITORING_VM_ID).delete()
        log_success("VM cleanup completed")
    except Exception as e:
        log_error(f"Cleanup error: {str(e)}")


@time_function
def setup_monitoring_stack():
    """Main orchestration function for monitoring stack setup"""
    time_start = datetime.datetime.now()
    log_section("Starting Monitoring Stack Setup")

    try:
        with Timer():
            log_info("1. Importing monitoring VM")
            import_monitoring_vm()

            log_info("2. Changing default password and generation SSH keyfile")
            remote_setup_user_ssh_keys(
                ip=VM_IP,
                username=SSH_USER,
                keyfile=f"{PROXMOX_SSH_KEYFILE}.pub",
                old_password=DEFAULT_SSH_PASSWORD,
                new_password=NEW_SSH_PASSWORD,
                admin_user=SSH_USER
            )

            log_info("3. Installing required packages")
            install_packages()

            log_info("4. Setting up Grafana")
            setup_grafana()

            log_info("5. Setting up Prometheus")
            setup_prometheus()

            log_info("6.1 Setting up Node Exporter on Monitoring VM (with systemd)")
            setup_node_exporter()

            log_info("6.2 Setting up Node Exporter on Proxmox Host (with systemd)")
            setup_node_exporter_on_proxmox()

            log_info("6.3 Configuring Prometheus targets")
            configure_prometheus_yml()

            log_info("6.4 Setting up Apache Exporter on web server")
            setup_apache_exporter()

            log_info("6.5 Setting up Node Exporter on web server")
            setup_node_exporter_on_webserver()

            log_info("6.6.1 Setting up AuthToken for Proxmox Exporter")
            setup_pve_exporter_token()

            log_info("6.6.2 Setting up Proxmox Exporter")
            setup_proxmox_exporter()

            log_info("6.7 Setting up Postgres Exporter")
            setup_postgres_exporter()

            log_info("6.8 Setting up Node Exporter on database server")
            setup_node_exporter_on_database_server()

            log_info("7. Configuring firewall")
            configure_firewall()

            log_info("8. Verifying services")
            verify_services()

            log_info("9. Configuring Proxmox iptables for port forwarding")
            configure_proxmox_iptables()

        time_end = datetime.datetime.now()
        time_elapsed = time_end - time_start

        log_section("Setup Complete")
        log_success("Monitoring setup completed successfully!")
        log_info(f"Setup completed in {time_elapsed}")
        log_info(f"Grafana: http://{VM_IP}:{GRAFANA_PORT} (admin/admin)")
        log_info(f"Prometheus: http://{VM_IP}:{PROMETHEUS_PORT}")

    except Exception as e:
        log_error(f"Setup failed: {str(e)}")
        cleanup_on_failure()
        raise


@time_function
def main():
    """Main execution function with argument parsing"""
    global DEBUG_MODE

    parser = argparse.ArgumentParser(description="Monitoring Stack Setup Script")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug output")
    args = parser.parse_args()

    DEBUG_MODE = args.debug

    try:
        setup_monitoring_stack()
    except KeyboardInterrupt:
        log_info("Setup interrupted by user")
        sys.exit(1)
    except Exception as e:
        log_error(f"Setup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()