import base64
import logging
import socket
import time
from pathlib import Path

logging.getLogger("paramiko").setLevel(logging.CRITICAL)


def wait_for_ssh(port, host="127.0.0.1", timeout=3600, interval=10):
    """Wait for the forwarded TCP port."""
    print(f"Waiting for SSH on {host}:{port} (timeout {timeout}s)...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=5):
                print("SSH port is open")
                return True
        except OSError:
            time.sleep(interval)
    return False


def _get_paramiko():
    try:
        import paramiko
        return paramiko
    except ImportError:
        raise RuntimeError(
            "paramiko is required to drive guest setup over SSH. Install it with `pip install paramiko`."
        )


def _ps(command: str) -> str:
    """Build a powershell.exe command line using -EncodedCommand."""
    prefix = "$ProgressPreference='SilentlyContinue'; "
    enc = base64.b64encode((prefix + command).encode("utf-16-le")).decode("ascii")
    return f"powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -OutputFormat Text -EncodedCommand {enc}"


def ssh_connect(port, username, password, host="127.0.0.1", timeout=15):
    paramiko = _get_paramiko()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=username, password=password, timeout=timeout,
                   banner_timeout=30, auth_timeout=30, allow_agent=False, look_for_keys=False)
    return client


def ssh_run(port, command, username, password, timeout=120):
    """Run a PowerShell command over SSH and return (exit_status, stdout, stderr)."""
    client = ssh_connect(port, username=username, password=password)
    try:
        _, stdout, stderr = client.exec_command(_ps(command), timeout=timeout)
        exit_status = stdout.channel.recv_exit_status()
        out = stdout.read().decode(errors="ignore")
        err = stderr.read().decode(errors="ignore")
        return exit_status, out, err
    finally:
        client.close()


def ssh_run_expect_disconnect(port, command, username, password, max_wait=120):
    """Run a command that is expected to reboot the guest."""
    exit_status, out, err = None, "", ""
    try:
        client = ssh_connect(port, username=username, password=password)
        try:
            _, stdout, stderr = client.exec_command(_ps(command))
            chan = stdout.channel
            deadline = time.time() + max_wait
            while time.time() < deadline:
                if chan.exit_status_ready():
                    break
                transport = client.get_transport()
                if transport is None or not transport.is_active():
                    break
                time.sleep(1)
            if chan.exit_status_ready():
                exit_status = chan.recv_exit_status()
                try:
                    out = stdout.read().decode(errors="ignore")
                    err = stderr.read().decode(errors="ignore")
                except Exception:
                    pass
        finally:
            try:
                client.close()
            except Exception:
                pass
    except Exception as e:
        print(f"[Info] SSH session dropped while triggering reboot (expected): {e}")
    return exit_status, out, err


def get_boot_time(port, username, password):
    """Guest's LastBootUpTime as a string; changes after every reboot."""
    code, out, _ = ssh_run(
        port, "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('o')",
        username, password, timeout=20,
    )
    out = out.strip()
    return out if code == 0 and out else None


def reboot_and_wait(port, username, password, command, timeout=1800, disconnect_wait=120, interval=10):
    """Run `command`, then wait until the guest has rebooted (LastBootUpTime changed) and SSH logins work again."""
    before = None
    read_deadline = time.time() + 180
    while time.time() < read_deadline:
        try:
            before = get_boot_time(port, username, password)
            if before:
                break
        except Exception as e:
            print(f"Boot-time read not ready yet: {e}")
        time.sleep(5)
    if not before:
        raise RuntimeError("Could not read the guest's boot time before rebooting (SSH unavailable)")
    print(f"Boot time before reboot: {before}")

    status, out, err = ssh_run_expect_disconnect(port, command, username, password, max_wait=disconnect_wait)
    if out.strip():
        print(out.strip())
    if status not in (None, -1, 0):
        raise RuntimeError(f"Command failed (exit {status}) instead of rebooting:\n{err or out}")

    print("Waiting for the guest to actually reboot and SSH to come back...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            after = get_boot_time(port, username, password)
            if after and after != before:
                print(f"Guest rebooted (boot time now {after})")
                return True
        except Exception:
            pass
        time.sleep(interval)

    raise RuntimeError("Guest did not reboot (or SSH never came back) within the timeout")


def sftp_put(port, local_path: Path, remote_path: str, username, password):
    client = ssh_connect(port, username=username, password=password)
    try:
        sftp = client.open_sftp()
        try:
            sftp.put(str(local_path), remote_path)
        finally:
            sftp.close()
    finally:
        client.close()


def wait_for_setup_complete(port, username, password, timeout=1800, interval=15):
    """Poll the guest over SSH for the 'SETUP COMPLETE' marker in setup.log."""
    print("Polling setup.log over SSH for completion marker...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            exit_status, out, _ = ssh_run(
                port,
                'Get-Content C:\\Windows\\Temp\\setup.log -ErrorAction SilentlyContinue',
                username, password,
                timeout=20,
            )
            if "SETUP COMPLETE" in out:
                print("Setup script reported completion")
                return True
        except Exception as e:
            print(f"SSH check not ready yet: {e}")
        time.sleep(interval)

    print("WARNING: timed out waiting for SETUP COMPLETE marker")
    return False


def get_adapter_ip(port, ip_prefix, username, password, timeout=120, interval=5):
    """SSH in and ask the guest for its DHCP-assigned IPv4 matching ip_prefix."""
    print(f"Discovering guest IP matching {ip_prefix}* via SSH...")
    deadline = time.time() + timeout
    cmd = (
        f"(Get-NetIPAddress -AddressFamily IPv4 | "
        f"Where-Object {{ $_.IPAddress -like '{ip_prefix}*' }} | "
        f"Select-Object -First 1 -ExpandProperty IPAddress)"
    )
    while time.time() < deadline:
        try:
            exit_status, out, _ = ssh_run(port, cmd, username, password, timeout=20)
            ip = out.strip()
            if ip.startswith(ip_prefix):
                print(f"Discovered IP: {ip}")
                return ip
        except Exception as e:
            print(f"IP discovery not ready yet: {e}")
        time.sleep(interval)

    raise TimeoutError(f"Timed out discovering an IP matching {ip_prefix}*")