"""Verify external tool dependencies at startup."""

import shutil
import subprocess
import sys


def check_dependencies():
    """Check that required external tools are available. Exits if any are missing."""
    missing = []

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            missing.append(tool)

    if not shutil.which("pgrep"):
        missing.append("pgrep")

    # Check Photos.app exists
    result = subprocess.run(
        ["mdfind", "kMDItemCFBundleIdentifier == 'com.apple.Photos'"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        missing.append("Photos.app")

    if missing:
        print(f"Error: missing required dependencies: {', '.join(missing)}", file=sys.stderr)
        if {"ffmpeg", "ffprobe"} & set(missing):
            print("  Install ffmpeg: brew install ffmpeg", file=sys.stderr)
        if "Photos.app" in missing:
            print("  Photos.app is required on macOS", file=sys.stderr)
        sys.exit(1)
