#!/usr/bin/env python3
"""
Orchestration Script
Master script to coordinate and execute all configuration scripts
"""

import os
import sys
import time
import argparse
from pathlib import Path
from typing import List, Tuple, Dict
from heist.environment import load_installer_env as load_dotenv, environment_file
sys.stdout.reconfigure(line_buffering=True)

# Load environment variables
load_dotenv()
MONITORING_FILES_DIR = os.getenv("MONITORING_FILES_DIR", "/root/heiST/heist/monitoring")
UTILS_DIR = f"{MONITORING_FILES_DIR}/utils"

# Import the script_helper module
from heist.monitoring.utils.script_helper import (
    log_info, log_debug, log_error, log_warning, log_success, log_section,
    run_cmd, run_cmd_with_realtime_output, Timer, time_function, DEBUG_MODE
)

MONITORING_FILES_DIR = os.getenv("MONITORING_FILES_DIR", "/root/heiST/heist/monitoring")

# ===== ENVIRONMENT VARIABLES CONFIGURATION =====
ENV_VARIABLES = [
    # Proxmox Configuration
    "PROXMOX_HOST", "PROXMOX_USER", "PROXMOX_PASSWORD", "PROXMOX_HOSTNAME",
    "PROXMOX_EXTERNAL_IP", "PROXMOX_INTERNAL_IP","PROXMOX_LVM_STORAGE", "PROXMOX_SSH_KEYFILE", "PROXMOX_EXPORTER_TOKEN_NAME",

    # Monitoring VM Configuration
    "MONITORING_VM_ID", "MONITORING_VM_NAME", "MONITORING_VM_MAC_ADDRESS",
    "MONITORING_VM_MEMORY", "MONITORING_VM_CORES", "MONITORING_VM_DISK",
    "MONITORING_HOST", "MONITORING_VM_USER", "MONITORING_VM_PASSWORD",

    # Other VMs
    "WEBSERVER_HOST", "DATABASE_HOST",

    # Network Configuration
    "BACKEND_NETWORK_SUBNET", "BACKEND_NETWORK_ROUTER", "BACKEND_NETWORK_DEVICE",
    "MONITORING_VPN_INTERFACE", "MONITORING_DMZ_INTERFACE",
    "WAZUH_NETWORK_DEVICE", "WAZUH_NETWORK_DEVICE_IPV6", "WAZUH_NETWORK_DEVICE_CIDR",
    "WAZUH_NETWORK_SUBNET", "WAZUH_MANAGER_IPV6",
    "CLOUD_INIT_NETWORK_DEVICE", "CLOUD_INIT_NETWORK_DEVICE_IP",
    "CLOUD_INIT_NETWORK_DEVICE_CIDR", "CLOUD_INIT_NETWORK_SUBNET",
    "CHALLENGES_ROOT_SUBNET", "MONITORING_DNS",

    # Directory Paths
    "MONITORING_FILES_DIR", "BACKEND_FILES_DIR", "WAZUH_FILE_DIR",
    "SURICATA_FILES_DIR", "SURICATA_RULES_DIR", "SURICATA_LOG_DIR","VECTOR_FILES_DIR",
    "VECTOR_DIR", "LOGROTATE_CONFIG_DIR","SSL_TLS_CERTS_DIR", "DNSMASQ_BACKEND_DIR",
    "ZEEK_SITE_DIR", "CLICKHOUSE_SQL_DIR", "PVE_EXPORTER_DIR", "IPTABLES_FILE"

    # Wazuh Configuration
    "WAZUH_API_USER", "WAZUH_API_PASSWORD", "WAZUH_DASHBOARD_USER",
    "WAZUH_DASHBOARD_PASSWORD", "WAZUH_INDEXER_USER", "WAZUH_INDEXER_PASSWORD",
    "WAZUH_REGISTRATION_PORT", "WAZUH_COMMUNICATION_PORT", "WAZUH_ENROLLMENT_PASSWORD",

    # Logrotate Configuration
    "ROTATE_DAYS", "PCAP_ROTATION_INTERVAL",

    # Service Ports
    "MONITORING_VM_EXPORTER_PORT", "WEBSERVER_VM_EXPORTER_PORT",
    "DATABASE_VM_EXPORTER_PORT", "PROXMOX_PORT", "PROXMOX_EXPORTER_PORT",
    "POSTGRES_EXPORTER_PORT", "WEBSERVER_APACHE_EXPORTER_PORT",
    "GRAFANA_PORT", "PROMETHEUS_PORT", "DATABASE_PORT",
    "BANNER_SERVER_PORT", "CLICKHOUSE_HTTPS_PORT", "CLICKHOUSE_NATIVE_PORT", "PROXMOX_NODE_EXPORTER_PORT",

    # Database & Authentication
    "POSTGRES_EXPORTER_PASSWORD", "UBUNTU_BASE_SERVER_URL"
]

# ===== GRAFANA ENVIRONMENT VARIABLES =====
GRAFANA_ENV_VARIABLES = [
    # Grafana core configuration
    "MONITORING_HOST", "GRAFANA_PORT", "GRAFANA_USER", "GRAFANA_PASSWORD",
    "PROMETHEUS_PORT", "GRAFANA_FILES_SETUP_DIR",
    "PROXMOX_SSH_KEYFILE", "GRAFANA_FILES_DIR",

    # Wazuh configuration
    "WAZUH_MANAGER_PORT", "WAZUH_INDEXER_USER", "WAZUH_INDEXER_PASSWORD",

    # ClickHouse configuration
    "CLICKHOUSE_HTTPS_PORT", "CLICKHOUSE_NATIVE_PORT",
    "CLICKHOUSE_USER", "CLICKHOUSE_PASSWORD",

    # SSL/TLS
    "SSL_TLS_CERTS_DIR",

    # Misc (SSH credentials for remote actions)
    "MONITORING_VM_USER", "MONITORING_VM_PASSWORD"
]

# ===== VECTOR ENVIRONMENT VARIABLES =====
VECTOR_ENV_VARIABLES = [
    "MONITORING_FILES_DIR",
    "VECTOR_DIR",
    "SSL_TLS_CERTS_DIR",
    "CLICKHOUSE_USER",
    "CLICKHOUSE_PASSWORD"
]

# ===== BACKEND ENVIRONMENT VARIABLES =====
BACKEND_ENV_VARIABLES = [
    "MONITORING_HOST",
    "WAZUH_API_PORT",
    "WAZUH_API_USER",
    "WAZUH_API_PASSWORD"
]

# ===== SCRIPT CONFIGURATION =====
SCRIPTS = [
    {
        "name": "Setup Monitoring VM",
        "path": f"{MONITORING_FILES_DIR}/setup_monitoring_vm.py",
        "description": "Creates the Monitoring VM and installs Grafana & Prometheus"
    },
    {
        "name": "Setup Network Monitoring",
        "path": f"{MONITORING_FILES_DIR}/setup_network_monitoring.py",
        "description": "Sets up Suricata, Zeek & Vector"
    },
    {
        "name": "Setup Clickhouse",
        "path": f"{MONITORING_FILES_DIR}/setup_clickhouse.py",
        "description": "Sets up Clickhouse"
    },
    {
        "name": "Configure Grafana",
        "path": f"{MONITORING_FILES_DIR}/grafana/configure_grafana.py",
        "description": "Configures Grafana Dashboards and Datasources"
    },
    {
        "name": "Setup Wazuh",
        "path": f"{MONITORING_FILES_DIR}/setup_wazuh_manager.py",
        "description": "Sets up the Wazuh Manager on the Monitoring VM"
    },
    {
        "name": "Setup Cloudinit",
        "path": f"{MONITORING_FILES_DIR}/setup_cloudinit_device.py",
        "description": "Sets up the Cloudinit Device for the challenge VMs"
    },
    {
        "name": "Setup Wazuh Monitoring Bridge",
        "path": f"{MONITORING_FILES_DIR}/setup_vrtmon.py",
        "description": "Sets up the Wazuh networkdevice for the on-host Monitoring"
    },
    {
        "name": "Setup all Services",
        "path": f"{MONITORING_FILES_DIR}/setup_services.py",
        "description": "Sets up all necessary services for the Network Monitoring, Networking and Bannering"
    },
    {
        "name": "Setup Logrotate",
        "path": f"{MONITORING_FILES_DIR}/setup_logrotate.py",
        "description": "Sets up and configures Logrotate to rotate all Logs produced by Suricata and Zeek"
    },
]


# ===== ENVIRONMENT VARIABLES MANAGEMENT =====

def extract_env_variables() -> Dict[str, str]:
    """
    Extract environment variables from current environment
    Returns: Dictionary of variable names and their values
    """
    env_vars = {}

    for var_name in ENV_VARIABLES:
        value = os.getenv(var_name)
        if value is not None:
            env_vars[var_name] = value
            log_debug(f"Found environment variable: {var_name}={value}")
        else:
            log_warning(f"Environment variable not set: {var_name}")

    return env_vars


def create_env_file(env_vars: Dict[str, str], target_path: str) -> bool:
    """
    Create a new .env file with the extracted environment variables
    """
    try:
        env_file_path = Path(target_path) / ".env"

        # Create directory if it doesn't exist
        env_file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(env_file_path, 'w') as f:
            f.write("# Environment variables for heiST Monitoring\n")
            f.write("# Generated by orchestration script\n\n")

            # Write variables in organized sections
            sections = {
                "PROXMOX CONFIGURATION": [
                    "PROXMOX_HOST", "PROXMOX_USER", "PROXMOX_PASSWORD", "PROXMOX_HOSTNAME",
                    "PROXMOX_EXTERNAL_IP", "PROXMOX_INTERNAL_IP", "PROXMOX_LVM_STORAGE", "PROXMOX_SSH_KEYFILE",
                    "PROXMOX_EXPORTER_TOKEN_NAME"
                ],
                "VM CONFIGURATION": [
                    "MONITORING_VM_ID", "MONITORING_VM_NAME", "MONITORING_VM_MAC_ADDRESS",
                    "MONITORING_VM_MEMORY", "MONITORING_VM_CORES", "MONITORING_VM_DISK",
                    "MONITORING_HOST", "MONITORING_VM_USER", "MONITORING_VM_PASSWORD",
                    "WEBSERVER_HOST", "DATABASE_HOST"
                ],
                "NETWORK CONFIGURATION": [
                    "BACKEND_NETWORK_SUBNET", "BACKEND_NETWORK_ROUTER", "BACKEND_NETWORK_DEVICE",
                    "MONITORING_VPN_INTERFACE", "MONITORING_DMZ_INTERFACE",
                    "WAZUH_NETWORK_DEVICE", "WAZUH_NETWORK_DEVICE_IPV6", "WAZUH_NETWORK_DEVICE_CIDR",
                    "WAZUH_NETWORK_SUBNET", "WAZUH_MANAGER_IPV6",
                    "CLOUD_INIT_NETWORK_DEVICE", "CLOUD_INIT_NETWORK_DEVICE_IP",
                    "CLOUD_INIT_NETWORK_DEVICE_CIDR", "CLOUD_INIT_NETWORK_SUBNET",
                    "CHALLENGES_ROOT_SUBNET", "MONITORING_DNS"
                ],
                "DIRECTORY PATHS": [
                    "MONITORING_FILES_DIR", "BACKEND_FILES_DIR", "WAZUH_FILE_DIR",
                    "SURICATA_FILES_DIR", "SURICATA_RULES_DIR", "SURICATA_LOG_DIR",
                    "VECTOR_FILES_DIR", "VECTOR_DIR", "LOGROTATE_CONFIG_DIR",
                    "SSL_TLS_CERTS_DIR", "DNSMASQ_BACKEND_DIR",
                    "ZEEK_SITE_DIR", "CLICKHOUSE_SQL_DIR", "PVE_EXPORTER_DIR", "GRAFANA_FILES_SETUP_DIR", "GRAFANA_FILES_DIR", "IPTABLES_FILE"
                ],
                "WAZUH CONFIGURATION": [
                    "WAZUH_API_USER", "WAZUH_API_PASSWORD", "WAZUH_DASHBOARD_USER",
                    "WAZUH_DASHBOARD_PASSWORD", "WAZUH_INDEXER_USER", "WAZUH_INDEXER_PASSWORD",
                    "WAZUH_REGISTRATION_PORT", "WAZUH_COMMUNICATION_PORT", "WAZUH_MANAGER_PORT", "WAZUH_API_PORT", "WAZUH_ENROLLMENT_PASSWORD"
                ],
                "LOGROTATE CONFIGURATION": [
                    "LOGROTATE_CONFIG_DIR", "ROTATE_DAYS", "PCAP_ROTATION_INTERVAL"
                ],
                "SERVICE PORTS": [
                    "MONITORING_VM_EXPORTER_PORT", "WEBSERVER_VM_EXPORTER_PORT",
                    "DATABASE_VM_EXPORTER_PORT", "PROXMOX_PORT", "PROXMOX_EXPORTER_PORT",
                    "POSTGRES_EXPORTER_PORT", "WEBSERVER_APACHE_EXPORTER_PORT", "PROMETHEUS_PORT", "DATABASE_PORT",
                    "BANNER_SERVER_PORT", "CLICKHOUSE_HTTPS_PORT", "CLICKHOUSE_NATIVE_PORT", "PROXMOX_NODE_EXPORTER_PORT"
                ],
                "GRAFANA CONFIGURATION": [
                    "GRAFANA_USER","GRAFANA_PASSWORD",
                    "GRAFANA_PORT"
                ],
                "CLICKHOUSE CONFIGURATION": [
                    "CLICKHOUSE_USER", "CLICKHOUSE_PASSWORD"
                ],
                "DATABASE & AUTHENTICATION": [
                    "POSTGRES_EXPORTER_PASSWORD", "UBUNTU_BASE_SERVER_URL"
                ]
            }

            for section_name, section_vars in sections.items():
                f.write(f"\n# ===== {section_name} =====\n")
                for var_name in section_vars:
                    if var_name in env_vars:
                        value = env_vars[var_name].replace('"', '\\"')
                        f.write(f'{var_name}="{value}"\n')

        log_success(f"Created .env file at: {env_file_path}")
        log_info(f"Total variables written: {len(env_vars)}")
        return True

    except Exception as e:
        log_error(f"Failed to create .env file: {e}")
        return False


def append_to_env_file(env_vars: Dict[str, str], target_path: str) -> bool:
    """
    Append environment variables to an existing .env file, or create it if it doesn't exist.
    This function reads existing variables and only adds/updates the new ones.
    """
    try:
        env_file_path = environment_file("backend")

        # Create directory if it doesn't exist
        env_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing variables if file exists
        existing_vars = {}
        if env_file_path.exists():
            with open(env_file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key = line.split('=', 1)[0]
                        existing_vars[key] = True

        # Open file in append mode
        with open(env_file_path, 'a') as f:
            # Add a separator if file already exists and has content
            if env_file_path.stat().st_size > 0:
                f.write("\n# ===== APPENDED BY ORCHESTRATION SCRIPT =====\n")
                f.write(f"# Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            # Write only new variables
            new_count = 0
            for var_name, var_value in env_vars.items():
                if var_name not in existing_vars:
                    value = var_value.replace('"', '\\"')
                    f.write(f'{var_name}="{value}"\n')
                    new_count += 1
                    log_debug(f"Added new variable: {var_name}")
                else:
                    log_debug(f"Skipped existing variable: {var_name}")

        if new_count > 0:
            log_success(f"Appended {new_count} new variables to .env file at: {env_file_path}")
        else:
            log_info(f"No new variables to append (all already exist in {env_file_path})")
        return True

    except Exception as e:
        log_error(f"Failed to append to .env file: {e}")
        return False


def setup_environment() -> bool:
    """
    Extract environment variables and create .env file in MONITORING_FILES_DIR
    """
    log_section("Setting up Environment Variables")

    # Extract current environment variables
    env_vars = extract_env_variables()

    if not env_vars:
        log_error("No environment variables found to export")
        return False

    log_info(f"Extracted {len(env_vars)} environment variables")

    # Create .env file in MONITORING_FILES_DIR
    return create_env_file(env_vars, MONITORING_FILES_DIR)


def setup_grafana_environment() -> bool:
    """
    Extract Grafana-related environment variables and create .env file in GRAFANA_FILES_SETUP_DIR
    """
    log_section("Setting up Grafana Environment Variables")

    load_dotenv()  # Ensure we have all current env vars loaded
    grafana_env_vars = {}

    for var_name in GRAFANA_ENV_VARIABLES:
        value = os.getenv(var_name)
        if value is not None:
            grafana_env_vars[var_name] = value
            log_debug(f"Grafana setting available: {var_name}")
        else:
            log_warning(f"Grafana env var not set: {var_name}")

    if not grafana_env_vars:
        log_error("No Grafana environment variables found to export")
        return False

    grafana_files_setup_dir = os.getenv("GRAFANA_FILES_SETUP_DIR", "/root/heiST/heist/monitoring/grafana")
    return create_env_file(grafana_env_vars, grafana_files_setup_dir)


def setup_vector_environment() -> bool:
    """
    Extract Vector-related environment variables and create .env file in VECTOR_FILES_DIR
    """
    log_section("Setting up Vector Environment Variables")

    load_dotenv()  # Load all existing environment variables
    vector_env_vars = {}

    for var_name in VECTOR_ENV_VARIABLES:
        value = os.getenv(var_name)
        if value is not None:
            vector_env_vars[var_name] = value
            log_debug(f"Vector setting available: {var_name}")
        else:
            log_warning(f"Vector env var not set: {var_name}")

    if not vector_env_vars:
        log_error("No Vector environment variables found to export")
        return False

    vector_files_dir = os.getenv("VECTOR_FILES_DIR", "/root/heiST/heist/monitoring/vector")
    return create_env_file(vector_env_vars, vector_files_dir)


def setup_backend_environment() -> bool:
    """
    Extract Backend-related environment variables and APPEND to .env file in BACKEND_FILES_DIR
    """
    log_section("Setting up Backend Environment Variables (Append Mode)")

    load_dotenv()
    backend_env_vars = {}

    for var_name in BACKEND_ENV_VARIABLES:
        value = os.getenv(var_name)
        if value is not None:
            backend_env_vars[var_name] = value
            log_debug(f"Backend setting available: {var_name}")
        else:
            log_warning(f"Backend env var not set: {var_name}")

    if not backend_env_vars:
        log_error("No Backend environment variables found to export")
        return False

    backend_files_dir = os.getenv("BACKEND_FILES_DIR", "/root/heiST/heist/backend")
    return append_to_env_file(backend_env_vars, backend_files_dir)


# ===== SCRIPT VALIDATION =====

def validate_scripts() -> Tuple[bool, List[str]]:
    """
    Validate that all required scripts exist
    Returns: (all_valid, missing_scripts)
    """
    missing_scripts = []

    for script in SCRIPTS:
        script_path = Path(script["path"])
        if not script_path.exists():
            missing_scripts.append(script["path"])
            log_warning(f"Script not found: {script['path']}")
        else:
            log_debug(f"Script found: {script['path']}")

    return len(missing_scripts) == 0, missing_scripts


def get_script_command(script_path: str) -> List[str]:
    """
    Build the command to execute a script with appropriate flags, convert a path into a module execution to preserve structure
    """

    relative = Path(script_path).resolve().relative_to(Path(MONITORING_FILES_DIR).resolve())
    if relative.suffix != '.py' or not all(part.isidentifier() for part in relative.with_suffix('').parts):
        raise ValueError('Invalid monitoring module path')
    command = [sys.executable, '-m', 'heist.monitoring.' + '.'.join(relative.with_suffix('').parts)]

    if DEBUG_MODE:
        command.append("--debug")

    return command




# ===== SCRIPT EXECUTION =====

@time_function
def execute_script(script_info: dict) -> bool:
    """
    Execute a single script and return success status
    """
    name = script_info["name"]
    path = script_info["path"]
    description = script_info["description"]

    log_section(f"Executing: {name}")
    log_info(f"Description: {description}")
    log_info(f"Script: {path}")

    script_path = Path(path)
    if not script_path.exists():
        log_error(f"Script file not found: {path}")
        return False

    command = get_script_command(path)
    log_debug(f"Command: {' '.join(command)}")

    try:
        exit_code = run_cmd_with_realtime_output(command, check=False)

        if exit_code == 0:
            log_success(f"Completed: {name}")
            return True
        else:
            log_error(f"Failed with exit code {exit_code}: {name}")
            return False

    except Exception as e:
        log_error(f"Unexpected error executing {path}: {e}")
        return False


@time_function
def execute_all_scripts() -> bool:
    """
    Execute all scripts in sequence
    Returns: Overall success status
    """
    log_section("Starting Orchestration")
    log_info(f"Executing {len(SCRIPTS)} scripts")
    log_debug(f"Debug mode: {DEBUG_MODE}")

    # Setup environment
    if not (setup_environment() and setup_grafana_environment() and setup_vector_environment() and setup_backend_environment()):
        log_error("Failed to set up environment variables")
        return False

    # Validate scripts exist
    all_valid, missing = validate_scripts()
    if not all_valid:
        log_error(f"Missing scripts: {', '.join(missing)}")
        log_error("Please ensure all script files exist in the correct locations")
        log_error("Update the SCRIPTS configuration in this file with the correct paths")
        return False

    # Execute scripts sequentially
    success_count = 0
    failed_scripts = []

    for script in SCRIPTS:
        success = execute_script(script)
        if success:
            success_count += 1
        else:
            failed_scripts.append(script["name"])
        # Small pause between scripts
        time.sleep(1)

    # Summary
    log_section("Execution Summary")
    log_info(f"Successful: {success_count}/{len(SCRIPTS)}")

    if failed_scripts:
        log_error(f"Failed scripts: {', '.join(failed_scripts)}")
        return False
    else:
        log_success("All scripts completed successfully")
        return True


# ===== MAIN EXECUTION =====

@time_function
def main():
    """
    Main execution function
    """
    global DEBUG_MODE

    parser = argparse.ArgumentParser(
        description="Orchestration Script - Master script for configuration automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Run all scripts normally
  %(prog)s --debug           # Run with debug output
  %(prog)s --list-scripts    # List all configured scripts and exit
  %(prog)s --env-only        # Only create .env file and exit
        """
    )

    parser.add_argument(
        "-d", "--debug",
        action="store_true",
        help="Enable debug output for all scripts"
    )

    parser.add_argument(
        "-l", "--list-scripts",
        action="store_true",
        help="List all configured scripts and exit"
    )

    parser.add_argument(
        "-e", "--env-only",
        action="store_true",
        help="Only create .env file in MONITORING_FILES_DIR and exit"
    )

    args = parser.parse_args()

    DEBUG_MODE = args.debug

    if args.list_scripts:
        log_section("Configured Scripts")
        for i, script in enumerate(SCRIPTS, 1):
            print(f"{i}. {script['name']}")
            print(f"   Description: {script['description']}")
            print(f"   Path: {script['path']}")
            exists = "✓" if Path(script['path']).exists() else "✗"
            print(f"   Status: {exists} File exists")
            print()
        return

    if args.env_only:
        # Only create environment files and exit
        success_monitoring = setup_environment()
        success_grafana = setup_grafana_environment()
        success_vector = setup_vector_environment()
        success_backend = setup_backend_environment()
        sys.exit(0 if (success_monitoring and success_grafana and success_vector and success_backend) else 1)
    try:
        with Timer():
            success = execute_all_scripts()
        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        log_error("Execution interrupted by user")
        sys.exit(1)
    except Exception as e:
        log_error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()