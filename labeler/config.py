"""Configuration file management for ~/.image-labeler/config.json."""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".image-labeler"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS = {
    "base_url": "http://localhost:1234/v1",
    "api_key": "",
    "model": "google/gemma-4-e4b",
    "servers": [],
    "poll_interval": 21600,
    "limit_per_cycle": 0,
    "days": 0,
    "to_days": 0,
    "threads": 4,
    "video_frames": 5,
    "max_dimension": 1024,
    "photo": True,
    "video": True,
    "write": True,
}

VALID_KEYS = set(DEFAULTS.keys())


def ensure_config() -> dict:
    """Load config from disk, creating defaults if missing."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULTS, indent=2) + "\n")
        return dict(DEFAULTS)
    with CONFIG_PATH.open() as f:
        config = json.load(f)
    return {**DEFAULTS, **config}


def load_config() -> dict:
    """Load configuration from disk, creating defaults if the file is missing."""
    return ensure_config()


def save_config(config: dict):
    """Write configuration dictionary to disk, filtering to known keys."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    filtered = {k: v for k, v in config.items() if k in VALID_KEYS}
    CONFIG_PATH.write_text(json.dumps(filtered, indent=2) + "\n")


def _parse_server_spec(spec: str) -> dict:
    """Parse a 'url|model[|api_key]' spec into a server dict."""
    parts = [p.strip() for p in spec.split("|")]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError(
            f"Invalid server spec {spec!r}. Expected 'base_url|model[|api_key]'."
        )
    server = {"base_url": parts[0], "model": parts[1]}
    if len(parts) >= 3 and parts[2]:
        server["api_key"] = parts[2]
    return server


def resolve_servers(cfg: dict) -> list[dict]:
    """Return the effective list of server configs, falling back to legacy keys."""
    servers = cfg.get("servers") or []
    if servers:
        return [dict(s) for s in servers]
    return [
        {
            "base_url": cfg.get("base_url", ""),
            "model": cfg.get("model", ""),
            "api_key": cfg.get("api_key", ""),
        }
    ]


def set_value(key: str, value: str):
    """Update a single config key, coercing the string value to the correct type."""
    if key not in VALID_KEYS:
        raise ValueError(
            f"Unknown config key: {key}. Valid keys: {', '.join(sorted(VALID_KEYS))}"
        )
    config = load_config()
    # Coerce type based on defaults
    default_val = DEFAULTS[key]
    if isinstance(default_val, bool):
        config[key] = value.lower() in ("true", "1", "yes")
    elif isinstance(default_val, int):
        config[key] = int(value)
    elif isinstance(default_val, list):
        # Comma-separated 'url|model[|api_key]' specs
        specs = [s.strip() for s in value.split(",") if s.strip()]
        config[key] = [_parse_server_spec(s) for s in specs]
    else:
        config[key] = value
    save_config(config)


def reset_config():
    """Reset configuration to default values."""
    save_config(DEFAULTS)
