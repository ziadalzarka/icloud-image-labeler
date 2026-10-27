import gc
import importlib.util
import logging
import threading
import time

import osxphotos

from labeler.exporter import export_video_audio
from labeler.shutdown import is_shutting_down
from labeler.shutdown import wait as shutdown_wait
from labeler.writer import (
    NO_AUDIO_TAG,
    NO_SPEECH_TAG,
    TRANSCRIPT_TAG_PREFIX,
    normalize_keyword,
    write_transcript,
)

logger = logging.getLogger(__name__)

INSTALL_HINT = "pip install 'icloud-image-labeler[transcribe]'"
NO_SPEECH_PROB_LIMIT = 0.5
MAX_FAILURES = 3
PCM_SCALE = 32768.0
LOG_PREVIEW_CHARS = 80
DISCOVERY_RETRY_S = 300


def is_available() -> bool:
    return importlib.util.find_spec("mlx_whisper") is not None


def _speech_text(segments: list[dict]) -> str:
    return " ".join(
        s["text"].strip()
        for s in segments
        if s["no_speech_prob"] <= NO_SPEECH_PROB_LIMIT and s["text"].strip()
    )


def _transcribe_audio(pcm: bytes, model: str) -> tuple[str, str | None]:
    import mlx_whisper
    import numpy as np

    audio = np.frombuffer(pcm, np.int16).astype(np.float32) / PCM_SCALE
    result = mlx_whisper.transcribe(
        audio, path_or_hf_repo=model, condition_on_previous_text=False
    )
    return _speech_text(result["segments"]), result.get("language")


def _transcript_keyword(
    item: osxphotos.PhotoInfo, model: str
) -> tuple[str, str | None]:
    pcm = export_video_audio(item)
    if not pcm:
        return NO_AUDIO_TAG, None
    text, language = _transcribe_audio(pcm, model)
    if not text:
        return NO_SPEECH_TAG, language
    return f"{TRANSCRIPT_TAG_PREFIX}{text}", language


class Transcriber:
    def __init__(self, model: str, write: bool):
        self.model = model
        self.write = write
        self._failures: dict[str, int] = {}

    def start(self, discover, loop: bool, poll_interval: int) -> threading.Thread:
        thread = threading.Thread(
            target=self._run,
            args=(discover, loop, poll_interval),
            name="transcriber",
            daemon=True,
        )
        thread.start()
        return thread

    def _run(self, discover, loop: bool, poll_interval: int):
        while not is_shutting_down():
            found = self._run_pass(discover)
            gc.collect()
            if not loop:
                return
            wait = poll_interval if found else DISCOVERY_RETRY_S
            logger.info(f"Transcription sleeping {wait}s until next pass...")
            if shutdown_wait(wait):
                return

    def _run_pass(self, discover) -> bool:
        try:
            items = [
                p for p in discover() if self._failures.get(p.uuid, 0) < MAX_FAILURES
            ]
        except Exception:
            logger.exception("Looking for videos to transcribe failed")
            return False
        if not items:
            logger.info("No videos to transcribe.")
            return True

        logger.info(f"Transcribing {len(items)} videos with {self.model}...")
        for position, item in enumerate(items, start=1):
            if is_shutting_down():
                return True
            progress = f"[transcribe {position}/{len(items)}]"
            try:
                self._transcribe(item, progress)
            except Exception as e:
                self._failures[item.uuid] = self._failures.get(item.uuid, 0) + 1
                logger.error(f"{progress} Failed: {item.original_filename}: {e}")
        return True

    def _transcribe(self, item: osxphotos.PhotoInfo, progress: str):
        t_start = time.monotonic()
        keyword, language = _transcript_keyword(item, self.model)
        write_transcript(item.uuid, keyword, write=self.write)
        preview = normalize_keyword(keyword)[:LOG_PREVIEW_CHARS]
        if len(keyword) > LOG_PREVIEW_CHARS:
            preview += "..."
        logger.info(
            f"{progress} Done: {item.original_filename} "
            f"[{language or '-'}, {time.monotonic() - t_start:.1f}s] {preview}"
        )
