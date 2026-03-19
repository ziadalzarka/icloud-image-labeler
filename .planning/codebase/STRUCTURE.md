# Codebase Structure

**Analysis Date:** 2026-03-19

## Directory Layout

```
image-labeler/
├── .planning/              # GSD planning documents (generated)
├── .git/                   # Git repository
├── .claude/                # Claude workspace settings
├── .gitignore              # Git exclusions
├── CLAUDE.md               # Project instructions (checked in)
├── LICENSE                 # License file
├── README.md               # Project documentation
├── pyproject.toml          # Package metadata and dependencies
├── labeler/                # Main package
│   ├── __init__.py         # Package marker (empty)
│   ├── __main__.py         # Module entry point (calls cli.main())
│   ├── cli.py              # CLI argument parsing and subcommand routing
│   ├── config.py           # Config file management (~/.image-labeler/config.json)
│   ├── processor.py        # Batch orchestration (photos parallel, videos sequential)
│   ├── discovery.py        # Photos library query for unprocessed media
│   ├── exporter.py         # HEIC/JPEG export and video frame extraction
│   ├── llm.py              # OpenAI-compatible LLM client and response parsing
│   ├── writer.py           # PhotoScript metadata writes (thread-safe via lock)
│   ├── daemon.py           # launchd plist management for background execution
│   ├── metrics.py          # SQLite metrics database for performance tracking
│   ├── shutdown.py         # Signal handlers for graceful shutdown
│   ├── init.py             # First-run interactive setup wizard
│   └── checks.py           # Dependency verification (ffmpeg, ffprobe, Photos.app)
└── icloud_image_labeler.egg-info/  # Package metadata (generated)
```

## Directory Purposes

**`labeler/`:**
- Purpose: Main Python package containing all application logic
- Contains: CLI interface, configuration, media processing pipeline, LLM integration, metadata writing
- Key files: `cli.py`, `processor.py`, `config.py`

**`.planning/codebase/`:**
- Purpose: GSD analysis documents (architecture, structure, conventions, testing, etc.)
- Contains: Generated markdown files consumed by other GSD commands
- Generated: Yes
- Committed: No (git-ignored)

## Key File Locations

**Entry Points:**
- `labeler/__main__.py` — Module entry point; imports and calls `cli.main()`
- `labeler/cli.py:main()` — Main CLI function; sets up logging, parses arguments, dispatches subcommands

**Configuration:**
- `labeler/config.py` — Config file loading/saving; defaults in `DEFAULTS` dict; path is `~/.image-labeler/config.json`
- `pyproject.toml` — Package metadata (name: icloud-image-labeler, entry point: icloud-image-labeler command)

**Core Processing Pipeline:**
- `labeler/processor.py` — Batch orchestration; two-phase processing (photos parallel, videos sequential)
- `labeler/discovery.py` — Queries osxphotos for unprocessed media
- `labeler/exporter.py` — Converts photos/videos to base64 for LLM
- `labeler/llm.py` — Sends to LLM, parses JSON responses, handles retries
- `labeler/writer.py` — Writes metadata back to Photos.app via AppleScript

**Supporting Systems:**
- `labeler/daemon.py` — Manages background execution via launchd
- `labeler/metrics.py` — Records performance metrics to `~/.image-labeler/metrics.db`
- `labeler/shutdown.py` — Graceful shutdown via signal handlers
- `labeler/init.py` — Interactive setup wizard for first run
- `labeler/checks.py` — Verifies ffmpeg, ffprobe, pgrep, Photos.app present

## Naming Conventions

**Files:**
- `_function_name()` — Private function (leading underscore)
- `class_name()` — Public function (no leading underscore)
- `CLASS_NAME` — Global constant (uppercase)
- `variable_name` — Local variable (lowercase with underscores)

**Directories:**
- `labeler/` — Package with lowercase name
- `.planning/codebase/` — Hidden directory for planning documents

**Module Organization:**
- One main responsibility per module (discovery, export, llm, write, config, etc.)
- No barrel files; explicit imports required
- Each module has module-level logger: `logger = logging.getLogger(__name__)`

## Where to Add New Code

**New Feature (e.g., new labeling strategy):**
- Primary code: Create new function in `labeler/processor.py` or new module if substantial
- Tests: Create `test_processor.py` or `test_new_module.py` in tests directory (if adding tests)
- Integration: Update `processor.process_batch()` to call new feature or add new subcommand in `cli.py`

**New Media Type (e.g., RAW images):**
- Export logic: Add function to `labeler/exporter.py` (e.g., `export_raw_as_base64()`)
- LLM logic: Reuse existing `label_photo()` in `labeler/llm.py` or extend if needed
- Processing: Add separate phase in `process_batch()` similar to photos/videos phases
- Discovery: Extend filters in `labeler/discovery.py` to include new media type

**New Configuration Option:**
- Schema: Add key to `DEFAULTS` dict in `labeler/config.py`
- CLI flag: Add argument to appropriate subparser in `labeler/cli.py`
- Usage: Merge into config dict via `args.option or cfg["option"]` pattern (see line 31-39 in cli.py)
- Validation: Add type coercion in `config.set_value()` if non-string type

**New Subcommand:**
- Handler: Create `_command_cmd()` function in `labeler/cli.py`
- Parser: Add `subparsers.add_parser("command", ...)` in `main()`
- Dispatch: Add condition in subcommand routing (line 214-219 in cli.py)
- Logic: Implement in dedicated module if substantial (e.g., `labeler/daemon.py`)

**New External Integration:**
- Client creation: Add function to `labeler/llm.py` or new module
- Error handling: Add exception type to `_is_retryable_error()` in `labeler/processor.py` if applicable
- Configuration: Add base_url/api_key style config to `DEFAULTS` in `labeler/config.py`
- Initialization: Add prompts to `labeler/init.py` setup wizard

**Utilities:**
- Shared image helpers: `labeler/exporter.py` (has `_resize_if_needed()`, `_open_image()`)
- Shared retry logic: `labeler/processor.py` (has `_retry_delay()`, `_is_retryable_error()`)
- Shared metrics: `labeler/metrics.py` (has thread-local connections, record_item(), start_run())

## Special Directories

**`~/.image-labeler/`:**
- Purpose: User-specific runtime files (config, logs, metrics)
- Generated: Yes (created automatically on first run)
- Contents:
  - `config.json` — User configuration (base_url, api_key, model, etc.)
  - `daemon.log` — Daemon logs (when running in background)
  - `metrics.db` — SQLite database with item and run metrics

**`~/Library/LaunchAgents/`:**
- Purpose: macOS system location for background agents
- Generated: Yes (by daemon.py when `daemon start` is run)
- Contents:
  - `com.image-labeler.plist` — launchd plist for background execution

**`/tmp/` (or system temp):**
- Purpose: Temporary files for media processing
- Generated: Yes (by exporter.py during processing)
- Lifecycle: Automatically cleaned up after each export operation (tempfile.TemporaryDirectory context manager)

## Import Organization

**Pattern observed:**

1. Standard library imports (os, sys, logging, threading, pathlib, etc.)
2. Third-party imports (osxphotos, openai, photoscript, PIL, etc.)
3. Local imports (from labeler import config, processor, etc.)

**Example from `processor.py` (lines 1-14):**
```python
import logging
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import osxphotos
from openai import APIConnectionError, APITimeoutError, APIStatusError

from labeler.exporter import export_photo_as_base64, export_video_frames_as_base64
from labeler.llm import create_client, label_photo, label_video
from labeler.writer import write_metadata
from labeler import metrics
from labeler.shutdown import is_shutting_down, wait as shutdown_wait
```

**Path Aliases:**
- None detected; all imports use explicit relative paths (from labeler import ...)

---

*Structure analysis: 2026-03-19*
