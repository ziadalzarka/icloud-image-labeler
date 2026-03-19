# iCloud Image Labeler

Auto-label your Apple Photos library using any OpenAI-compatible LLM. Generates keywords, titles, descriptions, and OCR text for photos and videos, then writes the metadata back into Photos.app.

Works with any OpenAI-compatible API — designed for [LM Studio](https://lmstudio.ai/) but also works with Ollama, vLLM, or cloud providers.

## How It Works

```
Photos.app ──> Discovery ──> Export ──> LLM ──> Writer ──> Photos.app
               (osxphotos)   (Pillow)   (API)   (PhotoScript)
```

1. **Discovery** — Queries the Photos library for media with no keywords set, filtered by date range and media type.
2. **Export** — Exports photos as JPEG (with HEIC/iCloud fallbacks), extracts frames from videos via ffmpeg.
3. **LLM** — Sends images to an OpenAI-compatible API. Returns structured JSON with keywords, title, description, and OCR text.
4. **Writer** — Writes metadata back into Photos.app via PhotoScript (AppleScript automation).

Photos are processed in parallel (configurable thread count), videos sequentially.

## Requirements

- macOS (requires Photos.app and AppleScript)
- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) (for video frame extraction)
- An OpenAI-compatible LLM API ([LM Studio](https://lmstudio.ai/), Ollama, etc.)

## Installation

```sh
brew tap ziadalzarka/tap
brew install icloud-image-labeler
```

### iCloud Settings

For best performance, go to **System Settings → Apple Account → iCloud → Photos** and enable **Download Originals to this Mac**. This downloads all photos in advance so the labeler doesn't have to wait for individual iCloud downloads during processing.

## Quick Start

```sh
# Interactive setup — connects to your LLM and picks a model
icloud-image-labeler init

# Process all unprocessed media
icloud-image-labeler run
```

## Usage

```sh
# Process 5 items from the last 30 days
icloud-image-labeler run --limit 5 --days 30

# Preview without writing (dry run)
icloud-image-labeler run --dry-run

# Photos only, skip videos
icloud-image-labeler run --no-video

# Process media from 60 to 30 days ago
icloud-image-labeler run --days 60 --to-days 30

# Process specific photos by UUID
icloud-image-labeler run --uuid ABC123 DEF456

# Run continuously (daemon-style loop)
icloud-image-labeler run --loop

# Use a specific model or API endpoint
icloud-image-labeler run --base-url http://localhost:1234/v1 --model my-model

# Debug logging
icloud-image-labeler run -v
```

### All `run` Options

| Flag | Description |
|------|-------------|
| `--limit N` | Max items to process |
| `--days N` | Look back N days (0 = all time) |
| `--to-days N` | Skip most recent N days |
| `--photo` / `--no-photo` | Include/exclude photos |
| `--video` / `--no-video` | Include/exclude videos |
| `--write` | Force write metadata |
| `--dry-run` | Preview without writing |
| `--base-url URL` | LLM API endpoint |
| `--api-key KEY` | API key for LLM |
| `--model NAME` | Model identifier |
| `--threads N` | Parallel photo threads |
| `--video-frames N` | Frames to extract per video |
| `--uuid UUID [...]` | Process specific photo UUIDs |
| `--loop` | Run continuously with poll interval |
| `-v, --verbose` | Debug logging |

## Configuration

Config is stored at `~/.image-labeler/config.json`. Run `icloud-image-labeler init` for interactive setup, or manage directly:

```sh
icloud-image-labeler config show          # View current config
icloud-image-labeler config set days 14   # Update a value
icloud-image-labeler config reset         # Reset to defaults
icloud-image-labeler config path          # Print config file path
```

If no config exists when you run `icloud-image-labeler run`, the setup wizard launches automatically.

| Key | Default | Description |
|-----|---------|-------------|
| `base_url` | `http://localhost:1234/v1` | OpenAI-compatible API endpoint |
| `api_key` | `""` | API key (optional, empty for local LM Studio) |
| `model` | `qwen/qwen3.5-9b` | Model identifier |
| `days` | `0` | Look back N days (0 = all time) |
| `to_days` | `0` | Skip most recent N days |
| `limit_per_cycle` | `0` | Items per cycle (0 = all) |
| `threads` | `4` | Max parallel photo threads |
| `video_frames` | `5` | Frames to extract from videos |
| `max_dimension` | `1024` | Max image dimension sent to LLM (px) |
| `photo` | `true` | Include photos in processing |
| `video` | `true` | Include videos in processing |
| `write` | `true` | Write metadata to Photos.app |
| `poll_interval` | `300` | Seconds between cycles in loop/daemon mode |

## Daemon

Run as a background service that auto-starts on login via macOS Launch Agent:

```sh
icloud-image-labeler daemon start     # Install and start Launch Agent
icloud-image-labeler daemon status    # Check if running
icloud-image-labeler daemon restart   # Apply config changes
icloud-image-labeler daemon stop      # Uninstall Launch Agent
```

The daemon runs as `com.image-labeler` under `~/Library/LaunchAgents/`. It auto-restarts on crash and starts on login. Logs go to `~/.image-labeler/daemon.log`.

## Metrics

Processing metrics are stored in SQLite at `~/.image-labeler/metrics.db`.

```sh
icloud-image-labeler metrics serve              # Open Datasette UI at http://localhost:8001
icloud-image-labeler metrics serve --port 9000  # Custom port
icloud-image-labeler metrics path               # Print database path
```

**Per-item metrics:** export/LLM/write durations, image dimensions, LLM retry count, keyword count, OCR presence, error details, and model used.

**Per-run metrics:** items found/processed/failed, wall-clock duration, model, thread count, and average LLM latency.

## Architecture

```
labeler/
  cli.py        — argparse CLI (init, run, daemon, config, metrics subcommands)
  init.py       — interactive first-run setup wizard
  config.py     — ~/.image-labeler/config.json management
  discovery.py  — osxphotos query for unprocessed media
  exporter.py   — photo export (HEIC/iCloud fallbacks), video frame extraction
  llm.py        — OpenAI-compatible client, JSON parsing, retry logic
  processor.py  — batch orchestration, parallel photos + sequential videos
  writer.py     — PhotoScript metadata writes (thread-safe)
  metrics.py    — SQLite metrics recording
  daemon.py     — macOS Launch Agent lifecycle
  shutdown.py   — graceful shutdown (SIGINT/SIGTERM handling)
  checks.py     — pre-flight dependency checks (ffmpeg, Photos.app)
```

## License

MIT
