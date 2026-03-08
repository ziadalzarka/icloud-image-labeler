## Context

A working POC (`poc.py`) already exists that can query the Photos library, export photos/videos, send them to a local LM Studio instance for AI labeling, and write keywords/title/description back via PhotoScript. The POC runs as a one-shot CLI command. The codebase is a greenfield Python project targeting macOS only.

The user wants the tool to also support running as a background daemon that continuously processes new unprocessed media without manual invocation.

## Goals / Non-Goals

**Goals:**
- Refactor the POC into a well-structured CLI tool with the flags defined in the proposal
- Support parallel processing (up to 4 threads: 3 photos + 1 video concurrently)
- Add a `daemon` subcommand to run the tool as a persistent background process that polls for new unprocessed media
- Externalize configuration to `config.json` with CLI flag overrides
- Robust error handling for iCloud downloads, LLM failures, and Photos.app availability

**Non-Goals:**
- GUI or web interface
- Multi-platform support (macOS only)
- Cloud-hosted LLM support (local LM Studio only)
- Smart scheduling (daemon uses simple fixed-interval polling)
- Automatic model selection or fallback

## Decisions

### 1. CLI Structure: Subcommands with `run` default

The CLI uses subcommands:
- `run` (default) — one-shot batch processing, same as current POC behavior
- `daemon start` — start the daemon in the background
- `daemon stop` — stop a running daemon
- `daemon restart` — stop then start
- `daemon status` — check if daemon is running
- `config show` — display current configuration
- `config set <key> <value>` — update a config value
- `config reset` — reset config to defaults
- `config path` — print the config file path

**Why subcommands over flags:** A `--daemon` flag would mix daemon lifecycle management (start/stop/restart) with processing options. Subcommands keep concerns separate and are more intuitive (`labeler daemon start` vs `labeler --daemon start`).

**Why subcommands over flags:** A `--daemon` flag would mix daemon lifecycle management (start/stop/restart) with processing options. Subcommands keep concerns separate and are more intuitive.

### 2. Daemon Implementation: launchd Launch Agent

The daemon uses macOS's native `launchd` system via a Launch Agent plist at `~/Library/LaunchAgents/com.image-labeler.plist`. This provides:
- **Auto-start on login** — launchd loads agents automatically when the user logs in
- **Auto-restart on crash** — `KeepAlive` key ensures the process is restarted if it exits unexpectedly
- **Proper process lifecycle** — no orphan PID files, no stale processes; launchd owns the lifecycle

The CLI manages the plist:
- `daemon start` — generates the plist from current config, writes it to `~/Library/LaunchAgents/`, runs `launchctl load`
- `daemon stop` — runs `launchctl unload`, removes the plist
- `daemon restart` — unload + load
- `daemon status` — `launchctl list | grep com.image-labeler` to check if running

The plist points to the labeler script with a `run --loop` flag, which runs the processing loop in the foreground (launchd manages backgrounding). The `--loop` flag makes `run` poll continuously at the configured interval instead of exiting after one batch. All processing parameters (limit, days, threads, etc.) are read from config — no CLI flags are passed through the plist. Use `config set` to change daemon behavior, then `daemon restart` to apply.

Logs go to `~/.image-labeler/daemon.log` via the plist's `StandardOutPath`/`StandardErrorPath`.

**Why launchd over os.fork():** Fork-based daemons don't survive login/logout and require manual PID file management. launchd is the macOS-native way to manage persistent background services — it handles auto-start on login, crash recovery, and clean process lifecycle for free.

**Alternative considered:** `os.fork()` with PID file. Simpler to implement but doesn't support auto-start on login, which is a key requirement.

### 3. Config file location: `~/.image-labeler/config.json`

Move config from project directory to `~/.image-labeler/config.json` since this is a user tool, not a project-specific config. The daemon PID file and logs also live in `~/.image-labeler/`.

```
~/.image-labeler/
  config.json      # LM Studio URL, model, default flags
  daemon.pid       # PID of running daemon
  daemon.log       # Daemon output log
```

Config schema (all parameters — daemon reads everything from here):
```json
{
  "base_url": "http://devbox.local:1234/v1",
  "model": "qwen/qwen3.5-9b",
  "poll_interval": 300,
  "limit_per_cycle": 10,
  "days": 7,
  "threads": 4,
  "video_frames": 10,
  "photo": true,
  "video": true,
  "write": true
}
```

The `run` subcommand also reads defaults from config but allows CLI flags to override any value for one-shot runs. The daemon always uses config values — modify via `config set`, then `daemon restart`.

### 4. Parallel Processing: ThreadPoolExecutor with semaphores

Use `concurrent.futures.ThreadPoolExecutor` with max 4 workers. A semaphore limits video processing to 1 concurrent job (videos are heavier — frame extraction + multiple images to LLM).

**Why threads over asyncio:** The bottleneck is I/O (LLM API calls, photo exports), and the OpenAI SDK is synchronous. Threads are simpler and sufficient.

### 5. Project Structure: Single module with clear separation

```
image-labeler/
  labeler/
    __init__.py
    cli.py           # CLI parsing, subcommands (run, daemon, config)
    config.py         # Config loading, defaults, get/set
    daemon.py         # Daemon lifecycle (launchd plist management)
    discovery.py      # Photos library query + filtering
    exporter.py       # Photo/video export (HEIC→JPEG, video frame extraction)
    llm.py            # LLM client, response parsing, retry logic
    writer.py         # Write keywords/title/description back to Photos.app
  requirements.txt
  poc.py              # Original POC (kept for reference)
```

**Why split processor into exporter/llm/writer:** Each has a distinct domain — media export (Pillow, ffmpeg), LLM communication (OpenAI SDK, response parsing), and Photos.app writes (PhotoScript/AppleScript). Splitting makes each file focused and testable independently.

### 6. LLM Response Parsing: Shared utility with retry

Both photo and video labeling need the same response cleaning (strip `<think>` blocks, strip markdown fences, parse JSON). Extract this to a shared function. Add one retry on JSON parse failure with a "please respond with valid JSON only" follow-up message.

## Risks / Trade-offs

- **Stale plist** — If the user changes config, the running daemon still uses the old plist. Mitigation: `daemon restart` regenerates the plist from current config before reloading.
- **Photos.app must be running** — PhotoScript requires Photos.app. If the user quits Photos.app while the daemon is running, writes will fail. Mitigation: Check Photos.app is running before each processing cycle; if not, open it automatically via `subprocess.run(["open", "-a", "Photos"])`.
- **LM Studio availability** — The daemon may start when LM Studio is not running. Mitigation: Health check before each cycle; back off if LM Studio is unreachable.
- **Large library init time** — `osxphotos.PhotosDB()` takes ~20s for 120k photos. In daemon mode this happens every poll cycle. Mitigation: Use `from_date` filter to limit scope; accept the latency since poll interval (5min) dwarfs init time (20s).
- **iCloud download timeouts** — Videos especially may take long to download. Mitigation: Use generous timeouts (300s for video, 120s for photo) and skip items that fail.

### 7. Error Handling: Distinguish network errors from item errors

Two categories of failures with different strategies:

- **Network errors** (LM Studio unreachable, connection timeout, HTTP 5xx): Retry indefinitely with a 1-2 minute delay between attempts. These are transient — the server will come back.
- **Item errors** (JSON parse failure after retry, export failure, invalid image): Track per-item failure count. After 10 failed attempts for the same item, stop processing entirely and log an error. This prevents silently burning cycles on a corrupted photo while also catching systemic issues (e.g., model producing bad output).

Failed item tracking is in-memory per daemon cycle — restarting the daemon resets retry counts.
