"""Checkout paths shared by installer bootstrap and UI."""
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
REQUIREMENTS_PATH = SCRIPT_DIR / "requirements.txt"
ENV_FILE_PATH = SCRIPT_DIR / ".env"
CREDENTIALS_MD_PATH = SCRIPT_DIR / "credentials.md"
BOOTSTRAP_SENTINEL_ENV = "HEIST_TUI_BOOTSTRAPPED"
