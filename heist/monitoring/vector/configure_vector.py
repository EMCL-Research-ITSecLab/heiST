"""
Vector Configuration Script
Updates CA certificate paths in Vector configuration files
"""

import os
import re
import sys
import argparse
from pathlib import Path
from heist.environment import load_installer_env as load_dotenv
sys.stdout.reconfigure(line_buffering=True)

# Load environment variables
load_dotenv()
from heist.monitoring.utils.script_helper import (
    log_info, log_debug, log_error, log_warning, log_success, log_section, execute_remote_command_with_key,
    Timer, time_function, DEBUG_MODE
)

# ==== CONFIGURATION CONSTANTS ====
VECTOR_DIR = os.getenv("VECTOR_DIR", "/root/heiST/heist/monitoring/vector")
CONFIG_DIR = f"{VECTOR_DIR}/config"

SSL_TLS_CERTS_DIR = os.getenv("SSL_TLS_CERTS_DIR", "/root/heiST/heist/installer/certs")
CA_FILE = f"{SSL_TLS_CERTS_DIR}/fullchain.pem"

CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "changeme")

CONFIG_EXTENSIONS = {".toml"}
CA_FILE_PATTERN = re.compile(r'^(ca_file\s*=\s*").*(")$')
USERNAME_PATTERN = re.compile(r'^(username\s*=\s*").*(")$')
PASSWORD_PATTERN = re.compile(r'^(password\s*=\s*").*(")$')


def validate_ca_file(ca_path):
    """
    Validate that the CA file exists and is readable

    Returns:
        bool: True if valid, False otherwise
    """
    ca_file = Path(ca_path)

    if not ca_file.exists():
        log_error(f"CA file does not exist: {ca_path}")
        return False

    if not ca_file.is_file():
        log_error(f"CA path is not a file: {ca_path}")
        return False

    try:
        with open(ca_file, 'r', encoding='utf-8') as f:
            content = f.read(100)
            if "BEGIN CERTIFICATE" not in content:
                log_warning(f"CA file may not be a valid certificate: {ca_path}")
    except (IOError, UnicodeDecodeError) as e:
        log_error(f"Unable to read CA file {ca_path}: {e}")
        return False

    return True


@time_function
def update_config_file(file_path, ca_path, username, password):
    """
    Updates the ca_file path, ClickHouse username and password in the given configuration file.

    Args:
        file_path: Path to the configuration file
        ca_path: New CA file path to set
        username: ClickHouse username
        password: ClickHouse password

    Returns:
        bool: True if the file was modified, False otherwise
    """
    log_debug(f"Processing file: {file_path}")

    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
    except IOError as e:
        log_error(f"Failed to read file {file_path}: {e}")
        return False

    modified = False
    new_lines = []

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        if CA_FILE_PATTERN.match(stripped):
            new_line = f'ca_file = "{ca_path}"\n'
            new_lines.append(new_line)
            modified = True
            log_debug(f"Updated line {line_num} (CA): {stripped} -> {new_line.strip()}")
        elif USERNAME_PATTERN.match(stripped):
            new_line = f'username = "{username}"\n'
            new_lines.append(new_line)
            modified = True
            log_debug(f"Updated line {line_num} (user): {stripped} -> {new_line.strip()}")
        elif PASSWORD_PATTERN.match(stripped):
            new_line = f'password = "{password}"\n'
            new_lines.append(new_line)
            modified = True
            log_debug(f"Updated line {line_num} (pass): {stripped} -> {new_line.strip()}")
        else:
            new_lines.append(line)

    if modified:
        backup_path = file_path.with_suffix(file_path.suffix + ".bak")
        try:
            with open(backup_path, 'w', encoding='utf-8') as backup_file:
                backup_file.writelines(lines)
            with open(file_path, 'w', encoding='utf-8') as file:
                file.writelines(new_lines)
            log_debug(f"Created backup: {backup_path}")
        except IOError as e:
            log_error(f"Failed to write file {file_path}: {e}")
            return False

    return modified


@time_function
def process_directory(config_dir, ca_path):
    """
    Iterates through all supported configuration files and updates them.

    Args:
        config_dir: Directory containing configuration files
        ca_path: CA file path to set in configurations
    """
    config_path = Path(config_dir)

    if not config_path.exists():
        log_error(f"Configuration directory not found: {config_dir}")
        return

    if not config_path.is_dir():
        log_error(f"Configuration path is not a directory: {config_dir}")
        return

    log_section("Updating Vector Configuration Files")
    log_info(f"Configuration directory: {config_dir}")
    log_info(f"Using CA file path: {ca_path}")

    if not validate_ca_file(ca_path):
        log_warning("CA file validation failed, but continuing with update")

    updated_files = 0
    total_files = 0
    error_files = 0

    try:
        for file_path in config_path.rglob("*"):
            if file_path.is_file() and file_path.suffix in CONFIG_EXTENSIONS:
                total_files += 1
                try:
                    if update_config_file(file_path, ca_path, CLICKHOUSE_USER, CLICKHOUSE_PASSWORD):
                        updated_files += 1
                        if not DEBUG_MODE:
                            log_info(f"Updated: {file_path}")
                    else:
                        log_debug(f"No change needed: {file_path}")
                except Exception as e:
                    error_files += 1
                    log_error(f"Failed to process {file_path}: {e}")
    except Exception as e:
        log_error(f"Error scanning directory {config_dir}: {e}")
        return

    # Print summary
    log_section("Processing Summary")
    if updated_files > 0:
        log_success(f"Updated {updated_files} of {total_files} files")
    else:
        log_info(f"No updates needed: {total_files} files processed")

    if error_files > 0:
        log_warning(f"{error_files} files had errors during processing")


@time_function
def main():
    """Main execution function"""
    global DEBUG_MODE

    parser = argparse.ArgumentParser(
        description="Update CA certificate paths in Vector configuration files"
    )
    parser.add_argument(
        "-d", "--debug",
        action="store_true",
        help="Enable debug mode for detailed output"
    )

    args = parser.parse_args()

    DEBUG_MODE = args.debug

    try:
        with Timer():
            log_section("Starting Vector Configuration Update")
            process_directory(CONFIG_DIR, CA_FILE)
            log_success("Vector configuration update completed")

    except Exception as e:
        log_error(f"Vector configuration update failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()