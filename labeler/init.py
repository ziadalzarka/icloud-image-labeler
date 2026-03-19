"""Interactive first-run setup wizard."""

import json
import sys

from openai import OpenAI

from labeler.config import CONFIG_PATH, DEFAULTS, load_config, save_config


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"{label}{suffix}: ").strip()
    return val or default


def _test_connection(base_url: str, api_key: str) -> list[str] | None:
    """Try to list models from the endpoint. Returns model IDs or None on failure."""
    try:
        client = OpenAI(base_url=base_url, api_key=api_key or "not-needed")
        models = client.models.list()
        return [m.id for m in models.data]
    except Exception:
        return None


def _pick_model(models: list[str]) -> str:
    print(f"\nAvailable models:")
    for i, m in enumerate(models, 1):
        print(f"  {i}. {m}")
    while True:
        choice = input(f"\nSelect model [1]: ").strip()
        if not choice:
            return models[0]
        try:
            idx = int(choice)
            if 1 <= idx <= len(models):
                return models[idx - 1]
        except ValueError:
            # Allow typing the model name directly
            if choice in models:
                return choice
        print(f"  Please enter 1-{len(models)} or a model name.")


def run_init():
    """Interactive setup wizard."""
    if CONFIG_PATH.exists():
        cfg = load_config()
        print(f"Existing config found at {CONFIG_PATH}")
        resp = input("Overwrite? [y/N]: ").strip().lower()
        if resp not in ("y", "yes"):
            print("Keeping existing config.")
            return
    else:
        cfg = dict(DEFAULTS)

    print("\n--- iCloud Image Labeler Setup ---\n")

    # Base URL
    base_url = _prompt("LLM endpoint URL", cfg["base_url"])
    api_key = _prompt("API key (optional, press Enter to skip)", cfg["api_key"])

    # Test connection
    print(f"\nConnecting to {base_url}...")
    models = _test_connection(base_url, api_key)

    if models is None:
        print(f"Could not connect to {base_url}.")
        print("Make sure your LLM server is running and try again,")
        print("or continue with manual model name entry.\n")
        model = _prompt("Model name", cfg["model"])
    elif not models:
        print("Connected, but no models found.")
        model = _prompt("Model name", cfg["model"])
    else:
        print(f"Connected! Found {len(models)} model(s).")
        model = _pick_model(models)

    cfg["base_url"] = base_url
    cfg["api_key"] = api_key
    cfg["model"] = model

    save_config(cfg)
    print(f"\nConfig saved to {CONFIG_PATH}")
    print(f"\n  base_url: {base_url}")
    print(f"  model:    {model}")
    print(f"\nRun 'icloud-image-labeler run' to start labeling.")
    print("Run 'icloud-image-labeler config show' to see all settings.")
