import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".image-labeler"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS = {
    "base_url": "http://localhost:1234/v1",
    "api_key": "",
    "model": "qwen/qwen3.5-9b",
    "poll_interval": 300,
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
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    merged = {**DEFAULTS, **config}
    return merged


def load_config() -> dict:
    return ensure_config()


def save_config(config: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    filtered = {k: v for k, v in config.items() if k in VALID_KEYS}
    CONFIG_PATH.write_text(json.dumps(filtered, indent=2) + "\n")


def set_value(key: str, value: str):
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
    else:
        config[key] = value
    save_config(config)


def reset_config():
    save_config(DEFAULTS)
