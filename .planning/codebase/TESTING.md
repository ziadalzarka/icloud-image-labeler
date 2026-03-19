# Testing Patterns

**Analysis Date:** 2026-03-19

## Test Framework

**Status:** Not detected

No test framework is configured or in use. There are:
- No `.pytest.ini`, `tox.ini`, or test configuration files
- No `tests/` or `test_*` directories
- No `*_test.py` or `test_*.py` files found in the repository
- No test dependencies in `pyproject.toml` (pytest, unittest, nose, etc.)

**Verification Approach:**
Testing is performed manually via:
- Interactive CLI: `python -m labeler run` with `--dry-run` flag to validate label generation without writing
- Integration testing: `labeler daemon start/stop` to verify Launch Agent lifecycle
- Manual testing of config management: `labeler config show/set/reset`

## Testing Manually

**Dry-Run Mode:**
The codebase supports `--dry-run` flag to preview label generation without writing to Photos:

```python
# writer.py lines 24-33
def write_metadata(photo_uuid: str, labels: dict, write: bool = True):
    """Write keywords, title, and description to Photos.app."""
    if not write:
        logger.info(f"[DRY RUN] Would write:")
        logger.info(f"  Title: {labels.get('title', '')}")
        logger.info(f"  Description: {labels.get('description', '')}")
        logger.info(f"  Keywords: {', '.join(labels.get('keywords', []))}")
        if labels.get("ocr_text"):
            logger.info(f"  OCR Text: {labels['ocr_text']}")
        return
```

Usage:
```bash
icloud-image-labeler run --dry-run
icloud-image-labeler run --dry-run --limit 5  # Test on first 5 items
```

**Metrics Database:**
Processing results are recorded in SQLite database for post-run analysis:

```bash
icloud-image-labeler metrics serve  # Start Datasette viewer on localhost:8001
icloud-image-labeler metrics path   # Show database location (~/.image-labeler/metrics.db)
```

Captured metrics enable validation of:
- Success/failure counts
- Timing (export, LLM, write durations)
- Image dimensions, frame counts
- LLM retry counts
- Per-item error messages

## Validation & Checks

**Startup Dependency Check:**
`labeler/checks.py` verifies required tools before processing:

```python
def check_dependencies():
    """Check that required external tools are available. Exits if any are missing."""
    missing = []
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            missing.append(tool)
    if not shutil.which("pgrep"):
        missing.append("pgrep")
    # Check Photos.app exists
    result = subprocess.run(
        ["mdfind", "kMDItemCFBundleIdentifier == 'com.apple.Photos'"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        missing.append("Photos.app")
    if missing:
        print(f"Error: missing required dependencies: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
```

Called from `cli.py` line 212 before processing starts.

**Image Integrity Check:**
Exported images are validated before sending to LLM:

```python
# exporter.py lines 63-68
try:
    size_mb = os.path.getsize(export_path) / (1024 * 1024)
    logger.debug(f"Exported {export_path} ({size_mb:.1f} MB)")
    img = _open_image(export_path, tmpdir)
    img.load()  # Force full read to catch truncated files early
except Exception as e:
    logger.warning(f"Failed to open {export_path}: {e}")
    img = None
```

**JSON Response Validation:**
LLM responses are parsed and validated with retry on failure:

```python
# llm.py lines 53-81
def _request_labels(client: OpenAI, model: str, messages: list) -> tuple[dict, int]:
    """Send request to LLM and parse response, with one retry on JSON failure.

    Returns (labels_dict, retry_count).
    """
    # ...
    try:
        return _parse_response(raw), 0
    except (json.JSONDecodeError, IndexError):
        logger.warning("JSON parse failed, retrying with correction prompt...")
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": "Please respond with valid JSON only."})
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.3,
        )
        raw = response.choices[0].message.content.strip()
        labels = _parse_response(raw)
        logger.debug(f"Retry succeeded: {len(labels.get('keywords', []))} keywords")
        return labels, 1
```

**Connection Testing:**
Setup wizard tests LLM endpoint connectivity:

```python
# init.py lines 17-24
def _test_connection(base_url: str, api_key: str) -> list[str] | None:
    """Try to list models from the endpoint. Returns model IDs or None on failure."""
    try:
        client = OpenAI(base_url=base_url, api_key=api_key or "not-needed")
        models = client.models.list()
        return [m.id for m in models.data]
    except Exception:
        return None
```

## Error Simulation

**Retry Testing:**
The retry mechanism can be tested by:
1. Running with `--dry-run` first to see what will process
2. Stopping LLM server mid-batch to trigger API errors
3. Observing exponential backoff in logs: `"Retrying in {delay}s..."`
4. Checking metrics database for `llm_retries` column

**Failure Recovery:**
Item failure tracking prevents infinite retries:

```python
# processor.py lines 61-76
class ItemFailureTracker:
    """Track per-item failure counts. Raises MaxFailuresExceeded after limit."""

    def record_failure(self, uuid: str, filename: str):
        with self._lock:
            self._counts[uuid] += 1
            count = self._counts[uuid]
        if count >= MAX_ITEM_FAILURES:
            raise MaxFailuresExceeded(
                f"Item {filename} ({uuid[:8]}...) failed {count} times. Stopping."
            )
        logger.warning(f"{filename} failed ({count}/{MAX_ITEM_FAILURES})")
```

Set to `MAX_ITEM_FAILURES = 10` in `processor.py` line 18.

## Thread Safety Testing

**Lock Validation:**
PhotoScript write access is serialized:

```python
# writer.py lines 9, 41-47
_write_lock = threading.Lock()

def write_metadata(photo_uuid: str, labels: dict, write: bool = True):
    """Write keywords, title, and description to Photos.app."""
    # ...
    with _write_lock:
        logger.debug(f"Writing metadata to Photos.app...")
        photo = photoscript.Photo(photo_uuid)
        photo.keywords = keywords
        photo.title = labels.get("title", "")
        photo.description = labels.get("description", "")
        logger.info(f"Written {len(keywords)} keywords, title, and description")
```

Can be validated by:
1. Running with `--threads 4` (or higher) to force concurrency
2. Checking logs for sequential write operations (no interleaved logging)
3. Verifying metadata correctness in Photos.app

**Database Connection Testing:**
Thread-local SQLite connections prevent contention:

```python
# metrics.py lines 14-20
def _get_conn() -> sqlite3.Connection:
    """Get a thread-local database connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn
```

WAL mode enables concurrent reads from different threads.

## Graceful Shutdown Testing

**Signal Handler Testing:**
Shutdown event blocks on SIGINT/SIGTERM:

```python
# shutdown.py lines 12-31
def request_shutdown(signum=None, frame=None):
    """Signal handler that sets the shutdown flag."""
    name = signal.Signals(signum).name if signum else "unknown"
    logger.info(f"Received {name}, shutting down gracefully...")
    _shutdown_event.set()

def wait(timeout: float) -> bool:
    """Sleep for up to `timeout` seconds, returning True if shutdown was requested."""
    return _shutdown_event.wait(timeout)
```

Can test via:
```bash
icloud-image-labeler run --loop &
sleep 2
kill -SIGTERM $!
# Should log "Received SIGTERM, shutting down gracefully..."
# And complete current batch before exiting
```

## Configuration Testing

**Config Management:**
All operations are tested via CLI:

```bash
# Show all configuration
icloud-image-labeler config show

# Set individual values (with type coercion)
icloud-image-labeler config set max_dimension 2048
icloud-image-labeler config set threads 8

# Reset to defaults
icloud-image-labeler config reset

# Show config file path
icloud-image-labeler config path
```

Config validation in `config.py` lines 48-62:
```python
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
```

## Test Coverage Gaps

**No Automated Tests:**
The following areas lack automated test coverage:
- `discovery.py`: Photo query filtering logic not tested
- `exporter.py`: Image format conversion fallbacks, resizing logic
- `llm.py`: Response parsing with different LLM output formats (thinking blocks, markdown)
- `processor.py`: Batch orchestration, backpressure handling, refresh logic
- `writer.py`: AppleScript metadata writing via photoscript
- `daemon.py`: launchd plist generation and lifecycle
- `config.py`: Type coercion for all config types
- `metrics.py`: SQL queries, aggregations, concurrent access

**Manual Testing Required For:**
- End-to-end photo labeling with various file formats (HEIC, JPG, JPEG, PNG)
- Video frame extraction and multi-frame LLM prompting
- iCloud-only photo handling (derivative fallback)
- Graceful shutdown during active processing
- Daemon startup/stop/restart operations
- LLM connection failures and recovery

## Recommended Test Coverage Areas

**Priority: High**
- `processor.py`: Retry logic, failure tracking, batch orchestration — core workflow
- `llm.py`: JSON parsing with various LLM output formats — common error point
- `exporter.py`: Fallback chain (export → original → derivatives) — robustness critical

**Priority: Medium**
- `discovery.py`: Date filtering, media type filtering — correctness important
- `writer.py`: Lock behavior under concurrent access — safety critical
- `config.py`: Type validation and coercion — user-facing errors

**Priority: Low**
- `daemon.py`: launchd integration — platform-specific, manual testing sufficient
- `metrics.py`: Database operations — analytics, not core functionality

---

*Testing analysis: 2026-03-19*
