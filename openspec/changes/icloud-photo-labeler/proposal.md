## Why

Managing a large iCloud Photos library (120k+ photos) is painful — photos lack meaningful keywords, making search unreliable. Apple's built-in ML tagging is limited and not customizable. Running a local LLM (via LM Studio) to auto-generate keywords, descriptions, and OCR text for every photo and video would make the entire library searchable and organized — without sending data to the cloud.

## What Changes

- Build a Python CLI tool using `osxphotos` (reading) and `PhotoScript` (writing) to interact with iCloud Photos
- Query the Photos library for unprocessed photos and videos (missing keywords), filtered by date range and sorted by date added
- Export photo/video data and send to a local LM Studio instance (OpenAI-compatible API at `devbox.local:1234`) for:
  - Keyword/tag generation (scene, objects, people, activities)
  - OCR (extract visible text from photos/videos)
  - Description and title generation
- For photos: convert HEIC to JPEG (via Pillow + pillow-heif) before sending to the LLM
- For videos: extract 10 frames at equal intervals using ffmpeg, send all frames to the LLM as video context
- Handle iCloud-only (missing) media by downloading via Photos.app export (`use_photos_export=True`)
- Strip `<think>` blocks from Qwen model responses before parsing JSON
- Write generated keywords, title, and description back to Photos.app via `PhotoScript`
- Support dry-run mode (default) to preview AI-generated tags before committing

## Capabilities

### New Capabilities
- `media-discovery`: Query iCloud Photos library for unprocessed photos and videos using `osxphotos` — filter by date range, sort by date added, handle iCloud-only downloads
- `ai-labeling`: Send media to local LM Studio (OpenAI-compatible vision API) for keyword generation, OCR, title, and description. Photos sent as JPEG; videos sent as 10 extracted frames.
- `photo-metadata-writer`: Write keywords, title, and description back to Photos.app using `PhotoScript` (AppleScript wrapper)
- `batch-processing`: Process media in bulk with parallel execution (max 4 threads: up to 3 photos + 1 video concurrently, only 1 video at a time), progress tracking, and resume capability (track processed items to avoid re-processing)
- `cli`: Command-line interface with the following parameters:

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--limit` | int | `1` | Number of media items to process |
| `--days` | int | `7` | Look back N days for unprocessed media |
| `--photo` | flag | on | Process photos (use `--no-photo` to skip) |
| `--video` | flag | on | Process videos (use `--no-video` to skip) |
| `--write` | flag | on | Write metadata to Photos.app (use `--no-write` / `--dry-run` to preview) |
| `--base-url` | string | from config | LM Studio API base URL |
| `--model` | string | from config | Model name in LM Studio |
| `--threads` | int | `4` | Max parallel processing threads |
| `--video-frames` | int | `10` | Number of frames to extract from videos |

Configuration is stored in `config.json`:
```json
{
  "base_url": "http://devbox.local:1234/v1",
  "model": "qwen/qwen3.5-9b"
}
```
CLI flags override config values when provided.

### Modified Capabilities
<!-- No existing capabilities to modify — this is a greenfield project -->

## Impact

- **Platform**: macOS only (requires Photos.app + AppleScript support)
- **Dependencies**: Python 3.11+, `osxphotos`, `photoscript`, `openai`, `Pillow`, `pillow-heif`, `ffmpeg` (system), LM Studio running on local network (`devbox.local:1234`)
- **Permissions**: Full Photos library access, network access to LM Studio
- **Technical constraints**:
  - `osxphotos.PhotosDB()` loads the full SQLite database on init (~20s for 120k photos) — use `from_date` filter to limit query scope
  - HEIC photos must be converted to JPEG before sending to LM Studio (Pillow + pillow-heif)
  - iCloud-only photos/videos (`ismissing=True`) require `use_photos_export=True` to trigger download
  - Qwen models include `<think>` blocks in responses — must be stripped before JSON parsing (LM Studio ignores `enable_thinking` API parameter)
  - `PhotoScript` writes via AppleScript — slow per item (round-trip), need batching/queuing
  - iCloud Photos sync means changes propagate to all devices after writing
  - Photos.app must be running for AppleScript writes to work
