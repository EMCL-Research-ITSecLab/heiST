"""
Suricata Local Logrotate Setup Script
Automates configuration of Suricata log and PCAP rotation on the local machine
"""

import os
import sys
import argparse
from pathlib import Path
from heist.environment import load_installer_env as load_dotenv
sys.stdout.reconfigure(line_buffering=True)

# Load environment variables
load_dotenv()
from heist.monitoring.utils.script_helper import (
    log_info, log_debug, log_error, log_warning, log_success, log_section,
    run_cmd, run_cmd_with_realtime_output, Timer, time_function, DEBUG_MODE
)

# ==== CONFIGURATION CONSTANTS ====
SURICATA_LOG_DIR = os.getenv("SURICATA_LOG_DIR", "/var/log/suricata")
PCAP_DIR = f"{SURICATA_LOG_DIR}/pcap"
ROTATE_DAYS = int(os.getenv("ROTATE_DAYS", 30))
LOGROTATE_CONFIG_DIR = os.getenv("LOGROTATE_CONFIG_DIR", "/etc/logrotate.d")
LOGROTATE_CONFIG_PATH = f"{LOGROTATE_CONFIG_DIR}/suricata"


@time_function
def ensure_directories():
    """
    Ensure Suricata log and PCAP directories exist
    """
    log_section("Creating Suricata directories")
    for d in [SURICATA_LOG_DIR, PCAP_DIR]:
        Path(d).mkdir(parents=True, exist_ok=True)
        run_cmd(["sudo", "chown", f"{os.getlogin()}:{os.getlogin()}", d])
        log_info(f"Directory ensured: {d}")


@time_function
def install_logrotate():
    """
    Install logrotate if missing
    """
    log_section("Checking logrotate installation")
    try:
        run_cmd(["logrotate", "--version"], check=True, capture_output=True)
        log_info("logrotate already installed")
    except Exception:
        log_info("Installing logrotate")
        run_cmd_with_realtime_output(["sudo", "apt", "update"])
        run_cmd_with_realtime_output(["sudo", "apt", "install", "-y", "logrotate"])
        log_success("logrotate installed successfully")


@time_function
def deploy_logrotate_config():
    """
    Deploy logrotate config for Suricata logs and PCAPs
    """
    log_section("Deploying logrotate configuration for Suricata")

    config_content = f"""
{SURICATA_LOG_DIR}/*.json {{
    daily
    size 5G
    rotate {ROTATE_DAYS}
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root root
    sharedscripts
    dateext
    dateformat -%Y-%m-%d-%s
    prerotate
        mkdir -p /var/log/suricata/rotated/daily
    endscript
    olddir /var/log/suricata/rotated/daily
    postrotate
        /bin/kill -HUP `cat /var/run/suricata-vpn.pid 2>/dev/null` 2>/dev/null || true
        /bin/kill -HUP `cat /var/run/suricata-dmz.pid 2>/dev/null` 2>/dev/null || true
        /bin/kill -HUP `cat /var/run/suricata-backend.pid 2>/dev/null` 2>/dev/null || true
        CURRENT_DATE=$(date +%Y-%m-%d)
        TARGET_DIR="/var/log/suricata/rotated/${{CURRENT_DATE}}"
        mkdir -p "$TARGET_DIR"
        find /var/log/suricata/rotated/daily -name "*-${{CURRENT_DATE}}-*.gz" -exec mv -t "$TARGET_DIR/" {{}} + 2>/dev/null || true
    endscript
}}

{SURICATA_LOG_DIR}/*.log {{
    daily
    size 2G
    rotate {ROTATE_DAYS}
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root root
    sharedscripts
    dateext
    dateformat -%Y-%m-%d-%s
    prerotate
        mkdir -p /var/log/suricata/rotated/daily
    endscript
    olddir /var/log/suricata/rotated/daily
    postrotate
        /bin/kill -HUP `cat /var/run/suricata-vpn.pid 2>/dev/null` 2>/dev/null || true
        /bin/kill -HUP `cat /var/run/suricata-dmz.pid 2>/dev/null` 2>/dev/null || true
        /bin/kill -HUP `cat /var/run/suricata-backend.pid 2>/dev/null` 2>/dev/null || true
        CURRENT_DATE=$(date +%Y-%m-%d)
        TARGET_DIR="/var/log/suricata/rotated/${{CURRENT_DATE}}"
        mkdir -p "$TARGET_DIR"
        find /var/log/suricata/rotated/daily -name "*-${{CURRENT_DATE}}-*.gz" -exec mv -t "$TARGET_DIR/" {{}} + 2>/dev/null || true
    endscript
}}
""".strip()

    tmp_path = "/tmp/suricata_logrotate"
    with open(tmp_path, "w") as f:
        f.write(config_content)

    run_cmd(["sudo", "mv", tmp_path, LOGROTATE_CONFIG_PATH])
    run_cmd(["sudo", "chmod", "644", LOGROTATE_CONFIG_PATH])
    log_success(f"Logrotate config deployed to {LOGROTATE_CONFIG_PATH}")


@time_function
def test_logrotate():
    """
    Test the logrotate configuration in debug mode
    """
    log_section("Testing logrotate configuration")
    run_cmd_with_realtime_output(["sudo", "mkdir", "-p", "/var/log/suricata/rotated/daily"])
    run_cmd_with_realtime_output(["sudo", "logrotate", "-d", LOGROTATE_CONFIG_PATH])
    log_success("Logrotate debug test completed")


@time_function
def main():
    """
    Main execution function
    """
    global DEBUG_MODE

    parser = argparse.ArgumentParser(description="Suricata Local Logrotate Setup Script")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug output")
    args = parser.parse_args()
    DEBUG_MODE = args.debug

    try:
        with Timer():
            log_section("Starting Suricata logrotate setup")

            ensure_directories()
            install_logrotate()
            deploy_logrotate_config()
            test_logrotate()

            log_success("Suricata logrotate setup completed successfully")

    except Exception as e:
        log_error(f"Setup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
