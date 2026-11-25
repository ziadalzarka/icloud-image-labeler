# iCloud Image Labeler

Auto-label your Apple Photos library using any OpenAI-compatible LLM. Generates keywords, titles, descriptions, and OCR text for photos and videos, then writes the metadata back into Photos.app. Optionally transcribes speech in videos with a local [Whisper](https://github.com/openai/whisper) model, in any of its 99 languages.

Works with any OpenAI-compatible API — designed for [LM Studio](https://lmstudio.ai/) but also works with Ollama, vLLM, or cloud providers.

## How It Works

```
Photos.app ──> Discovery ──> Export ──> LLM ──> Writer ──> Photos.app
               (osxphotos)   (Pillow)   (API)   (PhotoScript)
```

1. **Discovery** — Queries the Photos library for media with no keywords set, filtered by date range and media type. Items this tool labeled with another model, and videos it labeled with other frame settings, are relabeled too, newest first, up to 2,000 photos and 200 videos per cycle; while more remain, the next cycle starts right away instead of waiting for the poll interval.
2. **Export** — Gets each photo from Photos at `max_dimension` as JPEG and each video at 720p (exporting the original when Photos can't), then extracts frames from videos via ffmpeg (evenly spaced, at most 2 per second).
3. **LLM** — Sends images to an OpenAI-compatible API. Returns structured JSON with keywords, title, description, and OCR text. Video frames are sent in batches, and a final text-only request merges the batch results into one set of labels.
4. **Writer** — Writes metadata back into Photos.app via PhotoScript (AppleScript automation).

Items are exported one at a time, and each one's LLM requests and Photos write run in worker threads (up to `threads` at once), so the next item exports while earlier ones are labeled. All photos go first, then videos. Requests that fail with a rate limit (429) are retried with backoff.

### Transcription (optional)

```
Photos.app ──> Export ──> ffmpeg ──> Whisper ──> LLM ──> Writer ──> Photos.app
               (video)    (audio)    (mlx-whisper)  (labels use what is said)
```

Transcription is part of video labeling. Before a video's frame labels are merged, its audio is transcribed with Whisper, and the merge request gets the transcript too, so the title, description and keywords can say what people talk about. The prompt tells the model that the transcript can be wrong and to ignore parts that don't fit the frames. If transcription fails, the video is labeled without it. Each video gets one keyword:

| Keyword | Meaning |
|---------|---------|
| `trans:<text>` | What was said in the video |
| `trans:no-speech` | The video has audio, but Whisper found no speech in it |
| `trans:no-audio` | The video has no audio track |

Videos with any `trans:` keyword are not transcribed again, and relabeling a video reuses its transcript. A video with only a `trans:` keyword still counts as unlabeled.

Whisper often writes text nobody said: on music, noise or silence it produces stock phrases from the videos it was trained on ("thank you for watching", "اشتركوا في القناة"), loops of one phrase, or speech in a language that isn't there. To keep that out of the keywords:

- With `whisper_languages` set, the language is detected for every 30 seconds of audio. Parts where none of the listed languages is likely (usually music or noise) are skipped, and each other part is transcribed in its own language, so a video that switches between Arabic and English keeps both.
- Segments are dropped when Whisper's own scores say they are unreliable: very low confidence (average log probability below -1.0, the point where Whisper itself gives up), repetition loops (compression ratio above 2.4), or likely silence (no-speech probability above 0.85, or above 0.6 with low confidence).
- Segments that contain nothing but a known made-up phrase are dropped.

Videos this tool labeled before transcription was turned on are transcribed after the cycle's other videos, up to 500 per cycle; while more remain, the next cycle starts right away. When one has speech, a text-only request updates its title, description and keywords with the transcript, without sending the frames again. Its `m:`, `v:` and `ocr:` keywords stay as they were.

### Keywords

All keywords the tool writes are lowercase and have no commas, including `ocr:` and `trans:` text. The keyword field in Photos' Info window splits a keyword at every comma when you click into it, so commas between digits are dropped (`3,000` becomes `3000`) and other commas become a space. Besides the descriptive keywords, the tool adds:

| Keyword | Meaning |
|---------|---------|
| `m:<hash>` | Which model labeled the item |
| `v:<hash>` | Which video frame settings were used |
| `ocr:<text>` | Text visible in the photo or video |
| `trans:...` | Speech transcript (see above) |

## Requirements

- macOS (requires Photos.app and AppleScript)
- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) (for video frame extraction)
- An OpenAI-compatible LLM API ([LM Studio](https://lmstudio.ai/), Ollama, etc.)
- For transcription only: Apple Silicon and [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)

## Installation

```sh
brew tap ziadalzarka/tap
brew install icloud-image-labeler
```

### Transcription

Transcription is optional and off by default. It needs `mlx-whisper`, which only runs on Apple Silicon:

```sh
# Homebrew install
$(brew --prefix icloud-image-labeler)/libexec/bin/pip install mlx-whisper

# pip install
pip install 'icloud-image-labeler[transcribe]'

# Turn it on
icloud-image-labeler config set transcribe true
```

The default model, `mlx-community/whisper-large-v3-mlx` (about 3 GB), downloads on first use. Any Whisper model in MLX format works; set it with `config set whisper_model <hugging face repo>`.

Whisper guesses each video's language from its first 30 seconds, and it often guesses wrong on dialects, background noise or music. It then writes the speech out in the wrong language, which reads as nonsense. If you know which languages your videos are in, list them, and Whisper picks the most likely one from that list:

```sh
icloud-image-labeler config set whisper_languages ar,en
```

Codes are Whisper's two-letter language codes (`ar`, `en`, `fr`, ...). With one language, detection is skipped.

#### Transcribing on another machine

Whisper can run on another machine with a GPU instead of this Mac. `devbox/whisper/` has a small server for that: faster-whisper `large-v3` in a CUDA container, which loads the model on the first request and unloads it after 5 minutes with no requests. The Mac sends each video's audio and keeps all the steps above (language per 30 seconds, dropping made-up text), so transcripts come out the same way. mlx-whisper isn't needed on the Mac then.

Huddle's live transcription uses the same server, so devbox only ever loads Whisper once. Its short phrases go ahead of videos waiting in line, but wait for the one being transcribed.

```sh
icloud-image-labeler config set whisper_url http://devbox.local:8178
icloud-image-labeler config set whisper_api_key <the server's key>
```

If the server doesn't answer, new videos are labeled without a transcript and get one in a later cycle, once it answers again.

### iCloud Settings

The labeler asks Photos for a smaller version of each item: photos at `max_dimension` and videos at 720p. Photos often already has these on the Mac, and when it doesn't, iCloud sends the smaller version instead of the original, so a 700 MB 4K video becomes a download of about 45 MB. The first time, macOS asks whether Python may access your Photos; allow it. Without that access, or for items Photos can't give a smaller version of (such as slow-motion videos), the labeler exports the original through Photos as before.

**Download Originals to this Mac** (System Settings → Apple Account → iCloud → Photos) is no longer needed for speed.

## Quick Start

```sh
# Interactive setup — connects to your LLM and picks a model
icloud-image-labeler init

# Process all unprocessed media
icloud-image-labeler run
```

## Usage

```sh
# Process 5 items from the last 30 days
icloud-image-labeler run --limit 5 --days 30

# Preview without writing (dry run)
icloud-image-labeler run --dry-run

# Photos only, skip videos
icloud-image-labeler run --no-video

# Process media from 60 to 30 days ago
icloud-image-labeler run --days 60 --to-days 30

# Process specific photos by UUID
icloud-image-labeler run --uuid ABC123 DEF456

# Run continuously (daemon-style loop)
icloud-image-labeler run --loop

# Use a specific model or API endpoint
icloud-image-labeler run --base-url http://localhost:1234/v1 --model my-model

# Transcribe speech in videos and use it in their labels
icloud-image-labeler run --transcribe

# Debug logging
icloud-image-labeler run -v
```

### All `run` Options

| Flag | Description |
|------|-------------|
| `--limit N` | Max items to process |
| `--days N` | Look back N days (0 = all time) |
| `--to-days N` | Skip most recent N days |
| `--photo` / `--no-photo` | Include/exclude photos |
| `--video` / `--no-video` | Include/exclude videos |
| `--transcribe` / `--no-transcribe` | Transcribe speech in videos and use it in their labels (needs mlx-whisper) |
| `--whisper-model REPO` | Whisper model for transcription |
| `--whisper-url URL` | Whisper server to send audio to instead of running mlx-whisper on this Mac |
| `--whisper-languages CODES` | Languages speech can be in, e.g. `ar,en` |
| `--write` | Force write metadata |
| `--dry-run` | Preview without writing |
| `--base-url URL` | LLM API endpoint |
| `--api-key KEY` | API key for LLM |
| `--model NAME` | Model identifier |
| `--threads N` | Items labeled at once |
| `--video-frames N` | Frames to extract per video |
| `--video-frame-batch N` | Video frames per LLM request (0 = all in one) |
| `--uuid UUID [...]` | Process specific photo UUIDs |
| `--loop` | Run continuously with poll interval |
| `--reindex` | Reprocess everything labeled by a different model, or videos labeled with different frame settings, in one run with no per-cycle limit, and items with keywords but no model tag |
| `-v, --verbose` | Debug logging |

## Configuration

Config is stored at `~/.image-labeler/config.json`. Run `icloud-image-labeler init` for interactive setup, or manage directly:

```sh
icloud-image-labeler config show          # View current config
icloud-image-labeler config set days 14   # Update a value
icloud-image-labeler config reset         # Reset to defaults
icloud-image-labeler config path          # Print config file path
```

If no config exists when you run `icloud-image-labeler run`, the setup wizard launches automatically.

| Key | Default | Description |
|-----|---------|-------------|
| `base_url` | `http://localhost:1234/v1` | OpenAI-compatible API endpoint |
| `api_key` | `""` | API key (optional, empty for local LM Studio) |
| `model` | `qwen/qwen3.5-9b` | Model identifier |
| `reasoning_effort` | `""` | Thinking level sent with every request, e.g. `low`, `medium`, `high` (empty = the server's default, and `none` for video merge requests) |
| `days` | `0` | Look back N days (0 = all time) |
| `to_days` | `0` | Skip most recent N days |
| `limit_per_cycle` | `0` | Items per cycle (0 = all) |
| `threads` | `4` | Max items labeled at once |
| `video_frames` | `30` | Frames to extract from videos |
| `video_frame_batch` | `5` | Video frames per LLM request (0 = all in one) |
| `max_dimension` | `1024` | Max image dimension sent to LLM (px) |
| `photo` | `true` | Include photos in processing |
| `video` | `true` | Include videos in processing |
| `transcribe` | `false` | Transcribe speech in videos and use it in their labels (needs mlx-whisper) |
| `whisper_model` | `mlx-community/whisper-large-v3-mlx` | Whisper model for transcription |
| `whisper_languages` | `""` | Comma-separated languages speech can be in, e.g. `ar,en` (empty = any) |
| `whisper_url` | `""` | Whisper server to send audio to (empty = mlx-whisper on this Mac) |
| `whisper_api_key` | `""` | Key for the Whisper server |
| `write` | `true` | Write metadata to Photos.app |
| `poll_interval` | `300` | Seconds between cycles in loop/daemon mode |

## Migrations

Libraries labeled by earlier versions can be converted to lowercase keywords without commas with:

```sh
icloud-image-labeler migrate normalize-keywords --dry-run   # Show what would change
icloud-image-labeler migrate normalize-keywords             # Normalize every keyword in the library
```

This changes every keyword in the library, including ones you added by hand. It only touches items that still need changing, so it can be stopped and run again. Before changing an item, it saves the item's original keywords to `~/.image-labeler/backups/keywords-<time>.jsonl`. It writes to Photos several times a second, so Photos is slow to respond while it runs. `lowercase-keywords` from 0.2.0 still works and does the same thing.

Transcripts made by earlier versions, or before you changed `whisper_languages` or `whisper_model`, can be redone:

```sh
icloud-image-labeler migrate redo-transcripts --dry-run   # Show what would change
icloud-image-labeler migrate redo-transcripts             # Remove trans: keywords so videos are transcribed again
```

This removes every `trans:` keyword except `trans:no-audio`, saving the originals to `~/.image-labeler/backups/transcripts-<time>.jsonl` first. The next runs transcribe those videos again with the current settings and update their labels when there is speech.

## Daemon

Run as a background service that auto-starts on login via macOS Launch Agent:

```sh
icloud-image-labeler daemon start     # Install and start Launch Agent
icloud-image-labeler daemon status    # Running or paused, what's labeling now, speed, models, library split
icloud-image-labeler daemon pause     # Leave Photos alone for a while
icloud-image-labeler daemon pause --minutes 10  # Same, then carry on by itself
icloud-image-labeler daemon resume    # Carry on after a pause
icloud-image-labeler daemon restart   # Apply config changes
icloud-image-labeler daemon stop      # Uninstall Launch Agent
```

The daemon runs as `com.image-labeler` under `~/Library/LaunchAgents/`. It auto-restarts on crash and starts on login. Logs go to `~/.image-labeler/daemon.log`.

Photos.app is slow to respond while the labeler writes to it. `daemon pause` stops all exports and writes, so you can use Photos. Requests already sent to the LLM finish, and their results are written after `daemon resume`. With `--minutes` (1 to 60) it carries on by itself after that long. Without it, if you don't resume within an hour, the daemon stops for good. It removes its Launch Agent and stays stopped, even after a login, until you run `daemon start`. Running `daemon pause` again starts a new pause. A labeler started with `run` also pauses.

## Metrics

Processing metrics are stored in SQLite at `~/.image-labeler/metrics.db`.

```sh
icloud-image-labeler metrics serve              # Open Datasette UI at http://localhost:8001
icloud-image-labeler metrics serve --port 9000  # Custom port
icloud-image-labeler metrics path               # Print database path
```

**Per-item metrics:** export/LLM/write durations, image dimensions, LLM retry count, keyword count, OCR presence, error details, and model used.

**Per-run metrics:** items found/processed/failed, wall-clock duration, model, thread count, and average LLM latency.

## Architecture

```
labeler/
  cli.py        — argparse CLI (init, run, daemon, config, metrics subcommands)
  init.py       — interactive first-run setup wizard
  config.py     — ~/.image-labeler/config.json management
  discovery.py  — osxphotos query for unprocessed media
  exporter.py   — smaller photo and video versions via PhotoKit, Photos export fallback, video frame extraction
  llm.py        — OpenAI-compatible client, JSON parsing, retry logic
  processor.py  — batch orchestration: export in turn, label and write in parallel
  transcriber.py — optional Whisper transcription of videos (local or on a server), used by video labeling
  migrate.py    — one-off keyword migrations (normalize-keywords)
  writer.py     — PhotoScript metadata writes (thread-safe)
  metrics.py    — SQLite metrics recording
  daemon.py     — macOS Launch Agent lifecycle
  pause.py      — pausing exports and writes, and stopping after an hour paused
  report.py     — the text `daemon status` prints (progress, speed, averages, models)
  library.py    — per-cycle summary of the library by model tag, for `daemon status`
  shutdown.py   — graceful shutdown (SIGINT/SIGTERM handling)
  checks.py     — pre-flight dependency checks (ffmpeg, Photos.app)
```

## License

MIT
