#!/usr/bin/env python3
"""Interactive onboarding wizard for heiST setup.

This script guides a user through the required configuration values,
writes a merged ``.env`` file into ``setup/``, and can optionally launch
existing setup scripts after saving the configuration.
"""

from __future__ import annotations
import argparse
import ipaddress
import os
import secrets
import shlex
import shutil
import string
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
import re

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
REQUIREMENTS_PATH = SCRIPT_DIR / "requirements.txt"
ENV_FILE_PATH = SCRIPT_DIR / ".env"
CREDENTIALS_MD_PATH = SCRIPT_DIR / "credentials.md"
BOOTSTRAP_SENTINEL_ENV = "HEIST_TUI_BOOTSTRAPPED"


def _run_bootstrap_command(command: list[str], description) -> None:
    print(f"[bootstrap] {description}...", flush=True)
    out = subprocess.run(command, capture_output=True)

    if not out.returncode == 0:
        raise subprocess.CalledProcessError(out.returncode, command, output=out.stdout, stderr=out.stderr)


def _with_optional_sudo(command: list[str]) -> list[str]:
    if os.name == "nt":
        return command
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return command
    if shutil.which("sudo"):
        return ["sudo", *command]
    return command


def _parse_debian_version_full() -> Optional[str]:
    os_release = Path("/etc/os-release")
    if not os_release.exists():
        return None

    for line in os_release.read_text(encoding="utf-8").splitlines():
        if line.startswith("DEBIAN_VERSION_FULL="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def _version_ge(left: str, right: str) -> bool:
    def normalize(value: str) -> tuple[int, ...]:
        parts = []
        for piece in value.split("."):
            digits = "".join(ch for ch in piece if ch.isdigit())
            parts.append(int(digits or "0"))
        return tuple(parts)

    return normalize(left) >= normalize(right)


def install_system_dependencies() -> None:
    if os.name == "nt":
        print("[bootstrap] Skipping apt-based system dependency installation on Windows.", flush=True)
        return

    if not shutil.which("apt"):
        print("[bootstrap] `apt` not found; skipping OS package installation.", flush=True)
        return

    debian_version = _parse_debian_version_full()
    ntp_package = "ntpsec-ntpdate" if debian_version and _version_ge(debian_version, "13.0") else "ntpdate"

    # Disable enterprise proxmox and ceph repositories to prevent apt update failures
    for repo_file in ["/etc/apt/sources.list.d/pve-enterprise.sources", "/etc/apt/sources.list.d/ceph.sources"]:
        # Replace Enabled: true with Enabled: false, or append Enabled: false if not present
        cmd = (
            f"[ -f {repo_file} ] && "
            f"(grep -q '^Enabled:' {repo_file} && sed -i 's/^Enabled: true$/Enabled: false/' {repo_file} || "
            f"echo 'Enabled: false' >> {repo_file}) || true"
        )
        _run_bootstrap_command(_with_optional_sudo(["bash", "-c", cmd]), description=f"Disabling {repo_file} if it exists")

    _run_bootstrap_command(_with_optional_sudo(["apt", "update"]), description="Updating `apt` packages")
    _run_bootstrap_command(_with_optional_sudo(["apt", "install", "-y", ntp_package]), description="Installing `ntpdate` packages")

    if shutil.which("ntpdate"):
        _run_bootstrap_command(_with_optional_sudo(["ntpdate", "time.google.com"]), description="Synchronizing system time")
    else:
        print("[bootstrap] `ntpdate` command not found after package install; skipping time sync.", flush=True)

    _run_bootstrap_command(
        _with_optional_sudo(
            [
                "apt",
                "install",
                "-y",
                "python3",
                "python3-pip"
            ]
        ), description="Installing dependencies available on `apt`"
    )


def install_python_dependencies() -> None:
    command = [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_PATH)]
    _run_bootstrap_command(command, description="Installing dependencies with `pip`")


def _is_running_in_venv() -> bool:
    return getattr(sys, "prefix", None) != getattr(sys, "base_prefix", None)


def _venv_python_path() -> Path:
    if os.name == "nt":
        return PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    return PROJECT_ROOT / ".venv" / "bin" / "python"


def _check_python_version() -> bool:
    major, minor = sys.version_info[:2]
    return (major, minor) == (3, 12)

def _install_python_version_312_and_create_venv() -> None:
    installation_script_path = SCRIPT_DIR / "install_python_3_12.sh"

    with open(installation_script_path, "w") as f:
        f.write(f"""#!/usr/bin/env bash
set -euo pipefail

PYTHON_VERSION="3.12.2"
VENV_DIR="{PROJECT_ROOT}/.venv"

echo "[1/6] Installing system dependencies..."
apt update
apt install -y \
  build-essential curl git \
  libssl-dev zlib1g-dev libbz2-dev libreadline-dev \
  libsqlite3-dev libffi-dev liblzma-dev tk-dev \
  libncursesw5-dev libgdbm-dev libnss3-dev libexpat1-dev

echo "[2/6] Installing pyenv..."
if [ ! -d "$HOME/.pyenv" ]; then
  curl https://pyenv.run | bash
fi

echo "[3/6] Configuring shell environment..."

# Add only if not already present
grep -q 'PYENV_ROOT' ~/.bashrc || cat >> ~/.bashrc <<'EOF'

# pyenv setup
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
EOF

# Load for current session
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"

echo "[4/6] Installing Python $PYTHON_VERSION..."
pyenv install -s "$PYTHON_VERSION"

echo "[5/6] Creating virtual environment..."
pyenv shell "$PYTHON_VERSION"
python -m venv "$VENV_DIR"

echo "[6/6] Done."
echo "Activate with:"
echo "  source $VENV_DIR/bin/activate"
echo "Python version:"
"$VENV_DIR/bin/python" --version""")

    installation_script_path.chmod(0o755)

    _run_bootstrap_command(
        [str(installation_script_path)],
        description="Installing Python 3.12 using pyenv (this may take a few minutes)"
    )


def _bootstrap_into_project_venv() -> None:
    """
    Bootstraps into the project virtual environment, creating it and installing dependencies if necessary.
    Always uses python version 3.12, since this is the verified version where everything is compatible. If the current Python
    version is different, version 3.12 will be installed for this purpose.
    :return:
    """

    venv_python = _venv_python_path()
    venv_dir = venv_python.parent.parent

    if not _check_python_version():
        _install_python_version_312_and_create_venv()

    elif not venv_python.exists():
        _run_bootstrap_command(
            [sys.executable, "-m", "venv", str(venv_dir)],
            description=f"Creating virtual environment at {venv_dir}",
        )

    _run_bootstrap_command(
        [str(venv_python), "-m", "pip", "install", "-r", str(REQUIREMENTS_PATH)],
        description="Installing dependencies into the virtual environment",
    )

    env = os.environ.copy()
    env[BOOTSTRAP_SENTINEL_ENV] = "1"
    os.execvpe(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]], env)


def bootstrap_requirements() -> None:
    try:
        if _is_running_in_venv():
            install_python_dependencies()
            return

        if os.environ.get(BOOTSTRAP_SENTINEL_ENV) != "1":
            install_system_dependencies()

        _bootstrap_into_project_venv()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Failed to install installer requirements (exit code {exc.returncode}).") from exc


BIN_DIR = PROJECT_ROOT / 'bin'
MAIN_RE = re.compile(r"if\s+__name__\s*==\s*['\"]__main__['\"]")


def _find_module_name_for_path(path: Path, root: Path):
    # Build a dotted module name for a .py file inside the project rooted at `root`.
    # Stop walking up when we reach the repository root so the top-level repo folder
    # name isn't inserted into the module path. This avoids invalid module names
    # like 'heiST.ai_training.sanitizer'.
    path = path.resolve()
    if path.suffix != '.py':
        return None
    module_name = path.stem
    cur = path.parent
    pkg_parts: list[str] = []

    # Walk upward while the directory is a Python package (has __init__.py) and
    # we haven't reached the explicit repository root.
    while cur != root and (cur / '__init__.py').exists():
        pkg_parts.append(cur.name)
        parent = cur.parent
        if parent == cur:
            break
        cur = parent

    # If the immediate parent is the root and it still has __init__.py, do not
    # include the root directory name in the package path; stop there.
    if (cur == root) and (cur / '__init__.py').exists():
        # pkg_parts currently contains package segments from leaf up to, but not including, root
        pass

    if not pkg_parts:
        # No package structure above the module (or we stopped at repo root): return module name
        return module_name

    pkg_parts.reverse()
    return '.'.join(pkg_parts + [module_name])


def _find_candidate_scripts(root: Path):
    for p in root.rglob('*.py'):
        # skip hidden, venvs, egg-info, dist, .git
        if any(part in ('venv', '.venv', 'env', '.git', '__pycache__') or part.endswith('.egg-info') for part in
               p.parts):
            continue
        if p.name == '__init__.py':
            continue
        try:
            text = p.read_text()
        except Exception:
            continue
        if MAIN_RE.search(text):
            yield p


def _write_shim(target_module: str, shim_path: Path, python_executable: str = 'python3'):
    shim_text = f"""#!/usr/bin/env bash
set -e

cd "{PROJECT_ROOT}" || {{
  echo "Failed to cd to {PROJECT_ROOT}" >&2
  exit 1
}}

exec "{python_executable}" -m {target_module} "$@"
"""
    shim_path.write_text(shim_text)


def generate_shims():
    scripts = list(_find_candidate_scripts(PROJECT_ROOT))
    if not scripts:
        print('No candidate scripts with __main__ found.')
        return
    BIN_DIR.mkdir(exist_ok=True)
    created = []
    for p in scripts:
        mod = _find_module_name_for_path(p, PROJECT_ROOT)
        if not mod:
            continue
        shim_name = p.stem
        shim_path = BIN_DIR / shim_name
        _write_shim(mod, shim_path, python_executable=sys.executable)
        created.append((p, mod, shim_path))

    if created:
        # make shims executable
        import stat
        for _src, _mod, shim in created:
            shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


bootstrap_requirements()
generate_shims()

from dotenv import dotenv_values, load_dotenv
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text



# Load values from the current .env if it exists so the wizard can act as a
# guided editor instead of forcing a from-scratch setup every time.
if ENV_FILE_PATH.exists():
    load_dotenv(ENV_FILE_PATH, override=False)
else:
    load_dotenv(override=False)

console = Console()


def draw_header() -> None:
    """
    Draws the header including logo and product name at the top
    """

    logo = r"""
⠀⠀⠀⠀⢀⣤⡶⠶⠛⠛⠛⠛⠶⢦⣤⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⣠⡾⠋⠡⣴⠶⠟⠛⠛⠻⢶⣤⣈⠛⢶⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⣴⠏⣠⡦⠀⣠⡴⠾⠛⠛⠶⢾⣇⠙⢷⡄⠻⣆⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀         
⢸⡏⢰⡟⢀⡾⠋⠀⣀⠀⠀⠀⠀⠙⢷⡀⢻⡄⢹⡆⠀⠀[red]⣿⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠸⠿[/red]⠀⢀⣴⠿⠻⢿⣦⠀⠸⠿⢿⣿⠿⠿
⣿⣀⣿⠀⣾⠃⠀⠀⣿[red]⣿⣶⣤⣀[/red]⠀⠘⠃⠈⣷⠈⠁⠀⠀[red]⣿⡷⠾⢿⣆⠀⢠⣶⠿⢷⣦⠀⢸⣿[/red]⠀⠘⢿⣶⣤⣌⡉⠀⠀⠀⢸⣿⠀⠀
⣿⠉⣿⠀⢿⡀⠀⠀⣿[red]⣿⠿⠛⠉[/red]⠀⢠⡄⢀⡿⢀⡀⠀⠀[red]⣿⡇⠀⢸⣿⠀⢸⡿⠶⠾⠿⠀⢸⣿[/red]⠀⢀⣀⠈⠉⠻⣿⠀⠀⠀⢸⣿⠀⠀
⢸⣇⠸⣧⠘⢷⣄⠀⣿⠀⠀⠀⠀⣠⡾⠁⣼⠃⣸⠇⠀⠀[red]⣿⡇⠀⢸⣿⠀⠘⢿⣤⣼⠟⠀⢸⣿[/red]⠀⠈⠻⣷⣶⣾⠟⠀⠀⠀⢸⣿⠀⠀
⠀⠻⣆⠙⢷⣄⠙⠷⢿⣤⣤⡶⠞⠋⠀⠾⠃⣴⠏⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠙⢷⣄⡙⠻⠶⣤⣤⣤⣴⠶⠟⢀⣤⠾⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠈⠛⠷⠶⣤⣤⣤⣤⠶⠞⠛⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
                              
                              
The interactive heiST installation wizard.
    """

    console.print(logo)


def clear_screen() -> None:
    if not supports_arrow_navigation():
        return

    # 2J clears the visible screen, 3J clears scrollback, H moves the cursor home.
    # If ANSI is not supported, fallback to Rich's standard clear.
    try:
        console.clear()
    except Exception:
        console.file.write("\x1b[2J\x1b[3J\x1b[H")
        console.file.flush()

    draw_header()


def supports_arrow_navigation() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def read_key_event() -> str:
    if os.name == "nt":
        import msvcrt

        first = msvcrt.getwch()
        if first == "\x03":
            raise KeyboardInterrupt
        if first in {"\r", "\n"}:
            return "enter"
        if first == "\x1b":
            return "escape"
        if first == "\x08":
            return "back"
        if first in {"\x00", "\xe0"}:
            second = msvcrt.getwch()
            if second == "H":
                return "up"
            if second == "P":
                return "down"
            return "other"
        return f"char:{first.lower()}"

    import termios
    import tty

    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        first = sys.stdin.read(1)
        if first == "\x03":
            raise KeyboardInterrupt
        if first in {"\r", "\n"}:
            return "enter"
        if first == "\x1b":
            second = sys.stdin.read(1)
            if second != "[":
                return "escape"
            third = sys.stdin.read(1)
            if third == "A":
                return "up"
            if third == "B":
                return "down"
            return "other"
        if first in {"\x7f", "\b"}:
            return "back"
        return f"char:{first.lower()}"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)


def arrow_select_menu(
    title: str,
    subtitle: str,
    options: list[str],
    *,
    allow_back: bool = False,
    initial_index: int = 0,
    option_details: Optional[list[str]] = None,
    divider_before: Optional[int] = None,
    action_start_index: Optional[int] = None,
) -> Optional[int]:
    if not options:
        raise ValueError("Options cannot be empty.")
    if option_details is not None and len(option_details) != len(options):
        raise ValueError("option_details must match options length.")

    if not supports_arrow_navigation():
        console.print(Panel(subtitle, title=title, border_style="magenta"))
        for idx, option in enumerate(options, start=1):
            if divider_before is not None and idx - 1 == divider_before:
                console.rule("[magenta]Actions[/magenta]")
            option_style = "magenta" if action_start_index is not None and idx - 1 >= action_start_index else "white"
            console.print(f"[bold cyan]{idx})[/bold cyan] [{option_style}]{option}[/{option_style}]")

        choices = [str(idx) for idx in range(1, len(options) + 1)]
        if allow_back:
            choices.append("b")
        fallback_choice = Prompt.ask("[bold cyan]Selection[/bold cyan]", choices=choices, default="1", show_choices=False).strip().lower()
        if fallback_choice == "b":
            return None
        return int(fallback_choice) - 1

    index = min(max(initial_index, 0), len(options) - 1)

    while True:
        clear_screen()
        console.print(Panel(subtitle, title=title, border_style="magenta"))

        table = Table(box=box.ROUNDED, show_header=False, expand=True)
        table.add_column("", width=2)
        table.add_column("Option")
        for idx, option in enumerate(options):
            if divider_before is not None and idx == divider_before:
                table.add_section()

            is_action = action_start_index is not None and idx >= action_start_index
            marker = ">" if idx == index else " "
            if is_action:
                style = "bold blue" if idx == index else "magenta"
            else:
                style = "bold cyan" if idx == index else "white"
            table.add_row(marker, f"[{style}]{option}[/{style}]")
        console.print(table)

        if option_details is not None:
            console.print(
                Panel(
                    option_details[index],
                    title="Selected variable description",
                    border_style="blue",
                )
            )

        hint = "Use Up/Down and Enter."
        if allow_back:
            hint += " Press Esc or Backspace to go back."
        console.print(f"[dim]{hint}[/dim]")

        event = read_key_event()
        if event == "up":
            index = (index - 1) % len(options)
            continue
        if event == "down":
            index = (index + 1) % len(options)
            continue
        if event == "enter":
            return index
        if allow_back and event in {"escape", "back"}:
            return None


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    kind: str = "text"
    default: str = ""
    description: str = ""
    secret: bool = False
    required: bool = True
    example: str = ""


@dataclass(frozen=True)
class SectionSpec:
    title: str
    subtitle: str
    fields: list[FieldSpec]


DEFAULTS = {
    # Core Proxmox / installer values
    "PROXMOX_HOST": "10.0.0.1",
    "PROXMOX_USER": "root@pam",
    "PROXMOX_PASSWORD": "",
    "PROXMOX_PORT": "8006",
    "BACKEND_PORT": "8000",
    "PROXMOX_INTERNAL_IP": "10.0.3.4",
    "PROXMOX_EXTERNAL_IP": "10.0.3.4",
    "PROXMOX_HOSTNAME": "pve",
    "UBUNTU_BASE_SERVER_URL": "https://heibox.uni-heidelberg.de/f/004597b1f84040f79dbf/?dl=1",

    # Paths / database / webserver
    "DATABASE_FILES_DIR": "/root/heiST/database",
    "DATABASE_NAME": "heist",
    "DATABASE_USER": "postgres",
    "DATABASE_PASSWORD": "",
    "DATABASE_PORT": "5432",
    "DATABASE_HOST": "10.0.0.102",
    "WEBSERVER_FILES_DIR": "/root/heiST/webserver",
    "WEBSERVER_USER": "www-data",
    "WEBSERVER_GROUP": "www-data",
    "WEBSERVER_ROOT": "/var/www/html",
    "WEBSERVER_HOST": "10.0.0.101",
    "WEBSERVER_HTTP_PORT": "80",
    "WEBSERVER_HTTPS_PORT": "443",
    "BACKEND_FILES_DIR": "/root/heiST/backend",
    "WEBSERVER_DATABASE_USER": "api_user",
    "WEBSERVER_DATABASE_PASSWORD": "",
    "WEBSITE_ADMIN_USER": "admin",
    "WEBSITE_ADMIN_PASSWORD": "",
    "BACKEND_AUTHENTICATION_TOKEN": "",
    "LECTURE_SIGNUP_TOKEN": "dummy-token",

    # Networking / VPN / VM import
    "OPENVPN_SUBNET": "10.64.0.0/16",
    "OPENVPN_SERVER_IP": "10.64.0.1",
    "BACKEND_NETWORK_SUBNET": "10.0.0.1/24",
    "BACKEND_NETWORK_ROUTER": "10.0.0.1",
    "BACKEND_NETWORK_DEVICE": "vrt_backend",
    "BACKEND_NETWORK_HOST_MIN": "10.0.0.2",
    "BACKEND_NETWORK_HOST_MAX": "10.0.0.254",
    "DATABASE_MAC_ADDRESS": "0E:00:00:00:00:01",
    "WEBSERVER_MAC_ADDRESS": "0E:00:00:00:00:02",
    "CHALLENGES_ROOT_SUBNET": "10.128.0.0",
    "CHALLENGES_ROOT_SUBNET_MASK": "255.128.0.0",
    "MONITORING_VPN_INTERFACE": "ctf_monitoring",
    "MONITORING_DMZ_INTERFACE": "dmz_monitoring",
    "MONITORING_HOST": "10.0.0.103",
    "MONITORING_VM_ID": "9000",
    "WAZUH_API_PORT": "55000",
    "WAZUH_API_USER": "wazuh-wui",
    "WAZUH_API_PASSWORD": "MyS3cr37P450r.*-",
    "WAZUH_ENROLLMENT_PASSWORD": "",
    "WAZUH_NETWORK_DEVICE": "vrtmon",

    # Monitoring / VM / observability
    "MONITORING_FILES_DIR": "/root/heiST/monitoring",
    "MONITORING_VM_NAME": "monitoring-vm",
    "MONITORING_VM_MAC_ADDRESS": "0E:00:00:00:00:03",
    "MONITORING_VM_MEMORY": "10240",
    "MONITORING_VM_CORES": "2",
    "MONITORING_VM_DISK": "32G",
    "MONITORING_VM_USER": "ubuntu",
    "MONITORING_VM_PASSWORD": "",
    "PROXMOX_LVM_STORAGE": "local-lvm",
    "PROXMOX_SSH_KEYFILE": "/root/.ssh/id_rsa",
    "PROXMOX_EXPORTER_TOKEN_NAME": "pve_exporter_token",
    "WAZUH_NETWORK_DEVICE_IPV6": "fd12:3456:789a:1::1",
    "WAZUH_NETWORK_DEVICE_CIDR": "64",
    "WAZUH_NETWORK_SUBNET": "fd12:3456:789a:1::/64",
    "WAZUH_MANAGER_IPV6": "fd12:3456:789a:1::101/64",
    "CLOUD_INIT_NETWORK_DEVICE": "vmbr-cloud",
    "CLOUD_INIT_NETWORK_DEVICE_IP": "10.32.0.1",
    "CLOUD_INIT_NETWORK_DEVICE_CIDR": "20",
    "CLOUD_INIT_NETWORK_SUBNET": "10.32.0.0/20",
    "MONITORING_DNS": "clickhouse.local",
    "BACKEND_LOGGING_DIR": "/var/log/backend",
    "GRAFANA_PORT": "3000",
    "GRAFANA_USER": "admin",
    "GRAFANA_PASSWORD": "",
    "GRAFANA_FILES_SETUP_DIR": "/root/heiST/monitoring/grafana",
    "GRAFANA_FILES_DIR": "/etc/grafana",
    "PROMETHEUS_PORT": "9090",
    "POSTGRES_EXPORTER_PORT": "9187",
    "POSTGRES_EXPORTER_PASSWORD": "",
    "PROXMOX_EXPORTER_PORT": "9221",
    "MONITORING_VM_EXPORTER_PORT": "9100",
    "DATABASE_VM_EXPORTER_PORT": "9100",
    "WEBSERVER_VM_EXPORTER_PORT": "9100",
    "WEBSERVER_APACHE_EXPORTER_PORT": "9117",
    "PROXMOX_NODE_EXPORTER_PORT": "9101",
    "WAZUH_MANAGER_PORT": "9200",
    "WAZUH_DASHBOARD_USER": "kibanaserver",
    "WAZUH_DASHBOARD_PASSWORD": "",
    "WAZUH_INDEXER_USER": "admin",
    "WAZUH_INDEXER_PASSWORD": "",
    "WAZUH_REGISTRATION_PORT": "1515",
    "WAZUH_COMMUNICATION_PORT": "1514",
    "WAZUH_FILE_DIR": "/root/heiST/monitoring/wazuh",
    "CLICKHOUSE_HTTPS_PORT": "8443",
    "CLICKHOUSE_NATIVE_PORT": "9440",
    "CLICKHOUSE_USER": "default",
    "CLICKHOUSE_PASSWORD": "",
    "CLICKHOUSE_SQL_DIR": "/root/heiST/monitoring/clickhouse/sql",
    "VECTOR_FILES_DIR": "/root/heiST/monitoring/vector",
    "VECTOR_DIR": "/etc/vector",
    "SURICATA_LOG_DIR": "/var/log/suricata",
    "SURICATA_FILES_DIR": "/etc/suricata",
    "SURICATA_RULES_DIR": "/var/lib/suricata/rules",
    "ZEEK_SITE_DIR": "/opt/zeek/share/zeek/site",
    "LOGROTATE_CONFIG_DIR": "/etc/logrotate.d",
    "ROTATE_DAYS": "90",
    "PCAP_ROTATION_INTERVAL": "*/15",
    "DNSMASQ_BACKEND_DIR": "/etc/dnsmasq-backend",
    "SSL_TLS_CERTS_DIR": "/root/heiST/setup/certs",
    "PVE_EXPORTER_DIR": "/etc/pve-exporter",
    "IPTABLES_FILE": "/etc/iptables-backend/iptables.sh",
}

SIMPLE_KEYS = [
    "PROXMOX_HOSTNAME",
    "PROXMOX_PASSWORD",
    "PROXMOX_INTERNAL_IP",
    "PROXMOX_EXTERNAL_IP",
]


def field(name: str, label: str, kind: str = "text", *, description: str = "", secret: bool = False, required: bool = True, example: str = "") -> FieldSpec:
    return FieldSpec(
        name=name,
        label=label,
        kind=kind,
        default=DEFAULTS.get(name, ""),
        description=description,
        secret=secret,
        required=required,
        example=example,
    )


SIMPLE_SECTION = SectionSpec(
    title="Simple setup",
    subtitle="Only the five values most users need to change.",
    fields=[
        field(
            "PROXMOX_HOSTNAME",
            "Proxmox node name",
            "hostname",
            description="The node name shown in the Proxmox UI and used by the API. Usually this is the Proxmox host's short hostname, for example `pve`.",
            example="pve",
        ),
        field(
            "PROXMOX_PASSWORD",
            "Proxmox password",
            "secret",
            secret=True,
            description="The password for the Proxmox account used by the installer. This should be the password you would normally use to log in to the Proxmox web UI or API.",
        ),
        field(
            "PROXMOX_INTERNAL_IP",
            "Proxmox internal IP",
            "ip",
            description="The IP address where Proxmox receives traffic on. May differ from the IP users connect to, if your Proxmox host is located inside a NAT network.",
            example="10.0.3.4",
        ),
        field(
            "PROXMOX_EXTERNAL_IP",
            "Proxmox external IP",
            "ip",
            description="The IP address that users or VPN clients should reach from the outside. This is the IP address that will be embedded in generated OpenVPN configs.",
            example="10.0.3.4",
        ),
        field(
            "WEBSITE_ADMIN_PASSWORD",
            "Website admin password",
            "secret",
            secret=True,
            description="Password for the admin account of the web application. This is used to log in to the challenge website and should be something secure."
        ),
    ],
)
ADVANCED_SECTIONS = [
    SectionSpec(
        title="Proxmox Control Plane and Host Access",
        subtitle="Configure Proxmox endpoint identity, API authentication, storage targets, and SSH access used during orchestration.",
        fields=[
            field("PROXMOX_HOST", "Proxmox host", "ip_or_host", description="The hostname or IP address of the Proxmox node or cluster entry point.", example="10.0.0.1"),
            field("PROXMOX_USER", "Proxmox user", description="The account used for API calls. The default is usually `root@pam`.", example="root@pam"),
            field("PROXMOX_PASSWORD", "Proxmox password", "secret", secret=True, description="Password for the Proxmox user above. The installer uses it to create API tokens and configure the host."),
            field("PROXMOX_PORT", "Proxmox API port", "port", description="The HTTPS API port for Proxmox. In most installations this is `8006`.", example="8006"),
            field("PROXMOX_HOSTNAME", "Proxmox node name", "hostname", description="The node name shown in the Proxmox UI and used by the API. Usually this is the Proxmox host's short hostname, for example `pve`.", example="pve"),
            field("PROXMOX_LVM_STORAGE", "Proxmox LVM storage", description="Storage pool used when importing OVA disks.", example="local-lvm"),
            field("PROXMOX_SSH_KEYFILE", "Proxmox SSH key file", "path", description="Path to the SSH private key used by auxiliary monitoring scripts.", example="/root/.ssh/id_rsa"),

        ],
    ),

    SectionSpec(
        title="Base Image and Backend VM Provisioning",
        subtitle="Define source artifacts and bootstrap inputs used to provision backend virtual machines consistently.",
        fields=[
            field("UBUNTU_BASE_SERVER_URL", "Ubuntu base server URL", "path", description="URL used to download the Ubuntu cloud image/base server artifact during setup."),
        ]
    ),

    SectionSpec(
        title="NAT Edge Addressing and Exposure Rules",
        subtitle="Set internal and external Proxmox addresses that drive NAT forwarding behavior and user-facing connectivity.",
        fields = [
            field("PROXMOX_INTERNAL_IP", "Proxmox internal IP", "ip",
                  description="Internal IP address used for port-forwarding rules."),
            field("PROXMOX_EXTERNAL_IP", "Proxmox external IP", "ip",
                  description="External IP address exposed to VPN users or the public network."),
        ],
    ),

SectionSpec(
        title="Website Administration and Enrollment Controls",
        subtitle="Configure administrative login identity and enrollment token controls for the challenge web interface.",
        fields=[
            field("WEBSITE_ADMIN_USER", "Website admin user", description="Admin username created in the challenge database.", example="admin"),
            field("WEBSITE_ADMIN_PASSWORD", "Website admin password", "secret", secret=True, description="Password for the admin account in the challenge website."),
            field("LECTURE_SIGNUP_TOKEN", "Lecture signup token", "secret", secret=True,
                  description="Optional token used by lecture or signup flows in the web application."),

        ],
    ),

    SectionSpec(
        title="Backend API Runtime and Trust Settings",
        subtitle="Set backend listener ports, authentication secrets, logging paths, and local source directory mapping.",
        fields=[
            field("BACKEND_PORT", "Backend port", "port", description="The HTTP port the backend service listens on.", example="8000"),
            field("BACKEND_AUTHENTICATION_TOKEN", "Backend authentication token", "secret", secret=True, description="Shared secret used by the web application and backend API to authenticate requests."),
            field("BACKEND_LOGGING_DIR", "Backend logging directory", "path",
                  description="Directory on the backend VM where backend logs are written."),
            field("BACKEND_FILES_DIR", "Backend files directory", "path",
                  description="Absolute path to the backend source tree on the setup machine."),
        ],
    ),
    SectionSpec(
        title="PostgreSQL Service and Application Credentials",
        subtitle="Configure database endpoint details, privileged roles, application users, and repository asset location.",
        fields=[
            field("DATABASE_NAME", "Database name", description="Name of the PostgreSQL database created during setup.", example="heist"),
            field("DATABASE_USER", "Database user", description="PostgreSQL role used by the backend during setup.", example="postgres"),
            field("DATABASE_PASSWORD", "Database password", "secret", secret=True, description="Password assigned to the PostgreSQL role used by the challenge backend."),
            field("DATABASE_PORT", "Database port", "port", description="TCP port for PostgreSQL.", example="5432"),
            field("DATABASE_HOST", "Database host", "ip", description="The IP address assigned to the database VM on the backend network.", example="10.0.0.102"),
            field("WEBSERVER_DATABASE_USER", "Webserver database user", description="Restricted database account used by the PHP web application.", example="api_user"),
            field("WEBSERVER_DATABASE_PASSWORD", "Webserver database password", "secret", secret=True, description="Password for the web application's PostgreSQL account."),
            field("DATABASE_FILES_DIR", "Database files directory", "path",
                  description="Absolute path to the repository's database assets on the setup machine."),

        ],
    ),
    SectionSpec(
        title="Webserver Runtime Ports and Filesystem Paths",
        subtitle="Define webserver addressing, HTTP and HTTPS exposure, process ownership, and deployment directories.",
        fields=[
            field("WEBSERVER_HOST", "Webserver host", "ip", description="The IP address assigned to the webserver VM on the backend network.", example="10.0.0.101"),
            field("WEBSERVER_HTTP_PORT", "Webserver HTTP port", "port", description="HTTP port exposed by Apache.", example="80"),
            field("WEBSERVER_HTTPS_PORT", "Webserver HTTPS port", "port", description="HTTPS port exposed by Apache.", example="443"),
            field("WEBSERVER_USER", "Webserver user", description="Linux user that owns or runs the web application files on the target VM.", example="www-data"),
            field("WEBSERVER_GROUP", "Webserver group", description="Group ownership for the web application files.", example="www-data"),
            field("WEBSERVER_ROOT", "Webserver document root", "path", description="Document root on the webserver VM.", example="/var/www/html"),
            field("WEBSERVER_FILES_DIR", "Webserver files directory", "path", description="Absolute path to the repository's webserver assets on the setup machine."),
        ],
    ),
    SectionSpec(
        title="Backend Bridge Topology and Address Allocation",
        subtitle="Set bridge subnetting, router defaults, DHCP bounds, and static MAC assignments for core service VMs.",
        fields=[
            field("BACKEND_NETWORK_SUBNET", "Backend network subnet", "interface", description="Backend bridge subnet in interface notation, for example `10.0.0.1/24`.", example="10.0.0.1/24"),
            field("BACKEND_NETWORK_ROUTER", "Backend network router", "ip", description="Default gateway used by backend VMs on the bridge.", example="10.0.0.1"),
            field("BACKEND_NETWORK_DEVICE", "Backend bridge name", description="Linux bridge name created on the Proxmox host for backend traffic.", example="vrt_backend"),
            field("BACKEND_NETWORK_HOST_MIN", "Backend DHCP range start", "ip", description="First address handed out by dnsmasq for backend VMs.", example="10.0.0.2"),
            field("BACKEND_NETWORK_HOST_MAX", "Backend DHCP range end", "ip", description="Last address handed out by dnsmasq for backend VMs.", example="10.0.0.254"),
            field("DATABASE_MAC_ADDRESS", "Database VM MAC address",
                  description="Static MAC address assigned to the database VM.", example="0E:00:00:00:00:01"),
            field("WEBSERVER_MAC_ADDRESS", "Webserver VM MAC address",
                  description="Static MAC address assigned to the webserver VM.", example="0E:00:00:00:00:02"),
            field("MONITORING_VM_MAC_ADDRESS", "Monitoring VM MAC address",
                  description="Static MAC address assigned to the monitoring VM.", example="0E:00:00:00:00:03"),

        ],
    ),


    SectionSpec(
        title="Challenge Network Routing and VPN Advertisement",
        subtitle="Configure OpenVPN address pools and challenge root routes propagated to connected participants.",
        fields=[
            field("OPENVPN_SUBNET", "OpenVPN subnet", "interface",
                  description="VPN client pool in CIDR form. The installer derives the server netmask from this value.",
                  example="10.64.0.0/10"),
            field("OPENVPN_SERVER_IP", "OpenVPN server IP", "ip",
                  description="Static server IP address inside the VPN subnet.", example="10.64.0.1"),
            field("CHALLENGES_ROOT_SUBNET", "Challenges root subnet", "ip_or_host",
                  description="Base subnet for challenge VM networks pushed to VPN clients.", example="10.128.0.0"),
            field("CHALLENGES_ROOT_SUBNET_MASK", "Challenges root mask",
                  description="Subnet mask paired with the challenge root network.", example="255.128.0.0"),

        ],
    ),

    SectionSpec(
        title="Monitoring VM Compute and Access Bootstrap",
        subtitle="Specify monitoring virtual machine identity, resource sizing, initial access credentials, and setup paths.",
        fields=[
            field("MONITORING_HOST", "Monitoring host", "ip", description="Static IP address of the monitoring VM on the backend network.", example="10.0.0.103"),
            field("MONITORING_VM_ID", "Monitoring VM ID", "integer", description="Proxmox VM ID reserved for the monitoring machine.", example="9000"),
            field("MONITORING_VM_NAME", "Monitoring VM name", description="Human-readable VM name shown in Proxmox.", example="monitoring-vm"),
            field("MONITORING_VM_MEMORY", "Monitoring VM memory (MB)", "integer",
                  description="Memory assigned to the monitoring VM.", example="10240"),
            field("MONITORING_VM_CORES", "Monitoring VM cores", "integer",
                  description="Number of virtual CPU cores assigned to the monitoring VM.", example="2"),
            field("MONITORING_VM_DISK", "Monitoring VM disk",
                  description="Disk size or volume definition used for the monitoring VM.", example="32G"),
            field("MONITORING_VM_USER", "Monitoring VM user", description="Default SSH user for the monitoring VM.",
                  example="ubuntu"),
            field("MONITORING_VM_PASSWORD", "Monitoring VM password", "secret", secret=True,
                  description="Password used for the monitoring VM's initial SSH access."),

            field("MONITORING_FILES_DIR", "Monitoring files directory", "path",
                  description="Absolute path to the monitoring repository tree on the setup machine."),

        ],
    ),
    SectionSpec(
        title="Monitoring Fabric and Dual-Stack Network Wiring",
        subtitle="Configure monitoring interfaces, Wazuh IPv6 segments, cloud-init bridge addressing, and internal DNS naming.",
        fields=[
            field("MONITORING_VPN_INTERFACE", "Monitoring VPN interface", description="Bridge or interface name used for monitoring traffic from the VPN side.", example="ctf_monitoring"),
            field("MONITORING_DMZ_INTERFACE", "Monitoring DMZ interface", description="Bridge or interface name used for monitoring the DMZ side.", example="dmz_monitoring"),
            field("WAZUH_NETWORK_DEVICE", "Wazuh network device", description="Bridge name used for the Wazuh network wiring.", example="vrtmon"),
            field("WAZUH_NETWORK_DEVICE_IPV6", "Wazuh network IPv6", "interface", description="IPv6 address and prefix assigned to the Wazuh network device.", example="fd12:3456:789a:1::1"),
            field("WAZUH_NETWORK_DEVICE_CIDR", "Wazuh network device prefix", "integer", description="IPv6 prefix length for the Wazuh network device.", example="64"),
            field("WAZUH_NETWORK_SUBNET", "Wazuh network subnet", "interface", description="IPv6 subnet used by the Wazuh network.", example="fd12:3456:789a:1::/64"),
            field("WAZUH_MANAGER_IPV6", "Wazuh manager IPv6", "interface", description="IPv6 address and prefix assigned to the Wazuh manager endpoint.", example="fd12:3456:789a:1::101/64"),
            field("CLOUD_INIT_NETWORK_DEVICE", "Cloud-init bridge", description="Bridge name for the cloud-init network device.", example="vmbr-cloud"),
            field("CLOUD_INIT_NETWORK_DEVICE_IP", "Cloud-init bridge IP", "ip", description="IPv4 address assigned to the cloud-init bridge on the host.", example="10.32.0.1"),
            field("CLOUD_INIT_NETWORK_DEVICE_CIDR", "Cloud-init bridge prefix", "integer", description="CIDR prefix length for the cloud-init bridge.", example="20"),
            field("CLOUD_INIT_NETWORK_SUBNET", "Cloud-init subnet", "interface", description="Subnet used by cloud-init generated VMs.", example="10.32.0.0/20"),
            field("MONITORING_DNS", "Monitoring DNS name", description="DNS name used by monitoring tooling and dashboards.", example="clickhouse.local"),
        ],
    ),
    SectionSpec(
        title="Grafana Access Management and Provisioning Paths",
        subtitle="Define Grafana service exposure, administrator credentials, and source-to-target provisioning directories.",
        fields=[
            field("GRAFANA_PORT", "Grafana port", "port", description="Port exposed by Grafana on the monitoring host.", example="3000"),
            field("GRAFANA_USER", "Grafana user", description="Grafana administrator username.", example="admin"),
            field("GRAFANA_PASSWORD", "Grafana password", "secret", secret=True, description="Grafana administrator password."),
            field("GRAFANA_FILES_SETUP_DIR", "Grafana setup directory", "path", description="Directory in the repository containing Grafana provisioning files."),
            field("GRAFANA_FILES_DIR", "Grafana install directory", "path", description="Destination directory for Grafana configuration on the target host."),
        ],
    ),
    SectionSpec(
        title="Prometheus Scrape Endpoints and Exporter Ports",
        subtitle="Configure Prometheus listener ports and exporter integration endpoints across Proxmox and service VMs.",
        fields=[
            field("PROMETHEUS_PORT", "Prometheus port", "port", description="Port exposed by Prometheus.",
                  example="9090"),
            field("POSTGRES_EXPORTER_PORT", "Postgres exporter port", "port", description="Port exposed by the postgres exporter.", example="9187"),
            field("POSTGRES_EXPORTER_PASSWORD", "Postgres exporter password", "secret", secret=True, description="Password used by the PostgreSQL exporter component."),
            field("PROXMOX_EXPORTER_PORT", "Proxmox exporter port", "port", description="Port exposed by the Proxmox exporter.", example="9221"),
            field("MONITORING_VM_EXPORTER_PORT", "Monitoring VM exporter port", "port", description="Node exporter port for the monitoring VM.", example="9100"),
            field("DATABASE_VM_EXPORTER_PORT", "Database VM exporter port", "port", description="Node exporter port for the database VM.", example="9100"),
            field("WEBSERVER_VM_EXPORTER_PORT", "Webserver VM exporter port", "port", description="Node exporter port for the webserver VM.", example="9100"),
            field("WEBSERVER_APACHE_EXPORTER_PORT", "Apache exporter port", "port", description="Port exposed by the Apache exporter.", example="9117"),
            field("PROXMOX_NODE_EXPORTER_PORT", "Proxmox node exporter port", "port", description="Port exposed by the Proxmox node exporter.", example="9101"),
            field("PROXMOX_EXPORTER_TOKEN_NAME", "Proxmox exporter token name",
                  description="Token name used by the Proxmox exporter integration.", example="pve_exporter_token"),

        ],
    ),
    SectionSpec(
        title="Wazuh Control Stack and Agent Enrollment Settings",
        subtitle="Set Wazuh manager, API, dashboard, indexer, and agent enrollment credentials with required ports.",
        fields=[
            field("WAZUH_MANAGER_PORT", "Wazuh manager port", "port", description="Port exposed by the Wazuh manager service.", example="9200"),
            field("WAZUH_API_PORT", "Wazuh API port", "port", description="Port used by the Wazuh API.", example="55000"),
            field("WAZUH_API_USER", "Wazuh API user", description="API username for the Wazuh manager.", example="wazuh-wui"),
            field("WAZUH_API_PASSWORD", "Wazuh API password", "secret", secret=True, description="Password for the Wazuh API user."),
            field("WAZUH_DASHBOARD_USER", "Wazuh dashboard user", description="Dashboard user account used by Wazuh components.", example="kibanaserver"),
            field("WAZUH_DASHBOARD_PASSWORD", "Wazuh dashboard password", "secret", secret=True, description="Password for the Wazuh dashboard user."),
            field("WAZUH_INDEXER_USER", "Wazuh indexer user", description="Indexer admin username.", example="admin"),
            field("WAZUH_INDEXER_PASSWORD", "Wazuh indexer password", "secret", secret=True, description="Password for the Wazuh indexer admin account."),
            field("WAZUH_ENROLLMENT_PASSWORD", "Wazuh enrollment password", "secret", secret=True, description="Shared password used to enroll Wazuh agents."),
            field("WAZUH_REGISTRATION_PORT", "Wazuh registration port", "port", description="Port used by agent registration.", example="1515"),
            field("WAZUH_COMMUNICATION_PORT", "Wazuh communication port", "port", description="Port used by agent communication.", example="1514"),
            field("WAZUH_FILE_DIR", "Wazuh files directory", "path", description="Directory containing the Wazuh setup assets in the repository."),
        ],
    ),
    SectionSpec(
        title="ClickHouse Core Connectivity and Bootstrap Parameters",
        subtitle="Define ClickHouse transport ports, access credentials, and SQL bootstrap file location for initialization.",
        fields=[
            field("CLICKHOUSE_HTTPS_PORT", "ClickHouse HTTPS port", "port", description="HTTPS port exposed by ClickHouse.", example="8443"),
            field("CLICKHOUSE_NATIVE_PORT", "ClickHouse native port", "port", description="Native protocol port exposed by ClickHouse.", example="9440"),
            field("CLICKHOUSE_USER", "ClickHouse user", description="Username used to connect to ClickHouse.", example="default"),
            field("CLICKHOUSE_PASSWORD", "ClickHouse password", "secret", secret=True, description="Password used to connect to ClickHouse."),
            field("CLICKHOUSE_SQL_DIR", "ClickHouse SQL directory", "path", description="Directory that contains ClickHouse SQL setup files."),
        ],
    ),
    SectionSpec(
        title="Telemetry Pipelines, IDS Assets, and Retention Policies",
        subtitle="Configure Vector, Suricata, Zeek, and log retention paths governing telemetry ingestion and archival lifecycle.",
        fields=[
            field("VECTOR_FILES_DIR", "Vector files directory", "path", description="Directory containing Vector configuration files in the repository."),
            field("VECTOR_DIR", "Vector install directory", "path", description="Destination directory for Vector configuration on the target host."),
            field("SURICATA_LOG_DIR", "Suricata log directory", "path", description="Directory where Suricata logs are written.", example="/var/log/suricata"),
            field("SURICATA_FILES_DIR", "Suricata files directory", "path", description="Destination directory for Suricata configuration.", example="/etc/suricata"),
            field("SURICATA_RULES_DIR", "Suricata rules directory", "path", description="Directory that stores Suricata rule files.", example="/var/lib/suricata/rules"),
            field("ZEEK_SITE_DIR", "Zeek site directory", "path", description="Directory used by Zeek for site-local configuration.", example="/opt/zeek/share/zeek/site"),
            field("LOGROTATE_CONFIG_DIR", "Logrotate config directory", "path", description="Directory containing logrotate configuration snippets.", example="/etc/logrotate.d"),
            field("ROTATE_DAYS", "Log retention days", "integer", description="How many days logs should be retained before rotation/pruning.", example="90"),
            field("PCAP_ROTATION_INTERVAL", "PCAP rotation interval", description="Cron-style interval or schedule used for packet capture rotation.", example="*/15"),
            field("DNSMASQ_BACKEND_DIR", "Dnsmasq backend directory", "path", description="Directory used to store the backend dnsmasq configuration and leases.", example="/etc/dnsmasq-backend"),
            field("SSL_TLS_CERTS_DIR", "SSL/TLS certificates directory", "path", description="Directory used by monitoring scripts to store trusted certificates.", example="/root/heiST/setup/certs"),
            field("PVE_EXPORTER_DIR", "PVE exporter directory", "path", description="Directory used by the Proxmox exporter configuration.", example="/etc/pve-exporter"),
            field("IPTABLES_FILE", "Iptables script path", "path", description="Location of the generated iptables bootstrap script.", example="/etc/iptables-backend/iptables.sh"),
        ],
    ),
]


ALL_SECTIONS = [SIMPLE_SECTION, *ADVANCED_SECTIONS]
# Build an ordered, deduplicated list of field specs.
# We prefer the first occurrence of a field name (SIMPLE_SECTION is placed first)
# so that when a variable exists in both simple and advanced sections the
# simple-mode FieldSpec (including its description) wins.
_ALL_FIELD_SPECS_ORDERED: list[FieldSpec] = []
FIELD_BY_NAME: dict[str, FieldSpec] = {}
for section in ALL_SECTIONS:
    for spec in section.fields:
        if spec.name not in FIELD_BY_NAME:
            FIELD_BY_NAME[spec.name] = spec
            _ALL_FIELD_SPECS_ORDERED.append(spec)

ALL_FIELD_SPECS = _ALL_FIELD_SPECS_ORDERED


def format_env_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def generate_password_value(length: int = 24) -> str:
    LOWERCASE = string.ascii_lowercase
    UPPERCASE = string.ascii_uppercase
    DIGITS = string.digits
    SPECIAL = "!#$%&*+-?@"

    password = []

    for required in [LOWERCASE, UPPERCASE, DIGITS, SPECIAL]:
        password.append(secrets.choice(required))

    for _ in range(length - len(password)):
        password.append(secrets.choice(LOWERCASE + UPPERCASE + DIGITS + SPECIAL))

    secrets.SystemRandom().shuffle(password)

    return "".join(password)


def generate_password_without_special(length: int = 24) -> str:
    LOWERCASE = string.ascii_lowercase
    UPPERCASE = string.ascii_uppercase
    DIGITS = string.digits

    password = []

    for required in [LOWERCASE, UPPERCASE, DIGITS]:
        password.append(secrets.choice(required))

    for _ in range(length - len(password)):
        password.append(secrets.choice(LOWERCASE + UPPERCASE + DIGITS))

    secrets.SystemRandom().shuffle(password)

    # Ensure at least one special character, this worked last time but more complicated special characters might cause
    # issues, so we just stick with this for now
    return "".join(password) + "!"


def build_generated_password_defaults() -> dict[str, str]:
    generated: dict[str, str] = {}
    for key in DEFAULTS:
        if key.endswith("_PASSWORD") and key != "PROXMOX_PASSWORD":
            generated[key] = generate_password_without_special()
    return generated


def mask_value(value: str, secret: bool) -> str:
    if not value:
        return "<empty>"
    if not secret:
        return value
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * max(4, len(value) - 4)}{value[-2:]}"


def load_current_values() -> dict[str, str]:
    current = dict(DEFAULTS)
    generated_passwords = build_generated_password_defaults()

    for name, value in generated_passwords.items():
        current[name] = value

    for name in current:
        env_value = os.getenv(name)
        if env_value is not None and env_value != "":
            current[name] = env_value

    if ENV_FILE_PATH.exists():
        parsed = dotenv_values(ENV_FILE_PATH)
        for name, value in parsed.items():
            if value is not None:
                current[name] = value

    for name, generated_value in generated_passwords.items():
        if not current.get(name, ""):
            current[name] = generated_value

    return current


def write_credentials_markdown(values: dict[str, str]) -> None:
    groups: list[tuple[str, list[tuple[str, str]]]] = [
        ("Proxmox", [("Host", "PROXMOX_HOST"), ("User", "PROXMOX_USER"), ("Password", "PROXMOX_PASSWORD")]),
        ("Website admin", [("User", "WEBSITE_ADMIN_USER"), ("Password", "WEBSITE_ADMIN_PASSWORD")]),
        ("PostgreSQL", [("Host", "DATABASE_HOST"), ("Port", "DATABASE_PORT"), ("User", "DATABASE_USER"), ("Password", "DATABASE_PASSWORD")]),
        ("Webserver database", [("User", "WEBSERVER_DATABASE_USER"), ("Password", "WEBSERVER_DATABASE_PASSWORD")]),
        ("Backend API", [("Port", "BACKEND_PORT"), ("Authentication token", "BACKEND_AUTHENTICATION_TOKEN"), ("Lecture signup token", "LECTURE_SIGNUP_TOKEN")]),
        ("Monitoring VM", [("Host", "MONITORING_HOST"), ("User", "MONITORING_VM_USER"), ("Password", "MONITORING_VM_PASSWORD")]),
        ("Grafana", [("Port", "GRAFANA_PORT"), ("User", "GRAFANA_USER"), ("Password", "GRAFANA_PASSWORD")]),
        ("ClickHouse", [("HTTPS port", "CLICKHOUSE_HTTPS_PORT"), ("Native port", "CLICKHOUSE_NATIVE_PORT"), ("User", "CLICKHOUSE_USER"), ("Password", "CLICKHOUSE_PASSWORD")]),
        ("Wazuh API", [("Port", "WAZUH_API_PORT"), ("User", "WAZUH_API_USER"), ("Password", "WAZUH_API_PASSWORD")]),
        ("Wazuh dashboard", [("User", "WAZUH_DASHBOARD_USER"), ("Password", "WAZUH_DASHBOARD_PASSWORD")]),
        ("Wazuh indexer", [("User", "WAZUH_INDEXER_USER"), ("Password", "WAZUH_INDEXER_PASSWORD")]),
        ("Wazuh enrollment", [("Password", "WAZUH_ENROLLMENT_PASSWORD")]),
        ("Postgres exporter", [("Port", "POSTGRES_EXPORTER_PORT"), ("Password", "POSTGRES_EXPORTER_PASSWORD")]),
    ]

    lines = [
        "# heiST Credentials",
        "",
        "> Generated by `install.py`. Treat this file as sensitive.",
        "",
    ]

    for title, rows in groups:
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| Field | Value |")
        lines.append("|---|---|")
        for label, key in rows:
            value = values.get(key, DEFAULTS.get(key, ""))
            display = value if value else "<empty>"
            lines.append(f"| {label} | ```{display}``` |")
        lines.append("")

    CREDENTIALS_MD_PATH.write_text("\n".join(lines), encoding="utf-8")


def describe_kind(field_spec: FieldSpec) -> str:
    if field_spec.description:
        return field_spec.description

    kind_map = {
        "secret": "Sensitive value used by the installer.",
        "path": "Absolute filesystem path used by the installer.",
        "port": "TCP port number.",
        "ip": "IPv4 or IPv6 address.",
        "ip_or_host": "Hostname or IP address.",
        "interface": "Interface or address-with-prefix notation.",
        "hostname": "Hostname or node name.",
        "integer": "Whole number value.",
    }
    return kind_map.get(field_spec.kind, "Value used by the installer.")


def validate_value(field_spec: FieldSpec, value: str) -> str:
    value = value.strip()
    if field_spec.required and not value:
        raise ValueError("This value cannot be empty.")

    if not value:
        return value

    if field_spec.kind == "port":
        port = int(value)
        if not 1 <= port <= 65535:
            raise ValueError("Port must be between 1 and 65535.")
    elif field_spec.kind == "integer":
        if not value.isdigit() or int(value) < 0:
            raise ValueError("Enter a non-negative whole number.")
    elif field_spec.kind == "ip":
        try:
            ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError("Enter a valid IP address.") from exc
    elif field_spec.kind == "interface":
        try:
            ipaddress.ip_interface(value)
        except ValueError as exc:
            raise ValueError("Enter an address with prefix, for example 10.0.0.1/24 or fd12::1/64.") from exc
    elif field_spec.kind == "hostname":
        if any(char.isspace() for char in value):
            raise ValueError("Hostnames cannot contain spaces.")
    elif field_spec.kind == "ip_or_host":
        if any(char.isspace() for char in value):
            raise ValueError("This field cannot contain spaces.")

    return value


def render_welcome() -> None:
    clear_screen()
    banner = Text()
    banner.append("heiST Installer", style="bold cyan")
    banner.append("\n", style="white")
    banner.append("A guided setup wizard for first-time onboarding.", style="white")
    banner.append("\n", style="white")
    banner.append("Choose a simple setup for the minimum Proxmox values, or an advanced setup to edit every configuration value used by the installers.", style="dim")

    console.print(
        Panel(
            banner,
            title="[bold white on blue] Welcome [/bold white on blue]",
            subtitle="Step-by-step configuration in the terminal",
            border_style="cyan",
            padding=(1, 2),
        )
    )

    notes = Table.grid(padding=(0, 1))
    notes.add_row("[bold]Simple mode[/bold]", "Only asks for the four Proxmox values most users need to change.")
    notes.add_row("[bold]Advanced mode[/bold]", "Walks through every setup value in themed sections.")
    notes.add_row("[bold]Save only[/bold]", "Writes the resulting `.env` file so you can run the setup later.")
    notes.add_row("[bold]Run now[/bold]", "Saves the `.env` file and then launches the existing setup scripts.")
    console.print(Panel(notes, title="What this wizard does", border_style="blue"))


def choose_mode(preselected: Optional[str] = None) -> str:
    if preselected in {"simple", "advanced"}:
        return preselected

    selected = arrow_select_menu(
        "Mode selection",
        "Select the onboarding mode that fits your installation.",
        [
            "Simple setup (minimum Proxmox values)",
            "Advanced setup (all configuration values)",
        ],
    )
    if selected == 1:
        return "advanced"
    return "simple"


def prompt_with_editable_prefill(prompt_label: str, current: str) -> str:
    """Prompt with the current value prefilled so users can edit in place."""
    if os.name != "nt":
        try:
            import readline

            if sys.stdout.isatty():
                # Wrap ANSI escapes with readline markers so cursor math stays correct.
                prompt_text = f"\001\033[1;36m\002{prompt_label}\001\033[0m\002: "
            else:
                prompt_text = f"{prompt_label}: "

            def startup_hook() -> None:
                readline.insert_text(current)

            readline.set_startup_hook(startup_hook)
            try:
                return input(prompt_text)
            finally:
                readline.set_startup_hook()
        except Exception:
            # Fallback to a normal prompt if readline prefill is unavailable.
            pass

    return Prompt.ask(f"[bold cyan]{prompt_label}[/bold cyan]", default=current, show_default=True)


def prompt_field(field_spec: FieldSpec, current_values: dict[str, str]) -> str:
    clear_screen()
    current = current_values.get(field_spec.name, DEFAULTS.get(field_spec.name, ""))
    help_text = describe_kind(field_spec)

    details = [f"[bold]{field_spec.label}[/bold]"]
    details.append(help_text)
    if field_spec.example:
        details.append(f"[dim]Example:[/dim] {field_spec.example}")
    if current:
        details.append(f"[dim]Current value:[/dim] {mask_value(current, field_spec.secret)}")
    else:
        details.append("[dim]Current value:[/dim] <empty>")

    console.print(Panel("\n".join(details), border_style="green", padding=(1, 2)))

    while True:
        if field_spec.secret:
            answer = Prompt.ask(
                f"[bold cyan]{field_spec.name}[/bold cyan]",
                default=current,
                password=True,
                show_default=False,
            )
        else:
            answer = prompt_with_editable_prefill(field_spec.name, current)

        try:
            validated = validate_value(field_spec, answer)
            return validated
        except ValueError as exc:
            console.print(f"[red]✗ {exc}[/red]")
            console.print("[dim]Please try again.[/dim]")


def sections_for_mode(mode: str) -> list[SectionSpec]:
    if mode == "simple":
        return [SIMPLE_SECTION]
    return ADVANCED_SECTIONS


def section_changed_count(section: SectionSpec, values: dict[str, str], original: dict[str, str]) -> int:
    return sum(1 for spec in section.fields if values.get(spec.name, "") != original.get(spec.name, ""))


def build_section_menu_table(sections: list[SectionSpec], values: dict[str, str], original: dict[str, str]) -> Table:
    table = Table(title="Sections", box=box.ROUNDED, show_lines=False)
    table.add_column("#", style="bold cyan", no_wrap=True)
    table.add_column("Section", style="white")
    table.add_column("Changed", style="magenta", no_wrap=True)

    for idx, section in enumerate(sections, start=1):
        changed = section_changed_count(section, values, original)
        table.add_row(str(idx), section.title, f"{changed}/{len(section.fields)}")
    return table


def build_fields_table(section: SectionSpec, values: dict[str, str], original: dict[str, str]) -> Table:
    table = Table(title=section.title, box=box.ROUNDED, show_lines=False)
    table.add_column("#", style="bold cyan", no_wrap=True)
    table.add_column("Variable", style="white")
    table.add_column("Value", style="white")
    table.add_column("State", style="magenta", no_wrap=True)

    for idx, spec in enumerate(section.fields, start=1):
        value = values.get(spec.name, "")
        changed = value != original.get(spec.name, "")
        state = "changed" if changed else "unchanged"
        if spec.required and not value:
            state = "missing"
        table.add_row(str(idx), spec.name, mask_value(value, spec.secret), state)
    return table


def format_field_menu_option(spec: FieldSpec, value: str, state: str) -> str:
    return f"{spec.name} [{state}] = {mask_value(value, spec.secret)}"


def edit_section_menu(section: SectionSpec, values: dict[str, str], original: dict[str, str]) -> None:
    while True:
        field_options = []
        field_descriptions = []
        for spec in section.fields:
            value = values.get(spec.name, "")
            changed = value != original.get(spec.name, "")
            state = "changed" if changed else "unchanged"
            if spec.required and not value:
                state = "missing"
            field_options.append(format_field_menu_option(spec, value, state))
            field_descriptions.append(describe_kind(spec))

        selected = arrow_select_menu(
            section.title,
            section.subtitle,
            field_options,
            allow_back=True,
            option_details=field_descriptions,
        )
        if selected is None:
            return

        field_spec = section.fields[selected]
        values[field_spec.name] = prompt_field(field_spec, values)


def run_configuration_menu(initial_mode: str, current_values: dict[str, str], original_values: dict[str, str]) -> tuple[dict[str, str], Optional[str]]:
    mode = initial_mode
    values = current_values

    while True:
        visible_sections = sections_for_mode(mode)
        total_changed = sum(1 for name, value in values.items() if original_values.get(name, "") != value)

        menu_items: list[tuple[str, Optional[int]]] = []
        menu_options: list[str] = []
        for idx, section in enumerate(visible_sections):
            changed = section_changed_count(section, values, original_values)
            menu_items.append(("section", idx))
            menu_options.append(f"Edit section: {section.title} ({changed}/{len(section.fields)} changed)")

        action_start_index = len(menu_options)
        if mode == "simple":
            menu_items.append(("advanced", None))
            menu_options.append("Switch to advanced mode")
        else:
            menu_items.append(("simple", None))
            menu_options.append("Switch to simple mode")

        menu_items.extend([
            ("review", None),
            ("save", None),
            ("quit", None),
        ])
        menu_options.extend([
            "Review changed values",
            "Save configuration and continue",
            "Exit without saving",
        ])

        selected = arrow_select_menu(
            "Configuration menu",
            "\n".join([
                f"Mode: {mode}",
                f"Changed values: {total_changed}",
                "Use arrow keys to choose a section or action.",
            ]),
            menu_options,
            divider_before=action_start_index,
            action_start_index=action_start_index,
        )

        action, index = menu_items[selected]

        if action == "review":
            changed_keys = [name for name, value in values.items() if original_values.get(name, "") != value]
            clear_screen()
            console.print(build_review_table(values, changed_keys))
            Prompt.ask("[dim]Press Enter to return to the menu[/dim]", default="", show_default=False)
            continue

        if action == "save":
            if not confirm_and_save(values, original_values):
                continue
            action = choose_action(mode)
            return values, action

        if action == "quit":
            has_unsaved_changes = any(original_values.get(name, "") != value for name, value in values.items())
            if has_unsaved_changes and not Confirm.ask("Discard unsaved changes and exit?", default=False):
                continue
            return values, None

        if action == "advanced" and mode == "simple":
            mode = "advanced"
            continue

        if action == "simple" and mode == "advanced":
            mode = "simple"
            continue

        if action == "section" and index is not None:
            edit_section_menu(visible_sections[index], values, original_values)
            continue

    raise RuntimeError("Configuration menu exited unexpectedly.")


def build_review_table(values: dict[str, str], changed_keys: Iterable[str]) -> Table:
    table = Table(title="Configuration review", box=box.ROUNDED, show_lines=False)
    table.add_column("Variable", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_column("Mode", style="magenta", no_wrap=True)

    changed = set(changed_keys)
    if not changed:
        table.add_row("(no changes)", "All values kept from the current configuration or defaults.", "saved")
        return table

    # Use the deduplicated ordered list so each variable appears only once.
    ordered_specs = [spec for spec in ALL_FIELD_SPECS if spec.name in changed]
    for spec in ordered_specs:
        value = values.get(spec.name, "")
        display = mask_value(value, spec.secret)
        table.add_row(spec.name, display, "changed")
    return table


def confirm_and_save(values: dict[str, str], original: dict[str, str]) -> bool:
    changed_keys = [name for name, value in values.items() if original.get(name, "") != value]
    clear_screen()
    console.print(build_review_table(values, changed_keys))

    summary = Panel(
        "\n".join([
            f"[bold]Output file:[/bold] {ENV_FILE_PATH}",
            f"[bold]Changed values:[/bold] {len(changed_keys)}",
            "[dim]Secrets are masked in this preview.[/dim]",
        ]),
        title="Review your configuration",
        border_style="cyan",
    )
    console.print(summary)

    if not Confirm.ask("Save these values to `.env`?", default=True):
        return False

    write_env_file(values)
    return True


def prompt_save_on_interrupt(values: dict[str, str], original: dict[str, str]) -> None:
    changed_count = sum(1 for name, value in values.items() if original.get(name, "") != value)
    clear_screen()
    console.print(
        Panel(
            "\n".join([
                "[yellow]Wizard cancelled with Ctrl-C.[/yellow]",
                f"Unsaved changed values: [bold]{changed_count}[/bold]",
            ]),
            title="Exit requested",
            border_style="yellow",
        )
    )

    #if changed_count == 0:
    #    console.print("[yellow]No unsaved changes to write.[/yellow]")
    #    raise SystemExit(1)

    if Confirm.ask("Save current values to `.env` before exiting?", default=True):
        write_env_file(values)
        console.print("[green]Current values were saved.[/green]")
    else:
        console.print("[yellow]Changes were discarded.[/yellow]")

    raise SystemExit(1)


def write_env_file(values: dict[str, str]) -> None:
    ENV_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)

    sections = [
        ("Core Proxmox / Installer", ["PROXMOX_HOST", "PROXMOX_USER", "PROXMOX_PASSWORD", "PROXMOX_PORT", "BACKEND_PORT", "PROXMOX_INTERNAL_IP", "PROXMOX_EXTERNAL_IP", "PROXMOX_HOSTNAME", "UBUNTU_BASE_SERVER_URL"]),
        ("Backend / Database / Webserver", ["DATABASE_FILES_DIR", "DATABASE_NAME", "DATABASE_USER", "DATABASE_PASSWORD", "DATABASE_PORT", "DATABASE_HOST", "WEBSERVER_FILES_DIR", "WEBSERVER_USER", "WEBSERVER_GROUP", "WEBSERVER_ROOT", "WEBSERVER_HOST", "WEBSERVER_HTTP_PORT", "WEBSERVER_HTTPS_PORT", "BACKEND_FILES_DIR", "WEBSERVER_DATABASE_USER", "WEBSERVER_DATABASE_PASSWORD", "WEBSITE_ADMIN_USER", "WEBSITE_ADMIN_PASSWORD", "BACKEND_AUTHENTICATION_TOKEN", "LECTURE_SIGNUP_TOKEN", "BACKEND_LOGGING_DIR"]),
        ("Networking / VPN / VM Import", ["OPENVPN_SUBNET", "OPENVPN_SERVER_IP", "BACKEND_NETWORK_SUBNET", "BACKEND_NETWORK_ROUTER", "BACKEND_NETWORK_DEVICE", "BACKEND_NETWORK_HOST_MIN", "BACKEND_NETWORK_HOST_MAX", "DATABASE_MAC_ADDRESS", "WEBSERVER_MAC_ADDRESS", "CHALLENGES_ROOT_SUBNET", "CHALLENGES_ROOT_SUBNET_MASK"]),
        ("Monitoring VM", ["MONITORING_FILES_DIR", "MONITORING_VPN_INTERFACE", "MONITORING_DMZ_INTERFACE", "MONITORING_HOST", "MONITORING_VM_ID", "MONITORING_VM_NAME", "MONITORING_VM_MAC_ADDRESS", "MONITORING_VM_MEMORY", "MONITORING_VM_CORES", "MONITORING_VM_DISK", "MONITORING_VM_USER", "MONITORING_VM_PASSWORD", "PROXMOX_LVM_STORAGE", "PROXMOX_SSH_KEYFILE", "PROXMOX_EXPORTER_TOKEN_NAME", "WAZUH_NETWORK_DEVICE", "WAZUH_NETWORK_DEVICE_IPV6", "WAZUH_NETWORK_DEVICE_CIDR", "WAZUH_NETWORK_SUBNET", "WAZUH_MANAGER_IPV6", "CLOUD_INIT_NETWORK_DEVICE", "CLOUD_INIT_NETWORK_DEVICE_IP", "CLOUD_INIT_NETWORK_DEVICE_CIDR", "CLOUD_INIT_NETWORK_SUBNET", "MONITORING_DNS"]),
        ("Grafana / Prometheus / Exporters", ["GRAFANA_PORT", "GRAFANA_USER", "GRAFANA_PASSWORD", "GRAFANA_FILES_SETUP_DIR", "GRAFANA_FILES_DIR", "PROMETHEUS_PORT", "POSTGRES_EXPORTER_PORT", "POSTGRES_EXPORTER_PASSWORD", "PROXMOX_EXPORTER_PORT", "MONITORING_VM_EXPORTER_PORT", "DATABASE_VM_EXPORTER_PORT", "WEBSERVER_VM_EXPORTER_PORT", "WEBSERVER_APACHE_EXPORTER_PORT", "PROXMOX_NODE_EXPORTER_PORT"]),
        ("Wazuh", ["WAZUH_MANAGER_PORT", "WAZUH_API_PORT", "WAZUH_API_USER", "WAZUH_API_PASSWORD", "WAZUH_DASHBOARD_USER", "WAZUH_DASHBOARD_PASSWORD", "WAZUH_INDEXER_USER", "WAZUH_INDEXER_PASSWORD", "WAZUH_ENROLLMENT_PASSWORD", "WAZUH_REGISTRATION_PORT", "WAZUH_COMMUNICATION_PORT", "WAZUH_FILE_DIR"]),
        ("ClickHouse / Vector / Suricata / Zeek / Logrotate", ["CLICKHOUSE_HTTPS_PORT", "CLICKHOUSE_NATIVE_PORT", "CLICKHOUSE_USER", "CLICKHOUSE_PASSWORD", "CLICKHOUSE_SQL_DIR", "VECTOR_FILES_DIR", "VECTOR_DIR", "SURICATA_LOG_DIR", "SURICATA_FILES_DIR", "SURICATA_RULES_DIR", "ZEEK_SITE_DIR", "LOGROTATE_CONFIG_DIR", "ROTATE_DAYS", "PCAP_ROTATION_INTERVAL", "DNSMASQ_BACKEND_DIR", "SSL_TLS_CERTS_DIR", "PVE_EXPORTER_DIR", "IPTABLES_FILE"]),
    ]

    with ENV_FILE_PATH.open("w", encoding="utf-8") as env_file:
        env_file.write("# Generated by the heiST onboarding wizard\n")
        env_file.write(f"# Generated from: {Path(__file__).name}\n\n")

        for section_name, keys in sections:
            env_file.write(f"# ===== {section_name} =====\n")
            for key in keys:
                value = values.get(key, DEFAULTS.get(key, ""))
                env_file.write(f"{key}={format_env_value(str(value))}\n")
            env_file.write("\n")

    write_credentials_markdown(values)

    console.print(
        Panel(
            "\n".join([
                f"Saved configuration to [bold]{ENV_FILE_PATH}[/bold]",
                f"Saved credentials summary to [bold]{CREDENTIALS_MD_PATH}[/bold]",
            ]),
            title="Done",
            border_style="green",
        )
    )


def run_command(command: list[str], cwd: Path) -> None:
    pretty = " ".join(shlex.quote(part) for part in command)
    console.print(Panel(pretty, title=f"Running in {cwd}", border_style="yellow"))

    # Run the command inheriting the parent's stdout/stderr so the child
    # process writes directly to the terminal. This avoids invisible/latency
    # caused by capturing + buffering and makes the output visible in real time.
    # Use check_call to raise on non-zero exit.
    try:
        subprocess.check_call(command, cwd=str(cwd))
    except subprocess.CalledProcessError:
        # Re-raise to allow upstream handling and consistent behavior.
        raise


def choose_action(mode: str) -> str:
    options = [
        "Save only",
        "Save and run setup",
    ]

    selected = arrow_select_menu(
        "Post-save action",
        "Choose what should happen after saving the `.env` file.",
        options,
    )

    if selected == 0:
        return "save"
    return "both"


def run_selected_action(action: str) -> None:
    if action == "save":
        return

    console.print(Panel("[bold]Tip:[/bold] the wizard already saved the final `.env` file before running anything.", border_style="blue"))

    run_command([sys.executable, "-m", "setup.setup"], PROJECT_ROOT)
    run_command([sys.executable, "-m", "setup.setup_monitoring"], PROJECT_ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive onboarding wizard for heiST")
    parser.add_argument("--mode", choices=["simple", "advanced"], help="Skip the first menu and start in the selected mode.")
    args = parser.parse_args()

    current_values: dict[str, str] = {}
    original_values: dict[str, str] = {}

    try:
        render_welcome()
        current_values = load_current_values()
        original_values = dict(current_values)

        mode = choose_mode(args.mode)
        _, action = run_configuration_menu(mode, current_values, original_values)
        if action is None:
            console.print("[yellow]No changes were saved.[/yellow]")
            raise SystemExit(0)

        run_selected_action(action)

        console.print(Panel("[bold green]Setup wizard complete.[/bold green]\nYou can re-run this tool any time to update the configuration.", border_style="green"))

    except KeyboardInterrupt:
        try:
            prompt_save_on_interrupt(current_values, original_values)
        except KeyboardInterrupt:
            console.print("\n[yellow]Setup wizard cancelled by user without saving.[/yellow]")
            raise SystemExit(1)
    except subprocess.CalledProcessError as exc:
        console.print(Panel(f"[red]A setup command failed with exit code {exc.returncode}.[/red]\nReview the command output above, fix the issue, and run the wizard again.", title="Setup failed", border_style="red"))
        raise SystemExit(exc.returncode)
    except Exception as exc:
        console.print(Panel(f"[red]Unexpected error:[/red] {exc}", title="Setup failed", border_style="red"))
        raise SystemExit(1)


if __name__ == "__main__":
    main()

