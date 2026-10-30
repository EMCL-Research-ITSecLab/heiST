"""Checkout paths shared by installer bootstrap and UI."""
from pathlib import Path
from heist.environment import environment_file

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
REQUIREMENTS_PATH = SCRIPT_DIR / "requirements.txt"
ENV_FILE_PATH = environment_file("installer")
CREDENTIALS_MD_PATH = PROJECT_ROOT / "config/credentials.md"
BOOTSTRAP_SENTINEL_ENV = "HEIST_TUI_BOOTSTRAPPED"
