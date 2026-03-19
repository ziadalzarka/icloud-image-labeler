# Technology Stack

**Analysis Date:** 2026-03-19

## Languages

**Primary:**
- Python 3.10+ - Full application codebase in `labeler/` package

## Runtime

**Environment:**
- Python 3.10 or later (via `requires-python = ">=3.10"` in `pyproject.toml`)

**Package Manager:**
- pip (via setuptools)
- Lockfile: `pyproject.toml` (no explicit lock file generated)

## Frameworks

**Core:**
- None (pure Python with standard library modules)

**CLI:**
- argparse - Command-line interface in `labeler/cli.py`

**HTTP/API:**
- OpenAI Python SDK (`openai`) - OpenAI-compatible LLM client wrapper in `labeler/llm.py`

## Key Dependencies

**Critical:**
- `osxphotos` - Query and interact with macOS Photos library in `labeler/discovery.py`
- `photoscript` - AppleScript automation for writing metadata in `labeler/writer.py`
- `openai` - OpenAI-compatible API client (uses base_url override for LM Studio, etc.)
- `Pillow` (`pillow`) - Image processing and resizing in `labeler/exporter.py`
- `pillow-heif` - HEIF/HEIC image format support in `labeler/exporter.py`
- `datasette` - Local SQLite viewer/explorer (for metrics inspection)

**Build/Packaging:**
- `setuptools>=68.0` - Package build system

## Configuration

**Environment:**
- Config stored in `~/.image-labeler/config.json` (managed by `labeler/config.py`)
- No environment variables required beyond typical Python setup
- Metrics database at `~/.image-labeler/metrics.db` (SQLite with WAL mode)
- Daemon logs at `~/.image-labeler/daemon.log`

**Key Configs:**
- `base_url` - LLM API endpoint (default: `http://localhost:1234/v1`)
- `api_key` - LLM API key (optional, empty string accepted)
- `model` - Model name for LLM requests (default: `qwen/qwen3.5-9b`)
- `poll_interval` - Seconds between daemon cycles (default: 300)
- `limit_per_cycle` - Max items per run (default: 0 = all)
- `days` - Look back N days (default: 0 = all time)
- `to_days` - Skip last N days (default: 0 = include recent)
- `threads` - Photo processing parallelism (default: 4)
- `video_frames` - Frames to extract per video (default: 5)
- `max_dimension` - Max image dimension before resize (default: 1024)
- `photo` - Process photos (default: True)
- `video` - Process videos (default: True)
- `write` - Write metadata to Photos.app (default: True)

**Build:**
- `pyproject.toml` - Single source of truth for dependencies and metadata

## External Tools Required

**System Tools:**
- `ffmpeg` - Video processing, frame extraction
- `ffprobe` - Video metadata queries
- `pgrep` - Process checking in `labeler/writer.py`
- `sips` - Fallback image conversion in `labeler/exporter.py`
- `launchctl` - macOS daemon lifecycle management in `labeler/daemon.py`
- `mdfind` - Metadata search to verify Photos.app exists
- Photos.app - macOS native application (required to run)

## Platform Requirements

**Development:**
- macOS only (requires Photos.app and AppleScript)
- Python 3.10+ installed
- ffmpeg available (installable via `brew install ffmpeg`)

**Production:**
- macOS only
- Target deployment: Local machine via Homebrew tap at `ziadalzarka/tap`
- LaunchAgent-based daemon for continuous operation

**Homebrew Integration:**
- Package: `icloud-image-labeler`
- Installation: `brew install ziadalzarka/tap/icloud-image-labeler`
- Tap: `https://github.com/ziadalzarka/homebrew-tap`

## Entry Points

**CLI:**
- `icloud-image-labeler` command (defined in `pyproject.toml` via `[project.scripts]`)
- Routes to `labeler.cli:main` function in `labeler/cli.py`

**Module:**
- Runnable as `python -m labeler` via `labeler/__main__.py`

---

*Stack analysis: 2026-03-19*
