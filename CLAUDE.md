# Project Instructions

## Git

- Do not include "Co-Authored-By" lines in commit messages.

## Project Overview

macOS CLI tool that auto-labels iCloud Photos using a local LLM (LM Studio). Queries the Photos library for unprocessed media, sends to LLM for keyword/title/description/OCR generation, and writes metadata back via PhotoScript.

## Architecture

- `labeler/` — main package, run with `python -m labeler`
  - `cli.py` — argparse CLI with `run`, `daemon`, `config`, `migrate` subcommands
  - `config.py` — `~/.image-labeler/config.json` management
  - `daemon.py` — launchd Launch Agent lifecycle, `daemon pause`/`resume`
  - `pause.py` — the `~/.image-labeler/paused` file, waiting while it exists, and the thread that stops the labeler after an hour paused
  - `discovery.py` — osxphotos query for unprocessed media
  - `exporter.py` — PhotoKit requests for smaller photo and video versions, Photos export fallback with HEIC-to-JPEG conversion, video frame extraction (ffmpeg)
  - `llm.py` — OpenAI-compatible LLM client, response parsing, retry
  - `processor.py` — batch orchestration: photos then videos, each exported on the main thread and labeled and written in worker threads, error tracking
  - `transcriber.py` — optional Whisper transcription of videos, with mlx-whisper on the Mac or a Whisper server (`whisper_url`), called from video processing
  - `migrate.py` — `migrate normalize-keywords` and `migrate redo-transcripts` commands for existing libraries
  - `writer.py` — PhotoScript metadata writes with thread-safe locking
- `devbox/whisper/` — the faster-whisper server (Docker, CUDA) that runs on devbox

## Key Constraints

- Photos are requested through PhotoKit at `max_dimension` (`_photokit_image`) and videos as Photos' 720p version (`_medium_quality_video`), both on the main thread, so iCloud-only items don't download the original (a 4K video is 360-700 MB, iCloud gives about 4.7 MB/s). When PhotoKit access isn't allowed or returns nothing (e.g. slow-motion videos give an `AVComposition`), the Photos export of the original is used
- `use_photos_export=True` always for that export (not just for missing/iCloud-only files)
- PhotoScript writes must be serialized (AppleScript is single-threaded) — `_write_lock` in `writer.py`
- `daemon pause` makes `~/.image-labeler/paused`. While it exists no export starts and every Photos write waits (`_photos_write` in `writer.py`, which checks before and after taking `_write_lock`). A write still waiting when the labeler stops raises `StoppedWhilePausedError` and writes nothing. After `PAUSE_LIMIT_S` (1 hour, counted from the file's mtime) the daemon unlinks its plist and runs `launchctl remove`, so launchd sends SIGTERM and doesn't restart it; a `run` in a terminal just stops. The daemon is told apart by `XPC_SERVICE_NAME`. `daemon start` clears the pause, and a new run clears one that has expired
- Exports run one at a time on the main thread (osxphotos SQLite is bound to it); LLM requests and the Photos write run in up to `threads` worker threads. Photos and videos are separate phases in `processor.py` (`_label_in_parallel`). A 429 from the LLM server is retried with backoff
- Video frames are labeled `video_frame_batch` at a time, then a text-only request merges the batch labels (`label_video` in `llm.py`)
- Videos get a `v:<hash>` keyword of `video_frames`/`video_frame_batch` next to the `m:` model tag. Normal runs relabel items that have an `m:` tag of a model no server in the pool uses, and videos without the current `v:` tag, newest first, up to `OUTDATED_PHOTOS_PER_CYCLE` photos and `OUTDATED_VIDEOS_PER_CYCLE` videos per cycle (loop mode skips the sleep while more remain); `--reindex` takes all of them
- The `reasoning_effort` config (per server or global) is sent with every request when set. When it's empty, photo and frame requests send none and the video merge request sends `reasoning_effort="none"` (thinking made it take 110-300s on a local Qwen); servers that reject the parameter get the request again without it
- Qwen models return `<think>` blocks — stripped before JSON parsing in `llm.py`
- Images resized to `max_dimension` before sending to LLM to avoid context window exhaustion
- All keywords are written lowercase, without commas, and deduplicated (`normalize_keywords` in `writer.py`). Photos' Info window splits keywords at commas when the keyword field is clicked
- Under Homebrew the daemon plist uses `/opt/homebrew/opt/icloud-image-labeler/...`, not the versioned Cellar path that `brew upgrade` deletes (`_homebrew_opt_path` in `daemon.py`)
- Transcription is optional (`transcribe` config, `mlx-whisper` is an optional extra, or `whisper_url` points at the devbox server, which takes 16 kHz int16 PCM on `POST /languages` and `POST /transcribe` and returns Whisper's raw scores so the filtering stays on the Mac) and part of video labeling: the video is exported once, transcribed, and the transcript goes into the merge request (`label_video`), so labels use what is said. A video with a `trans:` keyword reuses it instead of running Whisper again. Every video gets one of `trans:<text>`, `trans:no-speech` or `trans:no-audio`
- Labeled videos (`m:` tag) without a `trans:` keyword are found by `get_untranscribed_videos`, up to `UNTRANSCRIBED_VIDEOS_PER_CYCLE` per cycle, and handled after the cycle's other videos: transcribe, then a text-only request (`add_transcript_to_labels`) updates title, description and keywords. Their `m:`/`v:`/`ocr:` keywords are kept (`write_labels_with_transcript`). These rows are recorded in metrics with `media_type='transcript'`
- Labeling keeps `trans:` keywords when it rewrites keywords, and a video whose only keywords are `trans:` ones still counts as unlabeled (`is_unlabeled` in `discovery.py`)
- Whisper invents text on music, noise and silence ("thank you for watching", "اشتركوا في القناة", text in a language nobody spoke). With `whisper_languages` set, the language is detected per 30 s window; windows where the listed languages together score below 0.5 are skipped and each other window is transcribed in its own language (`_window_languages` in `transcriber.py`). Segments are dropped by `_is_speech`: avg_logprob below -1.0, compression_ratio above 2.4, no_speech_prob above 0.85 (or above 0.6 with avg_logprob below -0.5), or only phrases from `MADE_UP_PHRASES`. These thresholds were picked on 75 videos from the library; song lyrics score 0.6-0.8 no_speech_prob and are kept
- `migrate redo-transcripts` removes `trans:` keywords (keeping `trans:no-audio`) so videos are transcribed again with the current settings
- Audio is taken from the first audio track (`-map 0:a:0`); newer iPhone videos also carry an `apple_apac` spatial audio track that older ffmpeg builds can't decode
