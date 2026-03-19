import logging
import plistlib
import subprocess
import sys
from pathlib import Path

from labeler.config import CONFIG_DIR

logger = logging.getLogger(__name__)

PLIST_NAME = "com.image-labeler.plist"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / PLIST_NAME
LOG_PATH = CONFIG_DIR / "daemon.log"


def _get_python_path() -> str:
    return sys.executable


def _get_labeler_module_path() -> str:
    """Get the path to run `python -m labeler`."""
    return str(Path(__file__).resolve().parent.parent)


def _generate_plist() -> dict:
    working_dir = _get_labeler_module_path()
    return {
        "Label": "com.image-labeler",
        "ProgramArguments": [
            _get_python_path(),
            "-m",
            "labeler",
            "run",
            "--loop",
        ],
        "WorkingDirectory": working_dir,
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin",
        },
    }


def start():
    if is_running():
        print("Daemon is already running.")
        return

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    plist = _generate_plist()
    with PLIST_PATH.open("wb") as f:
        plistlib.dump(plist, f)

    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)
    print(f"Daemon started. Logs: {LOG_PATH}")


def stop():
    if not PLIST_PATH.exists():
        print("Daemon is not running (no plist found).")
        return

    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=False)
    PLIST_PATH.unlink(missing_ok=True)
    print("Daemon stopped.")


def restart():
    stop()
    start()


def status():
    if is_running():
        print("Daemon is running.")
    else:
        print("Daemon is not running.")


def is_running() -> bool:
    result = subprocess.run(
        ["launchctl", "list"],
        capture_output=True,
        text=True,
    )
    return "com.image-labeler" in result.stdout
