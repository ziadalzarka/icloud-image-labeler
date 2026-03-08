## 1. Project Setup

- [x] 1.1 Create `labeler/` package directory with `__init__.py`
- [x] 1.2 Create `labeler/config.py` — config loading, defaults, `~/.image-labeler/` directory creation, auto-create `config.json` on first run
- [x] 1.3 Update `requirements.txt` with all dependencies (osxphotos, photoscript, openai, Pillow, pillow-heif)

## 2. Media Discovery

- [x] 2.1 Create `labeler/discovery.py` — query Photos library for unprocessed media (no keywords, not hidden), sorted by date added
- [x] 2.2 Implement media type filtering (photo only, video only, all)
- [x] 2.3 Implement limit and days-back parameters
- [x] 2.4 Handle iCloud-only media export with `use_photos_export=True` and appropriate timeouts (120s photo, 300s video)

## 3. Media Export

- [x] 3.1 Create `labeler/exporter.py` — photo export with HEIC-to-JPEG conversion (Pillow + pillow-heif, quality 85)
- [x] 3.2 Implement video frame extraction using ffmpeg (configurable frame count, equal intervals)
- [x] 3.3 Base64 encoding for photo and video frames

## 4. LLM Integration

- [x] 4.1 Create `labeler/llm.py` — OpenAI client setup for LM Studio
- [x] 4.2 Implement photo labeling (single image request with system prompt)
- [x] 4.3 Implement video labeling (multi-image request with video system prompt)
- [x] 4.4 Implement response parsing — strip `<think>` blocks, strip markdown code fences, parse JSON
- [x] 4.5 Implement retry on JSON parse failure (one follow-up message asking for valid JSON)

## 5. Metadata Writer

- [x] 5.1 Create `labeler/writer.py` — write keywords, title, description to Photos.app via PhotoScript
- [x] 5.2 Append `ocr:<text>` keyword when OCR text is present
- [x] 5.3 Check if Photos.app is running before writing; auto-open via `open -a Photos` if not
- [x] 5.4 Implement dry-run mode (print metadata without writing)

## 6. Batch Processing

- [x] 6.1 Implement ThreadPoolExecutor-based parallel processing with configurable thread count
- [x] 6.2 Add semaphore to limit video processing to 1 concurrent job
- [x] 6.3 Implement network error detection and retry with 1-2 minute delay
- [x] 6.4 Implement per-item failure tracking — stop processing after 10 failures for the same item

## 7. CLI

- [x] 7.1 Create `labeler/cli.py` — argument parser with `run`, `daemon`, and `config` subcommands
- [x] 7.2 Implement `run` subcommand — one-shot batch processing with CLI flag overrides over config
- [x] 7.3 Implement `run --loop` flag — continuous polling at configured interval
- [x] 7.4 Implement `config show`, `config set`, `config reset`, `config path` actions
- [x] 7.5 Wire up `__main__.py` entry point

## 8. Daemon

- [x] 8.1 Create `labeler/daemon.py` — generate launchd plist for `~/Library/LaunchAgents/com.image-labeler.plist`
- [x] 8.2 Implement `daemon start` — write plist, `launchctl load`
- [x] 8.3 Implement `daemon stop` — `launchctl unload`, remove plist
- [x] 8.4 Implement `daemon restart` — unload, regenerate plist from current config, reload
- [x] 8.5 Implement `daemon status` — check `launchctl list` for com.image-labeler
- [x] 8.6 Configure plist with `KeepAlive`, `StandardOutPath`/`StandardErrorPath` to `~/.image-labeler/daemon.log`
