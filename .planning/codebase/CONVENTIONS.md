# Coding Conventions

**Analysis Date:** 2026-03-19

## Naming Patterns

**Files:**
- Module files: lowercase with underscores (e.g., `config.py`, `exporter.py`, `llm.py`)
- Private/internal files: same convention (e.g., `__init__.py`, `__main__.py`)
- No suffix differentiation (no `_service.py`, `_util.py` patterns)

**Functions:**
- Public functions: lowercase with underscores (e.g., `get_unprocessed_media`, `export_photo_as_base64`, `process_batch`)
- Private/internal functions: leading underscore prefix (e.g., `_setup_logging`, `_run`, `_format_date`, `_is_retryable_error`)
- Helper/nested functions: also use underscore prefix (e.g., `_open_image`, `_resize_if_needed`)

**Variables:**
- Local variables: lowercase with underscores (e.g., `base_url`, `api_key`, `llm_duration`)
- Constants: UPPERCASE with underscores (e.g., `MAX_ITEM_FAILURES`, `RETRY_BASE_DELAY`, `RETRY_MAX_DELAY`)
- Instance variables in classes: lowercase with underscores, often with underscore prefix for "private" (e.g., `_counts`, `_lock`, `_shutdown_event`)

**Types:**
- Type hints present on function signatures: `photo: osxphotos.PhotoInfo`, `timeout: float`, `api_key: str = ""`
- Return type hints on all functions: `-> bool`, `-> dict`, `-> list[str]`, `-> tuple[str, dict]`
- Union types use pipe syntax: `str | None` (Python 3.10+ style, not `Optional[str]`)
- Generic types: `dict`, `list`, `tuple` with square bracket parameters (e.g., `list[str]`, `dict[str, int]`)

## Code Style

**Formatting:**
- No explicit formatter configured (no `.black` config, no `.isort` config)
- Line length appears unconstrained by formatter (lines vary from ~40 to ~100+ characters)
- 4-space indentation used consistently
- Trailing newlines on files
- Imports organized manually without tool enforcement

**Linting:**
- No linter config detected (no `.pylintrc`, `.flake8`, `pylintrc` files)
- Code follows PEP 8 conventions manually (function definitions, variable naming)
- No type checking tool configured (no `mypy.ini`, `pyright` config)

## Import Organization

**Order:**
1. Standard library imports (e.g., `import json`, `import logging`, `import subprocess`)
2. Third-party imports (e.g., `import osxphotos`, `from openai import OpenAI`, `from PIL import Image`)
3. Local package imports (e.g., `from labeler import config`, `from labeler.exporter import export_photo_as_base64`)

**Path Aliases:**
- No path aliases or import shortcuts defined
- Absolute imports always used: `from labeler.processor import process_batch`
- Package name always included: `import osxphotos`, never relative imports

## Error Handling

**Patterns:**
- Custom exceptions defined as subclasses of built-in types:
  - `class MaxFailuresExceeded(RuntimeError):` — raised when item retry limit exceeded
  - Uses docstring on exception class: `"""Raised when a single item exceeds MAX_ITEM_FAILURES."""`
- Function-level try/except blocks around risky operations:
  - `_is_retryable_error()` function checks exception type and status code to determine retry eligibility
  - Retryable errors: `APIConnectionError`, `APITimeoutError`, `ConnectionError`, `TimeoutError`, server-side 5xx errors, LM Studio crashes (400 with "crashed" in message)
  - Non-retryable errors logged and bubbled up with context (filename, UUID prefix)
- Exponential backoff retry logic: `_retry_delay(attempt)` uses `min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)` with max 300s
- Error recovery in batch processing:
  - Individual item failures don't stop batch (caught in outer loop)
  - `MaxFailuresExceeded` exception re-raised to stop entire batch (line 295-296 in `processor.py`)
  - `ItemFailureTracker` class tracks per-item failures and raises when limit reached
- Graceful degradation in export:
  - Primary: `photo.export()` via Photos.app
  - Fallback 1: original file path if export fails
  - Fallback 2: derivative JPEGs if original unavailable
  - Final error: `RuntimeError` with clear message if all paths exhausted
- Subprocess errors checked via `returncode != 0` and `capture_output` used throughout
- External tool dependencies verified at startup in `check_dependencies()`

## Logging

**Framework:** Python's `logging` module (stdlib)

**Patterns:**
- Logger created per module: `logger = logging.getLogger(__name__)` at top of each file
- Setup in `_setup_logging()` (line 17-25 in `cli.py`):
  - Format: `"%(asctime)s %(levelname)-7s [%(name)s] %(message)s"`
  - Debug level controlled by `--verbose` flag
  - Third-party loggers (`httpx`, `openai`, `httpcore`) kept at INFO to avoid noise
- Log levels used appropriately:
  - `logger.info()` for user-facing progress (start processing, completion, discovery results)
  - `logger.debug()` for detailed diagnostics (export state, image dimensions, parsing details)
  - `logger.warning()` for recoverable issues (retry attempts, export fallbacks, refresh failures)
  - `logger.error()` for item failures (filename and reason, with indexed position in batch)
- Log format includes timestamp, level, module name, and message
- Batch processing logs item progress with index: `[{processed}/{total}] Done: {filename}`

## Comments

**When to Comment:**
- Module-level docstrings on files: `"""Interactive first-run setup wizard."""` in `init.py`, `"""Graceful shutdown handling via SIGINT/SIGTERM."""` in `shutdown.py`
- Inline comments for non-obvious logic:
  - `# Strip <think>...</think> blocks (Qwen thinking mode)` in `llm.py`
  - `# LM Studio model crash returns 400 with "crashed" in the message` in `processor.py`
  - `# osxphotos SQLite is thread-bound` in `processor.py`
  - `# Filter: no keywords, not hidden` in `discovery.py`
  - `# Export on main thread (osxphotos SQLite is thread-bound)` in `processor.py`
- Function docstrings on public functions and important private functions
- Comments section out key architectural decisions (phases, thread safety concerns)

**JSDoc/TSDoc:**
- Not applicable (Python project)
- Function docstrings follow Google-style format:
  ```python
  def get_unprocessed_media(
      limit: int = 0,
      days_back: int = 0,
      to_days: int = 0,
      photo: bool = True,
      video: bool = True,
  ) -> list[osxphotos.PhotoInfo]:
      """Query Photos library for unprocessed media (no keywords, not hidden).

      Args:
          limit: Max items to return. 0 = no limit (all unprocessed).
          days_back: Look back N days from now. 0 = no date filter (all photos).
          to_days: Skip the most recent N days (e.g. 7 = exclude last 7 days).
      """
  ```
- Short docstrings (one-liner) on simple functions
- Full docstring with Args/Returns on complex functions

## Function Design

**Size:**
- Small focused functions: most are 5-30 lines
- Longer functions when orchestrating complex workflows:
  - `process_batch()` — 169 lines (orchestrates photo/video processing phases)
  - `export_video_frames_as_base64()` — 68 lines (extracts frames via ffmpeg with fallback logic)
  - `_run()` — 56 lines (main CLI loop with graceful shutdown)
- No functions exceed ~200 lines

**Parameters:**
- Most functions 1-4 parameters
- Longer parameter lists decomposed into logical groups:
  - `process_batch()` has 8 parameters grouped by concern: media list, model config, parallelism, dimensions, write mode, refresh logic, api_key
  - Default parameters used for optional/config values: `max_dimension: int = 1024`, `write: bool = True`
  - No `**kwargs` or `*args` used — explicit parameters throughout

**Return Values:**
- Single return type per function (no conditional return types)
- Tuples used for returning related data: `tuple[dict, int]` for (labels, retry_count)
- Dicts for structured data: `dict[str, int]` for metadata
- None only for side-effect-only functions
- Type hints always present on return

## Module Design

**Exports:**
- No `__all__` defined
- All public functions are top-level in modules
- Private implementation details use underscore prefix
- Modules are single-responsibility: `config.py` only config, `exporter.py` only export, `processor.py` only orchestration
- Clear module boundaries respected (e.g., `llm.py` doesn't import from `writer.py`)

**Barrel Files:**
- `__init__.py` exists but is empty (no re-exports)
- Imports always explicit: `from labeler.config import load_config`

## Threading & Concurrency

**Patterns:**
- Thread-local storage for database connections: `_local = threading.local()` in `metrics.py`
- Locks for shared mutable state:
  - `_write_lock = threading.Lock()` in `writer.py` — serializes PhotoScript calls (AppleScript is single-threaded)
  - `_lock = threading.Lock()` in `ItemFailureTracker` — serializes failure count updates
- No global state mutation outside locked sections
- `ThreadPoolExecutor` for photo parallelization in `processor.py`
- Shutdown coordination via `threading.Event()` in `shutdown.py` — checked with `is_shutting_down()` and `wait(timeout)`
- Futures tracked in dict for backpressure management: `in_flight: dict = {}`

## Data Structures

**Patterns:**
- Config stored as plain dicts (JSON serializable): keys are strings, values are primitives or simple lists
- Metrics use sqlite3 with thread-local connections
- No dataclasses or Pydantic models used (values passed as dicts)
- Named tuples not used; tuples with known order (labels, retry_count) returned from functions
- Sets used for deduplication: `seen_uuids = {p.uuid for p in items}`
- Defaultdict for tallies: `defaultdict(int)` in `ItemFailureTracker`

---

*Convention analysis: 2026-03-19*
