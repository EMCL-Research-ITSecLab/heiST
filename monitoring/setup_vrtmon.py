"""
Network Bridge Configuration Script
Creates restricted IPv6 bridge for Wazuh monitoring with firewall rules
FIXED: Now properly filters bridge traffic using br_netfilter
"""

import os
import sys
import time
import re
import argparse
import subprocess
import shlex
from dotenv import load_dotenv


sys.stdout.reconfigure(line_buffering=True)

# Load environment variables
load_dotenv()
from monitoring.utils.script_helper import (
    log_info, log_debug, log_error, log_warning, log_success, log_section,
    execute_remote_command, execute_remote_command_with_key, run_cmd, Timer, time_function, DEBUG_MODE
)
from backend.proxmox_api_calls import add_network_device_api_call

# ==== CONFIGURATION CONSTANTS ====
BRIDGE_NAME = os.getenv("WAZUH_NETWORK_DEVICE", "vrtmon")
BRIDGE_IP = os.getenv("WAZUH_NETWORK_DEVICE_IPV6", "fd12:3456:789a:1::1")
BRIDGE_CIDR = os.getenv("WAZUH_NETWORK_DEVICE_CIDR", "64")
TARGET_NETWORK = os.getenv("WAZUH_NETWORK_SUBNET", "fd12:3456:789a:1::/64")
WAZUH_REGISTRATION_PORT = str(os.getenv("WAZUH_REGISTRATION_PORT", "1515"))
WAZUH_COMMUNICATION_PORT = str(os.getenv("WAZUH_COMMUNICATION_PORT", "1514"))
BANNER_SERVER_PORT = str(os.getenv("BANNER_SERVER_PORT", 80))
ALLOWED_PORTS = [WAZUH_REGISTRATION_PORT, WAZUH_COMMUNICATION_PORT, BANNER_SERVER_PORT]
MONITORING_IP = os.getenv("MONITORING_HOST", "10.0.0.103")
MONITORING_ID = int(os.getenv("MONITORING_VM_ID", 9000))
SSH_USER = os.getenv("MONITORING_VM_USER", "ubuntu")
NEW_SSH_PASSWORD = os.getenv("MONITORING_VM_PASSWORD", "meow1234")
WAZUH_MANAGER_IPV6 = os.getenv("WAZUH_MANAGER_IPV6", "fd12:3456:789a:1::101/64")
WAZUH_NETWORK_DEVICE_IPV6 = os.getenv("WAZUH_NETWORK_DEVICE_IPV6", "fd12:3456:789a:1::1")
PROXMOX_SSH_KEYFILE = os.getenv("PROXMOX_SSH_KEYFILE", "/root/.ssh/id_rsa.pub")
MONITORING_VM_MAC_ADDRESS = os.getenv("MONITORING_VM_MAC_ADDRESS")


def get_remote_interface_by_mac(ip, mac_prefix, user=SSH_USER, password=NEW_SSH_PASSWORD, timeout=60, interval=30):
    """
    Find interface name by MAC prefix on remote host via SSH with retries

    Args:
        ip: Remote host IP address
        mac_prefix: MAC address prefix to match (e.g., "0a:01")
        user: SSH username
        password: SSH password
        timeout: Maximum seconds to wait for interface
        interval: Seconds between retries

    Returns:
        Interface name string

    Raises:
        TimeoutError: If interface not found within timeout
    """
    end_time = time.time() + timeout
    command = "ip -o link | awk '{print $2, $17}'"

    while time.time() < end_time:
        interface_name = None

        try:
            process = subprocess.Popen(
                [
                    "sshpass", "-p", password,
                    "ssh", "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=15",
                    f"{user}@{ip}", command
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            for line in process.stdout:
                parts = line.strip().split()
                if len(parts) != 2:
                    continue
                iface, mac = parts
                iface = iface.strip(':')
                if mac.lower().startswith(mac_prefix.lower()):
                    interface_name = iface
                    break

            process.stdout.close()
            process.stderr.close()
            process.wait()

            if interface_name:
                return interface_name

        except Exception as e:
            log_error(f"Error checking interfaces on {ip}: {e}")

        log_info(f"Interface with MAC prefix {mac_prefix} not found yet, retrying in {interval}s")
        time.sleep(interval)

    raise TimeoutError(f"No interface with MAC prefix {mac_prefix} appeared on {ip} within {timeout}s")


def check_bridge_exists():
    """Check if bridge interface already exists in system"""
    result = run_cmd(f'ip link show {BRIDGE_NAME}', check=False, shell=True)
    return result.returncode == 0


def check_config_exists():
    """Check if bridge configuration exists in network interfaces file"""
    try:
        with open('/etc/network/interfaces', 'r') as f:
            content = f.read()
            return BRIDGE_NAME in content
    except FileNotFoundError:
        return False


@time_function
def enable_bridge_netfilter():
    """
    Enable br_netfilter module to make bridge traffic pass through iptables
    This is CRITICAL for filtering same-subnet traffic on a bridge
    """
    log_section("Enabling Bridge Netfilter")

    # Load br_netfilter kernel module
    result = run_cmd('modprobe br_netfilter', check=False, shell=True)
    if result.returncode != 0:
        log_warning("Failed to load br_netfilter module")

    # Enable IPv6 bridge netfilter
    run_cmd('sysctl -w net.bridge.bridge-nf-call-ip6tables=1', check=False, shell=True)

    # Make it persistent
    sysctl_config = """
# Enable bridge netfilter for IPv6 firewall rules
net.bridge.bridge-nf-call-ip6tables=1
"""
    try:
        with open('/etc/sysctl.d/99-bridge-netfilter.conf', 'w') as f:
            f.write(sysctl_config)
        log_success("Bridge netfilter enabled (bridge traffic will now pass through ip6tables)")
    except Exception as e:
        log_warning(f"Could not write persistent sysctl config: {e}")

    # Also ensure module loads on boot
    modules_config = "br_netfilter\n"
    try:
        with open('/etc/modules-load.d/bridge.conf', 'w') as f:
            f.write(modules_config)
        log_success("Added br_netfilter to modules-load.d for persistence")
    except Exception as e:
        log_warning(f"Could not write modules-load config: {e}")


@time_function
def create_bridge_temp():
    """Create temporary bridge interface"""
    log_section("Creating Temporary Bridge Interface")

    commands = [
        f'ip link add name {BRIDGE_NAME} type bridge',
        f'ip link set dev {BRIDGE_NAME} up',
        f'ip -6 address add {BRIDGE_IP}/{BRIDGE_CIDR} dev {BRIDGE_NAME}'
    ]

    for cmd in commands:
        result = run_cmd(cmd, shell=True)
        if result.returncode != 0:
            log_error(f"Failed to execute: {cmd}")
            raise Exception(f"Bridge creation failed at command: {cmd}")

    log_success("Temporary bridge created successfully")


@time_function
def setup_firewall():
    """
    Configure strict IPv6 firewall rules - Hub and Spoke model
    Only allows communication between Wazuh Manager and VMs
    Blocks all VM-to-VM traffic
    """
    log_section("Configuring IPv6 Firewall Rules (Hub-and-Spoke)")

    # Flush existing forward rules for clean start
    run_cmd('ip6tables -F FORWARD', check=False, shell=True)

    # Set default forward policy to DROP
    run_cmd('ip6tables -P FORWARD DROP', check=False, shell=True)

    # Allow established/related connections (stateful return)
    run_cmd('ip6tables -A FORWARD -m state --state ESTABLISHED,RELATED -j ACCEPT', check=False, shell=True)

    # Allow ICMPv6 (needed for IPv6 to work properly)
    run_cmd('ip6tables -A FORWARD -p ipv6-icmp -j ACCEPT', check=False, shell=True)

    # CRITICAL: Extract Wazuh Manager IP without CIDR notation
    wazuh_ip = WAZUH_MANAGER_IPV6.split('/')[0]

    # Allow traffic FROM Wazuh Manager TO VMs on specific ports
    for port in ALLOWED_PORTS:
        # TCP from Manager to VMs
        run_cmd(f'ip6tables -A FORWARD -s {wazuh_ip} -d {TARGET_NETWORK} -p tcp --dport {port} -m state --state NEW -j ACCEPT',
                check=False, shell=True)
        # TCP from VMs to Manager
        run_cmd(f'ip6tables -A FORWARD -s {TARGET_NETWORK} -d {wazuh_ip} -p tcp --dport {port} -m state --state NEW -j ACCEPT',
                check=False, shell=True)

        # UDP from Manager to VMs
        run_cmd(f'ip6tables -A FORWARD -s {wazuh_ip} -d {TARGET_NETWORK} -p udp --dport {port} -j ACCEPT',
                check=False, shell=True)
        # UDP from VMs to Manager
        run_cmd(f'ip6tables -A FORWARD -s {TARGET_NETWORK} -d {wazuh_ip} -p udp --dport {port} -j ACCEPT',
                check=False, shell=True)

    # Log dropped packets for debugging (catches VM-to-VM attempts)
    run_cmd('ip6tables -A FORWARD -j LOG --log-prefix "IP6TABLES-DROPPED: " --log-level 4', check=False, shell=True)

    log_success("IPv6 firewall rules configured (Hub-and-Spoke model)")
    log_info(f"Only traffic between {wazuh_ip} and VMs allowed")
    log_info("All VM-to-VM communication blocked")

@time_function
def add_to_interfaces():
    """Add persistent bridge configuration to network interfaces file"""
    log_section("Adding Persistent Bridge Configuration")

    wazuh_ip = WAZUH_MANAGER_IPV6.split('/')[0]

    # Build firewall rules for post-up commands
    firewall_rules = ""
    for port in ALLOWED_PORTS:
        # TCP rules
        firewall_rules += f'    post-up ip6tables -A FORWARD -s {TARGET_NETWORK} -d {wazuh_ip} -p tcp --dport {port} -m state --state NEW -j ACCEPT\n'
        firewall_rules += f'    post-up ip6tables -A FORWARD -s {wazuh_ip} -d {TARGET_NETWORK} -p tcp --dport {port} -m state --state NEW -j ACCEPT\n'
        # UDP rules
        firewall_rules += f'    post-up ip6tables -A FORWARD -s {TARGET_NETWORK} -d {wazuh_ip} -p udp --dport {port} -j ACCEPT\n'
        firewall_rules += f'    post-up ip6tables -A FORWARD -s {wazuh_ip} -d {TARGET_NETWORK} -p udp --dport {port} -j ACCEPT\n'

    config_content = f'''
# IPv6 VM Network Bridge with restricted TCP/UDP access
auto {BRIDGE_NAME}
iface {BRIDGE_NAME} inet6 static
    address {BRIDGE_IP}/{BRIDGE_CIDR}
    bridge-ports none
    bridge-stp off
    bridge-fd 0
    # Enable bridge netfilter BEFORE setting up firewall rules
    pre-up modprobe br_netfilter || true
    pre-up sysctl -w net.bridge.bridge-nf-call-ip6tables=1 || true
    # Firewall configuration - TCP/UDP on ports {', '.join(ALLOWED_PORTS)}
    post-up ip6tables -F FORWARD
    post-up ip6tables -P FORWARD DROP
    post-up ip6tables -A FORWARD -m state --state ESTABLISHED,RELATED -j ACCEPT
    post-up ip6tables -A FORWARD -p ipv6-icmp -j ACCEPT
{firewall_rules}    post-up ip6tables -A FORWARD -j LOG --log-prefix "IP6TABLES-DROPPED: " --log-level 4
'''

    try:
        with open('/etc/network/interfaces', 'a') as f:
            f.write(config_content)
        log_success("Added bridge configuration to /etc/network/interfaces")
    except PermissionError:
        log_warning("Insufficient permissions, using sudo to write configuration")
        result = run_cmd(f'echo "{config_content}" | sudo tee -a /etc/network/interfaces > /dev/null', check=False,
                         shell=True)
        if result.returncode == 0:
            log_success("Added bridge configuration using sudo")
        else:
            log_error("Failed to add bridge configuration even with sudo")


@time_function
def connect_to_monitoring():
    """Connect monitoring VM to bridge network with persistent netplan configuration"""
    log_section("Connecting Monitoring VM to Bridge")

    # Add network device to monitoring VM
    add_network_device_api_call(MONITORING_ID, "net31", BRIDGE_NAME, "e1000", "0A:01")

    # Wait for interface to appear
    local_device_name = get_remote_interface_by_mac(MONITORING_IP, "0A:01", timeout=30, interval=2)
    log_info(f"Found remote interface: {local_device_name}")

    # Create comprehensive netplan configuration that replaces all existing configs
    netplan_config = f"""network:
  version: 2
  ethernets:
    {local_device_name}:
      match:
        name: "{local_device_name}"
      dhcp4: false
      dhcp6: false
      addresses:
        - {WAZUH_MANAGER_IPV6}
      routes:
        - to: ::/0
          via: {WAZUH_NETWORK_DEVICE_IPV6}
    backend:
      match:
        macaddress: "{MONITORING_VM_MAC_ADDRESS.lower()}"
      dhcp4: true
      dhcp4-overrides:
        use-dns: true
"""

    # Write netplan configuration to remote host
    netplan_path = "/etc/netplan/99-wazuh-monitoring.yaml"

    # Escape the config for safe shell transmission
    config_escaped = shlex.quote(netplan_config)

    commands = [
        # Remove old netplan configs (cloud-init and others)
        "sudo rm -f /etc/netplan/50-cloud-init.yaml",
        "sudo rm -f /etc/netplan/01-*.yaml",

        # Write new comprehensive config
        f"echo {config_escaped} | sudo tee {netplan_path} > /dev/null",
        f"sudo chmod 600 {netplan_path}",

        # Disable cloud-init network management to prevent regeneration
        "sudo mkdir -p /etc/cloud/cloud.cfg.d",
        "echo 'network: {config: disabled}' | sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg > /dev/null",

        # Apply netplan
        "sudo netplan apply"
    ]

    for cmd in commands:
        result = execute_remote_command_with_key(
            MONITORING_IP,
            cmd,
            SSH_USER,
            ssh_key_path=PROXMOX_SSH_KEYFILE
        )
        if result and result.returncode != 0:
            log_warning(f"Command may have failed (could be expected): {cmd}")

    log_success("Monitoring VM connected to bridge network with persistent netplan configuration")
    log_info(f"Configuration written to {netplan_path}")
    log_info("Old netplan configs removed, cloud-init network management disabled")


@time_function
def main():
    """Main execution function"""
    global DEBUG_MODE

    parser = argparse.ArgumentParser(description="Network Bridge Configuration Script")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug output")
    args = parser.parse_args()

    DEBUG_MODE = args.debug

    log_section(f"Creating Restricted IPv6 Bridge: {BRIDGE_NAME}")
    log_info(f"Allowed ports: UDP {', '.join(ALLOWED_PORTS)}")

    # Verify bridge doesn't already exist
    if check_bridge_exists() or check_config_exists():
        log_error(f"Bridge {BRIDGE_NAME} already exists")
        sys.exit(1)

    try:
        with Timer():
            # CRITICAL: Enable br_netfilter FIRST
            enable_bridge_netfilter()

            # Create temporary bridge
            create_bridge_temp()

            # Configure firewall rules
            setup_firewall()

            # Add persistent configuration
            add_to_interfaces()

            # Connect monitoring VM
            connect_to_monitoring()

            log_section("Bridge Configuration Summary")
            log_success("Successfully created restricted IPv6 bridge")
            log_info(f"Bridge name: {BRIDGE_NAME}")
            log_info(f"Gateway IP: {BRIDGE_IP}/{BRIDGE_CIDR}")
            log_info(f"VM Network: {TARGET_NETWORK}")
            log_info(f"Allowed traffic: TCP ports {', '.join(ALLOWED_PORTS)} only")
            log_info("Stateful return traffic is automatically allowed")
            log_info("Bridge netfilter enabled - ip6tables rules apply to bridge traffic")

    except Exception as e:
        log_error(f"Bridge configuration failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Verify script is running with root privileges
    if os.geteuid() != 0:
        log_error("This script must be run as root")
        sys.exit(1)

    main()