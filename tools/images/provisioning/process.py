import subprocess
import time


def run_command(cmd, check=True, wait_time=0, capture=False):
    """Run a shell command, printing it first."""
    print(f"$ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, capture_output=capture, text=True)
    if wait_time:
        time.sleep(wait_time)
    if check and result.returncode != 0:
        stderr = result.stderr if capture else "(see output above)"
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(str(c) for c in cmd)}\n{stderr}")
    return result
