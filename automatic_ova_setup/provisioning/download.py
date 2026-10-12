import shutil
from pathlib import Path

from .process import run_command


def download_file(url, dest: Path, label: str):
    if dest.exists():
        print(f"{label} already downloaded: {dest}")
        return
    print(f"Downloading {label} -> {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    run_command(["curl", "-L", "--fail", "-o", str(tmp), url])
    tmp.rename(dest)
    print(f"Downloaded {label}")


def create_iso(src_dir: Path, iso_path: Path):
    """Build a small ISO (autounattend + setup.ps1) using genisoimage/xorriso."""
    tool = shutil.which("genisoimage") or shutil.which("mkisofs") or shutil.which("xorriso")
    if tool is None:
        raise RuntimeError(
            "Need genisoimage, mkisofs, or xorriso installed on the host "
            "(e.g. `apt install genisoimage`) to build the autounattend ISO."
        )
    if "xorriso" in tool:
        cmd = [tool, "-as", "genisoimage", "-J", "-R", "-o", str(iso_path), str(src_dir)]
    else:
        cmd = [tool, "-J", "-R", "-o", str(iso_path), str(src_dir)]
    run_command(cmd)
