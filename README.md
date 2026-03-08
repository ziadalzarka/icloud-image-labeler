# Image Labeler

Auto-label your iCloud Photos library using a local LLM via LM Studio. Generates keywords, titles, descriptions, and OCR text for photos and videos.

## Requirements

- macOS (requires Photos.app)
- Python 3.11+
- [LM Studio](https://lmstudio.ai/) running on local network
- [ffmpeg](https://ffmpeg.org/) (for video frame extraction)

```sh
brew install ffmpeg
pip install -r requirements.txt
```

## Usage

```sh
# Process all unprocessed media (default: write metadata to Photos.app)
python -m labeler

# Process 5 items from the last 30 days
python -m labeler run --limit 5 --days 30

# Preview without writing (dry run)
python -m labeler run --dry-run

# Photos only, skip videos
python -m labeler run --no-video

# Process media from 60 to 30 days ago
python -m labeler run --days 60 --to-days 30
```

## Configuration

Config is stored at `~/.image-labeler/config.json` and auto-created on first run.

```sh
python -m labeler config show          # View current config
python -m labeler config set days 14   # Update a value
python -m labeler config reset         # Reset to defaults
python -m labeler config path          # Print config file path
```

Key config values:

| Key | Default | Description |
|-----|---------|-------------|
| `base_url` | `http://devbox.local:1234/v1` | LM Studio API URL |
| `model` | `qwen/qwen3.5-9b` | Model name |
| `days` | `0` | Look back N days (0 = all) |
| `to_days` | `0` | Skip most recent N days |
| `limit_per_cycle` | `0` | Items per cycle (0 = all) |
| `threads` | `4` | Max parallel photo threads |
| `video_frames` | `5` | Frames to extract from videos |
| `max_dimension` | `1024` | Max image dimension (px) |
| `poll_interval` | `300` | Daemon poll interval (seconds) |

## Daemon

Run as a background service that auto-starts on login:

```sh
python -m labeler daemon start     # Install and start Launch Agent
python -m labeler daemon status    # Check if running
python -m labeler daemon restart   # Apply config changes
python -m labeler daemon stop      # Uninstall Launch Agent
```

The daemon runs as a macOS Launch Agent (`~/Library/LaunchAgents/com.image-labeler.plist`). It auto-restarts on crash and starts on login. Logs are written to `~/.image-labeler/daemon.log`.
