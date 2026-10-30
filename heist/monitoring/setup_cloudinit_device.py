"""
Network Bridge Configuration Script
Creates and configures a bridge interface for cloud-init VM networks
"""

import subprocess
import os
import sys
import argparse
import ipaddress
from heist.environment import load_installer_env as load_dotenv
sys.stdout.reconfigure(line_buffering=True)

# Load environment variables
load_dotenv()
IPTABLES_FILE = os.getenv("IPTABLES_FILE","/etc/iptables-backend/iptables.sh")

from heist.monitoring.utils.script_helper import (
    log_info, log_debug, log_error, log_warning, log_success, log_section,
    run_cmd, Timer, time_function, DEBUG_MODE
)

# Configuration Constants
BRIDGE_NAME = os.getenv("CLOUD_INIT_NETWORK_DEVICE", "vmbr-cloud")
BRIDGE_IP = os.getenv("CLOUD_INIT_NETWORK_DEVICE_IP", "10.32.0.1")
BRIDGE_CIDR = os.getenv("CLOUD_INIT_NETWORK_DEVICE_CIDR", "20")
TARGET_NETWORK = os.getenv("CLOUD_INIT_NETWORK_SUBNET", "10.32.0.0/20")


def check_bridge_exists():
    """Verify if bridge interface already exists in system"""
    result = run_cmd(f'ip link show {BRIDGE_NAME}', check=False, shell=True)
    return result.returncode == 0


def check_config_exists():
    """Check if bridge configuration exists in network interfaces file"""
    try:
        with open('/etc/network/interfaces', 'r') as f:
            content = f.read()
            return BRIDGE_NAME in content
    except FileNotFoundError:
        log_warning("Network interfaces file not found")
        return False
    except PermissionError:
        log_error("Permission denied reading network interfaces file")
        return False


@time_function
def create_bridge_temp():
    """Create temporary bridge interface"""
    log_section("Creating temporary bridge interface")

    commands = [
        f'ip link add name {BRIDGE_NAME} type bridge',
        f'ip link set dev {BRIDGE_NAME} up',
        f'ip address add {BRIDGE_IP}/{BRIDGE_CIDR} dev {BRIDGE_NAME}'
    ]

    for cmd in commands:
        result = run_cmd(cmd, shell=True)
        if result.returncode != 0:
            log_error(f"Failed to execute: {cmd}")
            raise RuntimeError(f"Bridge creation failed at step: {cmd}")

    log_success("Temporary bridge created successfully")


@time_function
def enable_ip_forwarding():
    """Enable IP forwarding temporarily and permanently"""
    log_section("Configuring IP forwarding")

    # Enable temporarily
    result = run_cmd('sysctl -w net.ipv4.ip_forward=1', shell=True)
    if result.returncode != 0:
        log_warning("Failed to enable IP forwarding temporarily")

    # Enable permanently
    sysctl_conf = '/etc/sysctl.d/99-sysctl.conf'
    try:
        with open(sysctl_conf, 'r') as f:
            content = f.read()

        if 'net.ipv4.ip_forward=1' not in content:
            with open(sysctl_conf, 'a') as f:
                f.write('\nnet.ipv4.ip_forward=1\n')
            log_success("Permanently enabled IP forwarding")
        else:
            log_info("IP forwarding already enabled in sysctl configuration")

    except (FileNotFoundError, PermissionError) as e:
        log_error(f"Failed to update sysctl configuration: {e}")


@time_function
def setup_nat_and_firewall():
    """Configure NAT masquerading and firewall rules"""
    log_section("Setting up NAT and firewall rules")

    rules = [
        f'iptables -t nat -A POSTROUTING -s {TARGET_NETWORK} -o vmbr0 -j MASQUERADE',
        f'iptables -A FORWARD -s {TARGET_NETWORK} -o vmbr0 -j ACCEPT',
        f'iptables -A FORWARD -d {TARGET_NETWORK} -i vmbr0 -m state --state RELATED,ESTABLISHED -j ACCEPT'
    ]

    for rule in rules:
        result = run_cmd(rule, check=False, shell=True)
        if result.returncode != 0:
            log_warning(f"Failed to set up rule: {rule}")
        else:
            try:
                with open(IPTABLES_FILE, "a") as f:
                    f.write(rule + "\n")
            except Exception as e:
                log_warning(f"Failed to write rule to {IPTABLES_FILE}: {e}")

    log_success("NAT and firewall rules configured")


@time_function
def add_to_interfaces():
    """Add persistent bridge configuration to network interfaces file"""
    log_section("Adding persistent bridge configuration")

    config_content = f'''
# Cloud-Init VM Network Bridge
auto {BRIDGE_NAME}
iface {BRIDGE_NAME} inet static
    address {BRIDGE_IP}/{BRIDGE_CIDR}
    bridge-ports none
    bridge-stp off
    bridge-fd 0
    post-up echo 1 > /proc/sys/net/ipv4/ip_forward
'''

    try:
        with open('/etc/network/interfaces', 'a') as f:
            f.write(config_content)
        log_success("Successfully updated network interfaces file")
    except PermissionError:
        log_warning("Insufficient permissions, using sudo to append configuration")
        result = run_cmd(f'echo "{config_content}" >> /etc/network/interfaces', check=False, shell=True)
        if result.returncode != 0:
            log_error("Failed to update network interfaces file even with sudo")
            raise


@time_function
def validate_configuration():
    """Validate the current configuration parameters"""
    log_section("Validating configuration parameters")

    # Validate IP address format
    try:
        ipaddress.IPv4Address(BRIDGE_IP.split('/')[0])
    except ipaddress.AddressValueError:
        raise ValueError(f"Invalid bridge IP address: {BRIDGE_IP}")

    # Validate CIDR
    try:
        cidr = int(BRIDGE_CIDR)
        if not (0 <= cidr <= 32):
            raise ValueError(f"Invalid CIDR: {BRIDGE_CIDR}")
    except ValueError:
        raise ValueError(f"Invalid CIDR format: {BRIDGE_CIDR}")

    # Validate target network
    try:
        ipaddress.IPv4Network(TARGET_NETWORK, strict=False)
    except ipaddress.NetmaskValueError:
        raise ValueError(f"Invalid target network: {TARGET_NETWORK}")

    log_success("Configuration validation passed")


@time_function
def main():
    """Main execution function"""
    global DEBUG_MODE

    parser = argparse.ArgumentParser(description="Network Bridge Configuration Script")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug output")
    args = parser.parse_args()

    DEBUG_MODE = args.debug

    log_section(f"Creating Cloud-Init bridge: {BRIDGE_NAME}")

    # Validate configuration before proceeding
    try:
        validate_configuration()
    except ValueError as e:
        log_error(f"Configuration validation failed: {e}")
        sys.exit(1)

    # Check if bridge already exists
    if check_bridge_exists():
        log_error(f"Bridge {BRIDGE_NAME} already exists in system")
        sys.exit(1)

    if check_config_exists():
        log_error(f"Bridge {BRIDGE_NAME} already configured in network interfaces")
        sys.exit(1)

    try:
        with Timer():
            # Create temporary bridge
            create_bridge_temp()

            # Enable IP forwarding
            enable_ip_forwarding()

            # Setup NAT and firewall
            setup_nat_and_firewall()

            # Add persistent configuration
            add_to_interfaces()

            log_section("Bridge Configuration Summary")
            log_success("Successfully created Cloud-Init bridge")
            log_info(f"Bridge name: {BRIDGE_NAME}")
            log_info(f"Gateway IP: {BRIDGE_IP}/{BRIDGE_CIDR}")
            log_info(f"VM Network: {TARGET_NETWORK}")

    except Exception as e:
        log_error(f"Bridge configuration failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Ensure script runs as root
    if os.geteuid() != 0:
        log_error("This script must be run as root")
        sys.exit(1)

    main()