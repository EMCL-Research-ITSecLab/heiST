"""Explicit installer bootstrap. Never executed during import or --help."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import re
from setup.paths import SCRIPT_DIR, PROJECT_ROOT, REQUIREMENTS_PATH, ENV_FILE_PATH, CREDENTIALS_MD_PATH, BOOTSTRAP_SENTINEL_ENV

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


def _parse_debian_version_full() -> str | None:
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


def _bootstrap_into_project_venv(arguments) -> None:
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
    os.execvpe(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *arguments], env)


def bootstrap_requirements(arguments=()) -> None:
    try:
        if _is_running_in_venv():
            install_python_dependencies()
            return

        if os.environ.get(BOOTSTRAP_SENTINEL_ENV) != "1":
            install_system_dependencies()

        _bootstrap_into_project_venv(arguments)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Failed to install installer requirements (exit code {exc.returncode}).") from exc


