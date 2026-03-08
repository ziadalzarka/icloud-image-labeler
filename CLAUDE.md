# Project Instructions

## Git

- Do not include "Co-Authored-By" lines in commit messages.

## Project Overview

macOS CLI tool that auto-labels iCloud Photos using a local LLM (LM Studio). Queries the Photos library for unprocessed media, sends to LLM for keyword/title/description/OCR generation, and writes metadata back via PhotoScript.

## Architecture

- `labeler/` — main package, run with `python -m labeler`
  - `cli.py` — argparse CLI with `run`, `daemon`, `config` subcommands
  - `config.py` — `~/.image-labeler/config.json` management
  - `daemon.py` — launchd Launch Agent lifecycle
  - `discovery.py` — osxphotos query for unprocessed media
  - `exporter.py` — HEIC-to-JPEG conversion, video frame extraction (ffmpeg)
  - `llm.py` — OpenAI-compatible LLM client, response parsing, retry
  - `processor.py` — batch orchestration, parallel photos then sequential videos, error tracking
  - `writer.py` — PhotoScript metadata writes with thread-safe locking

## Key Constraints

- `use_photos_export=True` always (not just for missing/iCloud-only files)
- PhotoScript writes must be serialized (AppleScript is single-threaded) — `_write_lock` in `writer.py`
- Photos processed in parallel, videos sequentially (separate phases in `processor.py`)
- Qwen models return `<think>` blocks — stripped before JSON parsing in `llm.py`
- Images resized to `max_dimension` before sending to LLM to avoid context window exhaustion
