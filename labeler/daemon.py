"""launchd Launch Agent lifecycle management."""

import logging
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from labeler import pause as pause_file
from labeler import report
from labeler.config import CONFIG_DIR

logger = logging.getLogger(__name__)

LABEL = "com.image-labeler"
PLIST_NAME = f"{LABEL}.plist"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / PLIST_NAME
LOG_PATH = CONFIG_DIR / "daemon.log"
EXIT_TIMEOUT_S = 150


def _homebrew_opt_path(path: Path) -> str:
    parts = path.parts
    if "Cellar" in parts:
        cellar = parts.index("Cellar")
        formula = parts[cellar + 1]
        opt = Path(*parts[:cellar], "opt", formula, *parts[cellar + 3 :])
        if opt.exists():
            return str(opt)
    return str(path)


def _get_python_path() -> str:
    return _homebrew_opt_path(Path(sys.executable))


def _get_labeler_module_path() -> str:
    """Get the path to run `python -m labeler`."""
    return _homebrew_opt_path(Path(__file__).resolve().parent.parent)


def _generate_plist() -> dict:
    working_dir = _get_labeler_module_path()
    return {
        "Label": LABEL,
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
        "ExitTimeOut": EXIT_TIMEOUT_S,
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin",
        },
    }


def start():
    """Install and load the launchd Launch Agent."""
    if is_running():
        print("Daemon is already running.")
        return

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    pause_file.resume()

    plist = _generate_plist()
    with PLIST_PATH.open("wb") as f:
        plistlib.dump(plist, f)

    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)
    print(f"Daemon started. Logs: {LOG_PATH}")


def stop():
    """Unload and remove the launchd Launch Agent."""
    if not PLIST_PATH.exists():
        print("Daemon is not running (no plist found).")
        return

    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=False)
    PLIST_PATH.unlink(missing_ok=True)
    print("Daemon stopped.")


def restart():
    """Stop and restart the launchd Launch Agent."""
    stop()
    start()


def status():
    """Print whether the Launch Agent is currently running."""
    if not is_running():
        print("Daemon is not running.")
        return
    found = pause_file.active()
    if found is None:
        print("Daemon is running.")
    elif found.resumes_at is not None:
        print(f"Daemon is paused until {pause_file.clock_time(found.resumes_at)}.")
    else:
        print(
            f"Daemon is paused since {pause_file.clock_time(found.since)}. It stops "
            f"at {pause_file.clock_time(found.stops_at)} unless you run "
            "'icloud-image-labeler daemon resume'."
        )
    print()
    print(report.build(LOG_PATH))


def pause(minutes: int | None = None):
    pause_file.pause(minutes)
    found = pause_file.current()
    if found.resumes_at is not None:
        print(
            f"Paused until {pause_file.clock_time(found.resumes_at)}. Requests "
            "already sent to the LLM finish, but nothing new is exported or "
            "written to Photos until then."
        )
        print("Run 'icloud-image-labeler daemon resume' to carry on sooner.")
        return
    print(
        "Paused. Requests already sent to the LLM finish, but nothing new is "
        "exported or written to Photos."
    )
    print(
        "Run 'icloud-image-labeler daemon resume' before "
        f"{pause_file.clock_time(found.stops_at)}, or the daemon stops and stays "
        "stopped."
    )


def resume():
    found = pause_file.active()
    pause_file.resume()
    if found is None:
        print("Not paused.")
    elif found.has_expired():
        print(
            "The pause went past an hour, so the daemon stopped. Start it again "
            "with 'icloud-image-labeler daemon start'."
        )
    else:
        print("Resumed.")


def is_this_process() -> bool:
    return os.environ.get("XPC_SERVICE_NAME") == LABEL


def remove_from_launchd():
    logger.info(
        "Removing the launch agent, so the daemon doesn't start again until "
        "'icloud-image-labeler daemon start'"
    )
    PLIST_PATH.unlink(missing_ok=True)
    subprocess.run(["launchctl", "remove", LABEL], check=False)


def is_running() -> bool:
    """Check if the Launch Agent is loaded in launchctl."""
    result = subprocess.run(
        ["launchctl", "list"],
        capture_output=True,
        text=True,
    )
    return LABEL in result.stdout
