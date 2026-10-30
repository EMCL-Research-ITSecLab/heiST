"""
Wazuh Setup Script
Automates deployment and configuration of Wazuh manager and banner service
"""

import os
import sys
import shlex
import argparse
import time
from heist.environment import load_installer_env as load_dotenv
sys.stdout.reconfigure(line_buffering=True)

# Load environment variables
load_dotenv()
from heist.monitoring.utils.script_helper import (
    log_info, log_debug, log_error, log_warning, log_success, log_section,
    execute_remote_command, execute_remote_command_with_key, scp_file, scp_directory, Timer, time_function, DEBUG_MODE
)

# ==== CONFIGURATION CONSTANTS ====
MONITORING_IP = os.getenv("MONITORING_HOST", "10.0.0.103")
SSH_USER = os.getenv("MONITORING_VM_USER", "ubuntu")
NEW_SSH_PASSWORD = os.getenv("MONITORING_VM_PASSWORD", "meow1234")
WAZUH_FILE_DIR = os.getenv("WAZUH_FILE_DIR", "/root/heiST/heist/monitoring/wazuh")
WAZUH_MANAGER_DIRECTORY = f"{WAZUH_FILE_DIR}/manager"
BANNER_SERVER = f"{WAZUH_FILE_DIR}/banner/banner_server.py"
PROXMOX_SSH_KEYFILE = os.getenv("PROXMOX_SSH_KEYFILE", "/root/.ssh/id_rsa.pub")

# Wazuh API credentials
WAZUH_API_USER = os.getenv("WAZUH_API_USER", "wazuh-wui")
WAZUH_API_PASS = os.getenv("WAZUH_API_PASSWORD", "MyS3cr37P450r.*-")
WAZUH_DASHBOARD_USER = os.getenv("WAZUH_DASHBOARD_USER", "kibanaserver")
WAZUH_DASHBOARD_PASS = os.getenv("WAZUH_DASHBOARD_PASSWORD", "kibanaserver")
WAZUH_INDEXER_USER = os.getenv("WAZUH_INDEXER_USER", "admin")
WAZUH_INDEXER_PASS = os.getenv("WAZUH_INDEXER_PASSWORD", "SecretPassword")
WAZUH_REGISTRATION_PORT = os.getenv("WAZUH_REGISTRATION_PORT", "1515")
WAZUH_COMMUNICATION_PORT = os.getenv("WAZUH_COMMUNICATION_PORT", "1514")
WAZUH_API_PORT = os.getenv("WAZUH_API_PORT", "55000")
WAZUH_ENROLLMENT_PASSWORD = os.getenv("WAZUH_ENROLLMENT_PASSWORD", "")


@time_function
def setup_wazuh_manager():
    """
    Deploy and configure Wazuh manager with Docker
    """
    log_section("Setting up Wazuh Manager")

    # Copy manager files to remote host
    scp_directory(WAZUH_MANAGER_DIRECTORY, "/tmp", MONITORING_IP, SSH_USER, NEW_SSH_PASSWORD)

    # Execute setup commands
    commands = [
        "sudo mkdir -p /var/lib/wazuh",
        "sudo mv /tmp/manager /var/lib/wazuh/manager",
        "sudo chmod +x /var/lib/wazuh/manager/set_up_manager.sh",
        "sudo chmod +x /var/lib/wazuh/manager/utils/install_docker.sh",
    ]

    for cmd in commands:
        execute_remote_command_with_key(
            MONITORING_IP,
            cmd,
            SSH_USER,
            ssh_key_path=PROXMOX_SSH_KEYFILE,
            shell=True,
            timeout=1800
        )

    # Docker installation with retry logic
    log_info("Installing Docker")
    docker_install_successful = False
    max_retries = 3

    for attempt in range(max_retries):
        try:
            log_info(f"Docker installation attempt {attempt + 1}/{max_retries}")
            result = execute_remote_command_with_key(
                MONITORING_IP,
                "sudo /var/lib/wazuh/manager/utils/install_docker.sh",
                SSH_USER,
                ssh_key_path=PROXMOX_SSH_KEYFILE,
                shell=True,
                timeout=600
            )
            log_debug(f"Docker installation script output: {result}")
            docker_install_successful = True
            log_success("Docker installed successfully")
            break
        except Exception as e:
            log_warning(f"Docker installation attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                log_info("Waiting 15 seconds before retry...")
                time.sleep(15)
            else:
                log_error("Docker installation failed after all retries")
                raise

    if not docker_install_successful:
        log_error("Docker installation did not complete successfully")
        raise Exception("Docker installation failed")

    # Wait for Docker daemon to be fully ready with multiple verification attempts
    log_info("Waiting for Docker daemon to start...")
    time.sleep(20)

    # Verify Docker is running with retries
    docker_verification_successful = False
    verify_attempts = 5
    for verify_attempt in range(verify_attempts):
        try:
            log_info(f"Verifying Docker installation (attempt {verify_attempt + 1}/{verify_attempts})...")
            output = execute_remote_command_with_key(
                MONITORING_IP,
                "sudo docker ps",
                SSH_USER,
                ssh_key_path=PROXMOX_SSH_KEYFILE,
                shell=True,
                timeout=30
            )
            log_debug(f"Docker ps output: {output}")
            log_success("Docker daemon is running and responding")
            docker_verification_successful = True
            break
        except Exception as e:
            log_warning(f"Docker verification attempt {verify_attempt + 1} failed: {str(e)}")
            if verify_attempt < verify_attempts - 1:
                log_info("Waiting 10 seconds before next verification attempt...")
                time.sleep(10)
            else:
                log_error("Docker verification failed after all attempts")
                # Try to get more diagnostic information
                try:
                    log_info("Attempting to get Docker service status...")
                    status_output = execute_remote_command_with_key(
                        MONITORING_IP,
                        "sudo systemctl status docker",
                        SSH_USER,
                        ssh_key_path=PROXMOX_SSH_KEYFILE,
                        shell=True,
                        timeout=30
                    )
                    log_debug(f"Docker service status: {status_output}")
                except Exception as status_e:
                    log_warning(f"Could not retrieve Docker status: {str(status_e)}")
                raise

    if not docker_verification_successful:
        log_error("Docker could not be verified as running")
        raise Exception("Docker verification failed")

    # Run Wazuh setup script
    log_section("Running Wazuh Setup Script")
    wazuh_setup_cmd = " ".join([
        "sudo", "/var/lib/wazuh/manager/set_up_manager.sh",
        "--api-user", shlex.quote(WAZUH_API_USER),
        "--api-pass", shlex.quote(WAZUH_API_PASS),
        "--dashboard-user", shlex.quote(WAZUH_DASHBOARD_USER),
        "--dashboard-pass", shlex.quote(WAZUH_DASHBOARD_PASS),
        "--indexer-user", shlex.quote(WAZUH_INDEXER_USER),
        "--indexer-pass", shlex.quote(WAZUH_INDEXER_PASS),
        "--enrollment-pass", shlex.quote(WAZUH_ENROLLMENT_PASSWORD)
    ])

    execute_remote_command_with_key(
        MONITORING_IP,
        wazuh_setup_cmd,
        SSH_USER,
        ssh_key_path=PROXMOX_SSH_KEYFILE,
        shell=True,
        timeout=1800
    )

    # Configure firewall rules
    firewall_commands = [
        f"sudo ufw allow {WAZUH_REGISTRATION_PORT}/tcp",
        f"sudo ufw allow {WAZUH_COMMUNICATION_PORT}/tcp",
        f"sudo ufw allow {WAZUH_API_PORT}/tcp"
    ]

    for cmd in firewall_commands:
        execute_remote_command_with_key(
            MONITORING_IP,
            cmd,
            SSH_USER,
            ssh_key_path=PROXMOX_SSH_KEYFILE,
            shell=True,
            timeout=60
        )

    log_success("Wazuh manager setup completed")


@time_function
def setup_banner_service():
    """
    Deploy and configure banner service
    """
    log_section("Setting up Banner Service")

    # Copy banner script to remote host
    scp_file(BANNER_SERVER, "/tmp/banner_server.py", MONITORING_IP, SSH_USER, NEW_SSH_PASSWORD)

    # Execute setup commands
    commands = [
        "sudo mkdir -p /var/lib/wazuh/banner",
        "sudo mv /tmp/banner_server.py /var/lib/wazuh/banner/banner_server.py",
        "sudo chmod +x /var/lib/wazuh/banner/banner_server.py",
    ]

    for cmd in commands:
        execute_remote_command_with_key(MONITORING_IP, cmd, SSH_USER, ssh_key_path=PROXMOX_SSH_KEYFILE)

    log_success("Banner service setup completed")


@time_function
def main():
    """
    Main execution function
    """
    global DEBUG_MODE

    parser = argparse.ArgumentParser(description="Wazuh Setup Script")
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Enable debug output")
    args = parser.parse_args()

    DEBUG_MODE = args.debug

    try:
        with Timer():
            log_section("Starting Wazuh Deployment")

            setup_wazuh_manager()
            setup_banner_service()

            log_success("Wazuh deployment completed successfully")

    except Exception as e:
        log_error(f"Deployment failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()