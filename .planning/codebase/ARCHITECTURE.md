# Architecture

**Analysis Date:** 2026-03-19

## Pattern Overview

**Overall:** Pipeline orchestration with thread-based parallelism for media processing.

**Key Characteristics:**
- Photo processing parallelized across worker threads; video processing sequential on main thread
- Main thread pins osxphotos queries (SQLite is thread-bound) and photo exports
- Graceful shutdown via signal handlers with in-flight task cancellation
- Retry logic with exponential backoff for transient LLM/network failures
- Metrics collected at item and batch granularity to SQLite

## Layers

**CLI Layer:**
- Purpose: Argument parsing, subcommand routing, logging setup
- Location: `labeler/cli.py`
- Contains: Main entry point, argparse configuration, subcommand handlers
- Depends on: config, processor, daemon, metrics, discovery
- Used by: `labeler/__main__.py`

**Configuration Layer:**
- Purpose: Load, validate, and persist user settings from `~/.image-labeler/config.json`
- Location: `labeler/config.py`
- Contains: Config schema (defaults), path management, type coercion
- Depends on: pathlib, json
- Used by: cli, daemon, init

**Discovery Layer:**
- Purpose: Query Photos library for unprocessed media matching filters
- Location: `labeler/discovery.py`
- Contains: osxphotos query logic, date filtering, sorting
- Depends on: osxphotos
- Used by: processor, cli (via _run)

**Export Layer:**
- Purpose: Convert media to base64-encoded formats suitable for LLM consumption
- Location: `labeler/exporter.py`
- Contains: Photo JPEG export with resizing, video frame extraction with ffmpeg
- Depends on: osxphotos, PIL, ffmpeg, ffprobe, sips (macOS system tool)
- Used by: processor (on main thread only)

**LLM Layer:**
- Purpose: Send media to OpenAI-compatible endpoint, parse structured responses
- Location: `labeler/llm.py`
- Contains: System prompts (photo/video), JSON parsing with fallback retry, client creation
- Depends on: openai
- Used by: processor (in worker threads)

**Write Layer:**
- Purpose: Persist labels to Photos.app via AppleScript (photoscript)
- Location: `labeler/writer.py`
- Contains: Thread-safe metadata writes with lock serialization, dry-run support
- Depends on: photoscript, threading.Lock
- Used by: processor (in worker threads)

**Daemon Layer:**
- Purpose: Manage launchd plist for background execution
- Location: `labeler/daemon.py`
- Contains: plist generation, launchctl commands, daemon lifecycle
- Depends on: subprocess, plistlib
- Used by: cli (daemon subcommand)

**Metrics Layer:**
- Purpose: Record performance and status metrics to persistent SQLite
- Location: `labeler/metrics.py`
- Contains: Thread-local database connections, item/run record schemas, queries
- Depends on: sqlite3
- Used by: processor, cli (metrics subcommand)

**Shutdown Layer:**
- Purpose: Handle graceful shutdown across threads and async operations
- Location: `labeler/shutdown.py`
- Contains: Signal handlers (SIGINT/SIGTERM), shutdown event, wait with timeout
- Depends on: signal, threading
- Used by: processor, cli

**Initialization Layer:**
- Purpose: First-run interactive setup wizard
- Location: `labeler/init.py`
- Contains: User prompts, LLM endpoint validation, model discovery
- Depends on: openai
- Used by: cli (init subcommand)

**Support Layer:**
- `labeler/checks.py` — Dependency verification (ffmpeg, ffprobe, pgrep, Photos.app)
- `labeler/__init__.py` — Package marker (empty)
- `labeler/__main__.py` — Module entry point (imports cli.main)

## Data Flow

**Discovery → Processing → Metrics:**

1. User runs `labeler run` with optional filters (--days, --limit, --uuid, etc.)
2. CLI loads config and installs shutdown handlers
3. Discovery queries Photos library for items without keywords, sorted by date
4. Processor orchestrates two-phase batch:
   - **Photo phase (parallel):** Main thread exports all photos to base64, submits each to worker pool for LLM+write
   - **Video phase (sequential):** Main thread processes each video through export, LLM, and write
5. Each item records metrics (duration, size, keywords count, status) to SQLite
6. Batch finish records aggregate metrics (success/fail counts, avg duration)

**State Management:**

- **Per-batch state:** `ItemFailureTracker` (dict of uuid → failure count) prevents retry loops
- **Per-item state:** Metrics row (upserted by uuid) captures success/error details
- **Per-run state:** Metrics run record captures start time, model, thread count; updated at finish with results
- **Globals:** `_write_lock` in writer.py serializes all AppleScript writes

## Key Abstractions

**ItemFailureTracker:**
- Purpose: Prevent indefinite retries on permanently broken items
- Examples: `labeler/processor.py` lines 61-77
- Pattern: Thread-safe counter dict; raises `MaxFailuresExceeded` after 10 failures

**Retryable Error Detection:**
- Purpose: Distinguish transient network/LLM errors from permanent failures
- Examples: `labeler/processor.py` lines 27-36
- Pattern: Check exception type (APIConnectionError, APITimeoutError, status >= 500)
  - Special case: LM Studio crash returns 400 with "crashed" in message

**Export-then-LLM Separation:**
- Purpose: Keep main thread bound to osxphotos (SQLite), offload LLM to workers
- Examples: Photo export at lines 317-327, submission to worker at lines 329-332 in `processor.py`
- Pattern: Main thread handles all I/O with osxphotos; workers handle stateless LLM requests

**Dry-Run Support:**
- Purpose: Preview labels without writing to Photos.app
- Examples: `labeler/writer.py` lines 26-33; `labeler/cli.py` line 44-45
- Pattern: Boolean `write` flag threaded through processor → writer; dry-run logs instead of writing

## Entry Points

**`labeler/__main__.py`:**
- Location: `labeler/__main__.py`
- Triggers: `python -m labeler` or installed binary
- Responsibilities: Import and call `cli.main()`

**`labeler/cli.py:main()`:**
- Location: `labeler/cli.py` lines 138-220
- Triggers: Directly invoked by __main__
- Responsibilities:
  - Pre-parse for --verbose flag before full parsing
  - Set up logging
  - Create argparse parser with subcommands (init, run, daemon, config, metrics)
  - Load config and initialize metrics database
  - Dispatch to appropriate handler based on subcommand
  - Default to "run" if no subcommand specified

**`labeler/cli.py:_run()`:**
- Location: `labeler/cli.py` lines 28-82
- Triggers: `run` subcommand or default (no subcommand)
- Responsibilities:
  - Merge CLI flags with config values (CLI overrides config)
  - Loop if --loop flag, else single pass
  - Call discover() and processor.process_batch()
  - Sleep poll_interval between cycles
  - Respect shutdown signals

## Error Handling

**Strategy:** Catch exceptions at boundary layers (export, LLM, write); retry transiently retryable errors; fail item after MAX_ITEM_FAILURES.

**Patterns:**

1. **LLM Retries (labeler/llm.py lines 53-81):** If JSON parsing fails, send correction prompt. Total 1 retry attempt.

2. **Photo/Video Item Retries (processor.py lines 123-142, 197-213):** Exponential backoff (5s * 2^attempt, capped at 300s). Retry until retryable error becomes non-retryable or shutdown requested.

3. **Export Error (processor.py lines 317-327):** Catch on main thread; record metrics error, increment tracker failure count, continue to next item.

4. **LLM/Write Error in Worker (processor.py lines 129-141):** Caught by _label_photo_with_retry; retryable errors backoff, non-retryable errors increment tracker.

5. **Tracker Limit (processor.py lines 72-75):** When failure count reaches 10, raise MaxFailuresExceeded; caught at batch level (lines 295-296, 348-349, 374-375) and propagates to exit batch processing.

6. **Metric Recording Error (processor.py lines 48-58, 103-120):** Always recorded for success or failure; includes error_message field.

## Cross-Cutting Concerns

**Logging:**
- Framework: Python stdlib logging with custom format "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
- Setup: `cli._setup_logging()` at lines 17-25; third-party loggers (httpx, openai, httpcore) set to INFO to reduce noise
- Pattern: Each module has `logger = logging.getLogger(__name__)` at top; log before/after major operations

**Validation:**
- Config validation: `config.set_value()` checks key is in VALID_KEYS, coerces type based on defaults (booleans, ints, strings)
- Dependency validation: `checks.check_dependencies()` verifies ffmpeg, ffprobe, pgrep, Photos.app present before processing
- LLM response validation: `llm._parse_response()` strips Qwen think blocks, markdown code fences, parses JSON

**Authentication:**
- LLM: Base URL + optional API key from config, passed to OpenAI client (uses "not-needed" placeholder if empty)
- Photos: No auth; uses osxphotos native access (requires user grant on first use)
- AppleScript: No auth; photoscript sends commands to Photos.app (requires user grant)

**Threading:**
- Main thread: Bound to osxphotos queries and photo exports (SQLite is thread-bound)
- Worker pool: LLM requests and metadata writes (stateless operations on per-item data)
- Synchronization: ItemFailureTracker uses threading.Lock; metrics uses thread-local connections; writer uses _write_lock
- Backpressure: Processor throttles photo exports via in_flight dict; worker pool size limits concurrent LLM requests

**Timeouts:**
- LLM client timeout: 90 seconds (openai.py line 39)
- Photo export timeout: 30 seconds (exporter.py line 49)
- Video export timeout: 300 seconds (exporter.py line 103)
- Future result timeout during shutdown: 5 seconds (processor.py line 345)

---

*Architecture analysis: 2026-03-19*
