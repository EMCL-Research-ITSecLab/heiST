"""
Script Helper Module
Common utilities for professional script development including logging, command execution, and remote operations
"""

import os
import subprocess
import sys
import argparse
import time
from pathlib import Path
from typing import List, Optional, Tuple
import threading
sys.stdout.reconfigure(line_buffering=True)

# Global debug flag that can be set by scripts
DEBUG_MODE = False


# ===== LOGGING FUNCTIONS =====

def log_info(message: str):
    """Print informational messages"""
    print(f"INFO: {message}")


def log_debug(message: str):
    """Print debug messages only if debug mode is enabled"""
    if DEBUG_MODE:
        print(f"DEBUG: {message}")


def log_error(message: str):
    """Print error messages"""
    print(f"ERROR: {message}")


def log_warning(message: str):
    """Print warning messages"""
    print(f"WARNING: {message}")


def log_success(message: str):
    """Print success messages"""
    print(f"SUCCESS: {message}")


def log_section(title: str):
    """Print section headers"""
    print(f"\n{'=' * 60}")
    print(f"{title.upper()}")
    print(f"{'=' * 60}")


# ===== COMMAND EXECUTION FUNCTIONS =====

def run_cmd(command: List[str], check: bool = True, capture_output: bool = False,
            timeout: Optional[int] = None, shell: bool = False) -> subprocess.CompletedProcess:
    """
    Execute a local command with proper error handling and logging

    Args:
        command: Command and arguments as list
        check: Whether to raise exception on non-zero exit code
        capture_output: Whether to capture and return output
        timeout: Command timeout in seconds

    Returns:
        CompletedProcess object
    """
    log_debug(f"Executing local command: {' '.join(command)}")

    try:
        result = subprocess.run(
            command,
            check=check,
            capture_output=capture_output,
            text=True,
            timeout=timeout,
            shell=shell,
        )

        if result.returncode == 0:
            log_debug(f"Command completed successfully: {' '.join(command)}")
        else:
            log_warning(f"Command completed with exit code {result.returncode}: {' '.join(command)}")

        return result

    except subprocess.CalledProcessError as e:
        log_error(f"Command failed with exit code {e.returncode}: {' '.join(command)}")
        if e.stderr:
            log_error(f"Error output: {e.stderr.strip()}")
        raise
    except subprocess.TimeoutExpired:
        log_error(f"Command timed out: {' '.join(command)}")
        raise
    except FileNotFoundError:
        log_error(f"Command not found: {command[0]}")
        raise


def execute_remote_command(ip: str, command: str, user: str = "ubuntu",
                           password: Optional[str] = None, timeout: int = 300) -> None:
    """
    Execute a remote command via SSH with real-time output

    Args:
        ip: Remote host IP address
        command: Command to execute
        user: SSH username
        password: SSH password (if None, uses key-based auth)
        timeout: Command timeout in seconds
    """
    log_debug(f"Executing remote command on {ip}: {command}")

    ssh_command = [
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=15",
        f"{user}@{ip}", command
    ]

    # Use sshpass if password is provided
    if password:
        ssh_command = ["sshpass", "-p", password] + ssh_command

    try:
        process = subprocess.Popen(
            ssh_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        # Print output in real-time
        for line in process.stdout:
            line = line.strip()
            if line:
                log_debug(f"[{ip}] {line}")

        # Wait for completion
        return_code = process.wait(timeout=timeout)

        if return_code == 0:
            log_debug(f"Remote command completed successfully on {ip}")
        else:
            # Read stderr for error details
            stderr = process.stderr.read()
            if stderr:
                log_error(f"Remote command stderr on {ip}: {stderr.strip()}")
            raise Exception(f"Remote command failed with return code {return_code} on {ip}")

    except subprocess.TimeoutExpired:
        log_error(f"Remote command timed out on {ip}: {command}")
        raise
    except Exception as e:
        log_error(f"Remote command failed on {ip}: {str(e)}")
        raise


def execute_remote_command_with_key(ip: str, command: str, user: str = "ubuntu",
                                    ssh_key_path: Optional[str] = None, timeout: int = 300, shell: bool = False) -> str:
    """
    Execute remote command via SSH key authentication with real-time output,
    safely reading stdout and stderr concurrently and handling timeouts.
    """
    if ssh_key_path is None:
        ssh_key_path = "/root/.ssh/id_rsa"

    if shell:
        ssh_command = f"ssh -o StrictHostKeyChecking=no -o PasswordAuthentication=no -o ConnectTimeout=15 -i {ssh_key_path} {user}@{ip} 'bash -c \"{command}\"'"
    else:
        ssh_command = [
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "PasswordAuthentication=no",
            "-o", "ConnectTimeout=15",
            "-i", ssh_key_path,
            f"{user}@{ip}",
            command
        ]

    process = subprocess.Popen(
        ssh_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        shell=shell
    )

    output_lines = []
    error_lines = []

    def read_stream(stream, lines_list, log_prefix=""):
        for line in iter(stream.readline, ""):
            line = line.rstrip("\n")
            if line:
                log_debug(f"{log_prefix}{line}")
                lines_list.append(line)
        stream.close()

    # Start threads to read stdout and stderr concurrently
    stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, output_lines, f"[{ip}] "))
    stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, error_lines, f"[{ip}][ERR] "))

    stdout_thread.start()
    stderr_thread.start()

    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()  # Ensure process is terminated
        stdout_thread.join()
        stderr_thread.join()
        raise Exception(f"Remote command timed out on {ip}: {command}")

    # Ensure threads finished reading all remaining output
    stdout_thread.join()
    stderr_thread.join()

    if return_code != 0:
        raise Exception(f"Remote command failed ({return_code}) on {ip}:\n" + "\n".join(error_lines))

    log_debug(f"Remote command completed successfully on {ip}")
    return "\n".join(output_lines)


def scp_file(local_path: str, remote_path: str, ip: str, user: str = "ubuntu",
             password: Optional[str] = None, timeout: int = 120) -> None:
    """
    Copy a file to a remote server using SCP

    Args:
        local_path: Local file path to copy
        remote_path: Remote destination path
        ip: Remote host IP address
        user: SSH username
        password: SSH password (if None, uses key-based auth)
        timeout: Command timeout in seconds
    """
    log_info(f"Copying {local_path} to {user}@{ip}:{remote_path}")

    scp_command = [
        "scp", "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=15",
        local_path,
        f"{user}@{ip}:{remote_path}"
    ]

    # Use sshpass if password is provided
    if password:
        scp_command = ["sshpass", "-p", password] + scp_command

    try:
        result = run_cmd(
            scp_command,
            check=True,
            capture_output=False,
            timeout=timeout
        )
        log_debug(f"File copied successfully: {local_path} -> {remote_path}")

    except subprocess.CalledProcessError as e:
        log_error(f"SCP failed with exit code {e.returncode}: {local_path} -> {remote_path}")
        raise
    except Exception as e:
        log_error(f"SCP failed: {str(e)}")
        raise


def scp_directory(local_path: str, remote_path: str, ip: str, user: str = "ubuntu",
                  password: Optional[str] = None, timeout: int = 300) -> None:
    """
    Copy a directory recursively to remote server using SCP

    Args:
        local_path: Local directory path to copy
        remote_path: Remote destination path
        ip: Remote host IP address
        user: SSH username
        password: SSH password (if None, uses key-based auth)
        timeout: Command timeout in seconds
    """
    log_info(f"Copying directory {local_path} to {user}@{ip}:{remote_path}")

    scp_command = [
        "scp", "-r", "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=15",
        local_path,
        f"{user}@{ip}:{remote_path}"
    ]

    # Use sshpass if password is provided
    if password:
        scp_command = ["sshpass", "-p", password] + scp_command

    try:
        result = run_cmd(
            scp_command,
            check=True,
            capture_output=False,
            timeout=timeout
        )
        log_debug(f"Directory copied successfully: {local_path} -> {remote_path}")

    except subprocess.CalledProcessError as e:
        log_error(f"SCP directory failed with exit code {e.returncode}: {local_path} -> {remote_path}")
        raise
    except Exception as e:
        log_error(f"SCP directory failed: {str(e)}")
        raise


def run_cmd_with_realtime_output(command: List[str], check: bool = True,
                                 timeout: Optional[int] = None,
                                 env: Optional[dict] = None, shell=False) -> int:
    """
    Execute a command with real-time output display

    Args:
        command: Command and arguments as list
        check: Whether to raise exception on non-zero exit code
        timeout: Command timeout in seconds

    Returns:
        Exit code
    """

    log_debug(f"Executing command with real-time output: {' '.join(command)}")

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            shell=shell
        )

        # Print output in real-time
        for line in process.stdout:
            line = line.strip()
            if line:
                print(f"  {line}")

        # Wait for completion
        return_code = process.wait(timeout=timeout)

        if return_code == 0:
            log_debug("Command completed successfully")
        else:
            log_warning(f"Command completed with exit code {return_code}")
            if check:
                raise subprocess.CalledProcessError(return_code, command)

        return return_code

    except subprocess.TimeoutExpired:
        log_error(f"Command timed out: {' '.join(command)}")
        raise
    except Exception as e:
        log_error(f"Command execution failed: {str(e)}")
        raise


def remote_setup_user_ssh_keys(
    ip: str,
    username: str,
    keyfile: str,
    old_password: str,
    new_password: str,
    admin_user: str = "ubuntu"
) -> None:
    """
    Configure SSH key-based authentication for a remote user.

    This function performs the following steps:
        1. Creates the .ssh directory for the specified user (if not present)
        2. Copies the provided public key to authorized_keys
        3. Sets correct file permissions for SSH
        4. Updates the user's password

    Args:
        ip: Remote host IP address
        username: Remote username to configure
        keyfile: Path to local SSH public key file
        old_password: Current password for the target user (used for authentication)
        new_password: New password to set for the target user
        admin_user: Administrative user for SSH connection (default: ubuntu)

    Raises:
        Exception: If any remote operation fails
    """
    log_section(f"Setting up SSH keys for {username}@{ip}")

    try:
        # Ensure .ssh directory exists
        log_info(f"Creating .ssh directory for user '{username}' on {ip}")
        execute_remote_command(
            ip,
            f"sudo -u {username} mkdir -p /home/{username}/.ssh",
            user=admin_user,
            password=old_password
        )

        # Copy SSH public key to remote authorized_keys
        log_info(f"Copying SSH key to {username}@{ip}")
        remote_path = f"/home/{username}/.ssh/authorized_keys"
        scp_file(
            local_path=keyfile,
            remote_path=remote_path,
            ip=ip,
            user=admin_user,
            password=old_password
        )

        # Fix file permissions
        log_info(f"Setting correct permissions for {username}'s SSH directory")
        execute_remote_command(
            ip,
            f"sudo chmod 700 /home/{username}/.ssh && sudo chmod 600 /home/{username}/.ssh/authorized_keys && sudo chown -R {username}:{username} /home/{username}/.ssh",
            user=admin_user,
            password=old_password
        )

        # Change user password
        log_info(f"Updating password for user '{username}' on {ip}")
        execute_remote_command(
            ip,
            f"echo '{username}:{new_password}' | sudo chpasswd",
            user=admin_user,
            password=old_password
        )

        log_success(f"SSH key setup completed successfully for {username}@{ip}")

        # Setup up key-based authentication for root user as well
        log_info(f"Setting up SSH keys for root user on {ip}")
        execute_remote_command(
            ip,
            f"sudo mkdir -p /root/.ssh && sudo cp /home/{username}/.ssh/authorized_keys /root/.ssh/authorized_keys && sudo chmod 700 /root/.ssh && sudo chmod 600 /root/.ssh/authorized_keys && sudo chown -R root:root /root/.ssh",
            user=admin_user,
            password=old_password
        )

    except Exception as e:
        log_error(f"Failed to set up SSH keys for {username}@{ip}: {str(e)}")
        raise


# ===== TIMING FUNCTIONS =====

class Timer:
    """Context manager for timing code execution"""

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *args):
        self.end = time.time()
        self.duration = self.end - self.start
        log_debug(f"Operation completed in {self.duration:.2f}s")


def time_function(func):
    """Decorator to time function execution"""

    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        duration = time.time() - start
        log_debug(f"Function {func.__name__} executed in {duration:.2f}s")
        return result

    return wrapper