import importlib.util
import logging
import time
from dataclasses import dataclass

import osxphotos

from labeler.exporter import video_audio
from labeler.writer import (
    NO_AUDIO_TAG,
    NO_SPEECH_TAG,
    TRANSCRIPT_TAG_PREFIX,
    normalize_keyword,
)

logger = logging.getLogger(__name__)

INSTALL_HINT = "pip install 'icloud-image-labeler[transcribe]'"
NO_SPEECH_PROB_LIMIT = 0.5
PCM_SCALE = 32768.0
LOG_PREVIEW_CHARS = 80


@dataclass(frozen=True)
class Transcript:
    keyword: str
    text: str = ""


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


def existing_transcript(item: osxphotos.PhotoInfo) -> Transcript | None:
    keyword = next(
        (k for k in item.keywords or () if k.startswith(TRANSCRIPT_TAG_PREFIX)), None
    )
    if keyword is None:
        return None
    if keyword in (NO_AUDIO_TAG, NO_SPEECH_TAG):
        return Transcript(keyword)
    return Transcript(keyword, keyword.removeprefix(TRANSCRIPT_TAG_PREFIX))


def _speech_transcript(pcm: bytes | None, model: str) -> tuple[Transcript, str | None]:
    if not pcm:
        return Transcript(NO_AUDIO_TAG), None
    text, language = _transcribe_audio(pcm, model)
    if not text:
        return Transcript(NO_SPEECH_TAG), language
    return Transcript(f"{TRANSCRIPT_TAG_PREFIX}{text}", text), language


def transcribe_video(video_path: str, filename: str, model: str) -> Transcript:
    t_start = time.monotonic()
    transcript, language = _speech_transcript(video_audio(video_path, filename), model)
    preview = normalize_keyword(transcript.keyword)[:LOG_PREVIEW_CHARS]
    if len(transcript.keyword) > LOG_PREVIEW_CHARS:
        preview += "..."
    logger.info(
        f"Transcribed {filename} "
        f"[{language or '-'}, {time.monotonic() - t_start:.1f}s] {preview}"
    )
    return transcript
