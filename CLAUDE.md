# Project Instructions

## Git

- Do not include "Co-Authored-By" lines in commit messages.

## Project Overview

macOS CLI tool that auto-labels iCloud Photos using a local LLM (LM Studio). Queries the Photos library for unprocessed media, sends to LLM for keyword/title/description/OCR generation, and writes metadata back via PhotoScript.

## Architecture

- `labeler/` — main package, run with `python -m labeler`
  - `cli.py` — argparse CLI with `run`, `daemon`, `config`, `migrate` subcommands
  - `config.py` — `~/.image-labeler/config.json` management
  - `daemon.py` — launchd Launch Agent lifecycle
  - `discovery.py` — osxphotos query for unprocessed media
  - `exporter.py` — HEIC-to-JPEG conversion, video frame extraction (ffmpeg)
  - `llm.py` — OpenAI-compatible LLM client, response parsing, retry
  - `processor.py` — batch orchestration, parallel photos then sequential videos, error tracking
  - `transcriber.py` — optional mlx-whisper transcription of videos, called from video processing
  - `migrate.py` — `migrate normalize-keywords` command for existing libraries
  - `writer.py` — PhotoScript metadata writes with thread-safe locking

## Key Constraints

- `use_photos_export=True` always (not just for missing/iCloud-only files)
- PhotoScript writes must be serialized (AppleScript is single-threaded) — `_write_lock` in `writer.py`
- Photos processed in parallel, videos sequentially (separate phases in `processor.py`)
- Video frames are labeled `video_frame_batch` at a time, then a text-only request merges the batch labels (`label_video` in `llm.py`)
- Videos get a `v:<hash>` keyword of `video_frames`/`video_frame_batch` next to the `m:` model tag. Normal runs relabel up to `OUTDATED_VIDEOS_PER_CYCLE` videos per cycle that have an `m:` tag but not the current `v:` tag (loop mode skips the sleep while more remain); `--reindex` takes all of them
- The video merge request sends `reasoning_effort="none"` (thinking made it take 110-300s); servers that reject the parameter get the request again without it
- Qwen models return `<think>` blocks — stripped before JSON parsing in `llm.py`
- Images resized to `max_dimension` before sending to LLM to avoid context window exhaustion
- All keywords are written lowercase, without commas, and deduplicated (`normalize_keywords` in `writer.py`). Photos' Info window splits keywords at commas when the keyword field is clicked
- Under Homebrew the daemon plist uses `/opt/homebrew/opt/icloud-image-labeler/...`, not the versioned Cellar path that `brew upgrade` deletes (`_homebrew_opt_path` in `daemon.py`)
- Transcription is optional (`transcribe` config, `mlx-whisper` is an optional extra) and part of video labeling: the video is exported once, transcribed, and the transcript goes into the merge request (`label_video`), so labels use what is said. A video with a `trans:` keyword reuses it instead of running Whisper again. Every video gets one of `trans:<text>`, `trans:no-speech` or `trans:no-audio`
- Labeled videos (`m:` tag) without a `trans:` keyword are found by `get_untranscribed_videos`, up to `UNTRANSCRIBED_VIDEOS_PER_CYCLE` per cycle, and handled after the cycle's other videos: transcribe, then a text-only request (`add_transcript_to_labels`) updates title, description and keywords. Their `m:`/`v:`/`ocr:` keywords are kept (`write_labels_with_transcript`). These rows are recorded in metrics with `media_type='transcript'`
- Labeling keeps `trans:` keywords when it rewrites keywords, and a video whose only keywords are `trans:` ones still counts as unlabeled (`is_unlabeled` in `discovery.py`)
- Whisper segments with `no_speech_prob` above 0.5 are dropped; Whisper invents text like "Thank you for watching" on silent audio
- Audio is taken from the first audio track (`-map 0:a:0`); newer iPhone videos also carry an `apple_apac` spatial audio track that older ffmpeg builds can't decode
