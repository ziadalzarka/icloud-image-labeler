# External Integrations

**Analysis Date:** 2026-03-19

## APIs & External Services

**LLM Service:**
- **OpenAI-Compatible API** - Local or remote LLM inference
  - SDK/Client: `openai` Python package
  - Implementation: `labeler/llm.py` (create_client, label_photo, label_video)
  - Auth: `api_key` config (optional, defaults to "not-needed" for local LM Studio)
  - Base URL: `base_url` config (default: `http://localhost:1234/v1`)
  - Timeout: 90 seconds per request
  - Supported: Any endpoint compatible with OpenAI chat completions API (LM Studio, Ollama, vLLM, etc.)
  - Model parameter: User-configurable, defaults to `qwen/qwen3.5-9b`

## Data Storage

**Databases:**
- **Photos Library (read-only)** - macOS built-in Photos app database
  - Client: `osxphotos` library
  - Access: Query via `osxphotos.PhotosDB()` in `labeler/discovery.py`
  - Metadata queried: `uuid`, `filename`, `date_added`, `date`, `keywords`, `hidden`, `ismissing`, `isphoto`, `path`, `path_derivatives`

**Metrics Database:**
- **SQLite** - Local metrics and run history
  - Path: `~/.image-labeler/metrics.db`
  - Schema: Defined in `labeler/metrics.py` with two tables:
    - `item_metrics` - Per-photo/video processing records (uuid, filename, media_type, status, export_duration_s, llm_duration_s, write_duration_s, etc.)
    - `run_metrics` - Per-batch run summaries (photos_found, videos_found, photos_processed, videos_processed, photos_failed, videos_failed, avg_llm_duration_s)
  - Journal mode: WAL (write-ahead logging)
  - Client: Thread-local `sqlite3` connections in `labeler/metrics.py`
  - Viewable via: `datasette` package (optional, for exploration)

**File Storage:**
- **Local temporary directories** - Photos export, video frames, converted images
  - Uses `tempfile.TemporaryDirectory()` in `labeler/exporter.py`
  - Never persists files; cleaned up automatically

**Configuration Storage:**
- **Local JSON file** - User configuration
  - Path: `~/.image-labeler/config.json`
  - Managed by: `labeler/config.py` (load_config, save_config, set_value, reset_config)
  - Format: JSON with keys matching `DEFAULTS` dict

## Authentication & Identity

**Auth Mechanism:**
- API key authentication for LLM (optional, passed to `OpenAI` client via `api_key` parameter)
- No user/identity system; machine-local operation only
- Photos.app access requires local user session (implicit)

## Monitoring & Observability

**Error Tracking:**
- Local metrics database with error_message field
- No external error tracking service
- Errors logged via Python `logging` module

**Logs:**
- **Console Logging** - Default during interactive runs
  - Format: `%(asctime)s %(levelname)-7s [%(name)s] %(message)s`
  - Level: DEBUG (with `-v` flag) or INFO by default
- **Daemon Logging** - Background daemon operation
  - Path: `~/.image-labeler/daemon.log`
  - Routed via launchd StandardOutPath/StandardErrorPath in `labeler/daemon.py`
- **Third-party Logger Suppression**
  - `httpx`, `openai`, `httpcore` loggers set to INFO level (suppress verbose body/base64 dumps)

**Metrics Recorded:**
- Per-item: export duration, LLM duration, write duration, image size, dimensions, retry count, keywords count, OCR presence
- Per-run: photos/videos found, photos/videos processed, photos/videos failed, average LLM duration, total run duration

## CI/CD & Deployment

**Hosting/Distribution:**
- **Homebrew Tap** - `https://github.com/ziadalzarka/homebrew-tap`
- **Installation:** `brew tap ziadalzarka/tap && brew install icloud-image-labeler`
- No cloud deployment; purely local macOS CLI tool

**CI Pipeline:**
- None detected (not applicable for local CLI tool)

**Daemon Management:**
- **macOS LaunchAgent** - Continuous background operation
  - Plist path: `~/Library/LaunchAgents/com.image-labeler.plist`
  - Label: `com.image-labeler`
  - Configured in `labeler/daemon.py`
  - RunAtLoad: True (auto-start on login)
  - KeepAlive: True (restart on crash)
  - Environment: Adds `/usr/local/bin`, `/usr/bin`, `/bin`, `/opt/homebrew/bin` to PATH

## Environment Configuration

**Required env vars:**
- None required; all configuration via `~/.image-labeler/config.json`

**Optional system environment:**
- `PATH` - Must include ffmpeg/ffprobe locations (configured in launchd plist)

**Secrets location:**
- API key stored in plaintext in `~/.image-labeler/config.json` (user-controlled, no external secrets manager)

## Photos.app Integration

**AppleScript Automation:**
- **Metadata Writing** - Via `photoscript` library
  - Implementation: `labeler/writer.py` (write_metadata function)
  - Operations: Set keywords (list), title (string), description (string)
  - Method: AppleScript automation via `photoscript.Photo(uuid)` API
  - Concurrency: Serialized writes via `_write_lock` (AppleScript single-threaded constraint)
  - App Management: Auto-opens Photos.app if not running (using `open -a Photos` command)

**Media Discovery:**
- Query unprocessed photos/videos by date range, media type, keyword presence
- Implementation: `labeler/discovery.py` via `osxphotos.PhotosDB()`
- Filters: No keywords set, not hidden, date range optional, media type optional

**Media Export:**
- Photos: Export via Photos.app or fallback to original file or derivative
  - Format: JPEG (HEIC converted via `pillow-heif` or `sips`)
  - Resize: Max dimension 1024 (configurable)
  - Timeout: 30 seconds per photo
- Videos: Full export then frame extraction
  - Timeout: 300 seconds per video
  - Frame count: 5 (configurable)
  - Frame extraction: Via ffmpeg at equal intervals

## Webhooks & Callbacks

**Incoming:**
- None (not applicable for CLI tool)

**Outgoing:**
- None (not applicable; purely local operation)

## Signal Handling & Graceful Shutdown

**Implementation:**
- SIGINT (Ctrl+C) and SIGTERM handlers installed via `labeler/shutdown.py`
- Graceful shutdown: In-flight LLM requests cancelled with 90-second timeout to prevent hangs
- Daemon mode: Respects shutdown event, completes current batch before exiting

---

*Integration audit: 2026-03-19*
