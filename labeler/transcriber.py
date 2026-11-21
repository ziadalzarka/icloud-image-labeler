import functools
import importlib.util
import logging
import re
import time
from dataclasses import dataclass

import httpx
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
PCM_SCALE = 32768.0
LOG_PREVIEW_CHARS = 80
WINDOW_S = 30
MIN_LANGUAGE_PROB = 0.5
MIN_AVG_LOGPROB = -1.0
MAX_COMPRESSION_RATIO = 2.4
NO_SPEECH_PROB_LIMIT = 0.6
SILENCE_AVG_LOGPROB = -0.5
MAX_NO_SPEECH_PROB = 0.85
SERVER_TIMEOUT = 600.0
CONNECT_TIMEOUT = 15.0
HEALTH_TIMEOUT = 15.0
KEEPALIVE_S = 600.0
MADE_UP_PHRASES = (
    "اشتركوا في القناه",
    "اشتركو في القناه",
    "ترجمه نانسي قنقر",
    "شكرا للمشاهده",
    "شكرا علي المشاهده",
    "شكرا لكم علي المشاهده",
    "موسيقي",
    "thank you for watching",
    "thanks for watching",
    "please subscribe",
    "subscribe to the channel",
    "subtitles by the amara org community",
    "music",
)

_ARABIC_MARKS_RE = re.compile(r"[\u064b-\u0652\u0640]")
_ARABIC_LETTER_FORMS = str.maketrans("أإآةى", "اااهي")
_WORD_RE = re.compile(r"\w+")


@dataclass(frozen=True)
class Transcript:
    keyword: str
    text: str = ""


@dataclass(frozen=True)
class Whisper:
    model: str
    languages: tuple[str, ...] = ()
    url: str = ""
    api_key: str = ""


def is_available() -> bool:
    return importlib.util.find_spec("mlx_whisper") is not None


def parse_languages(codes: str) -> tuple[str, ...]:
    languages = tuple(c.strip().lower() for c in codes.split(",") if c.strip())
    if not is_available():
        return languages
    from mlx_whisper.tokenizer import LANGUAGES

    unknown = [c for c in languages if c not in LANGUAGES]
    if unknown:
        logger.warning(f"Ignoring unknown Whisper languages: {', '.join(unknown)}")
    return tuple(c for c in languages if c in LANGUAGES)


@functools.cache
def _server(url: str, api_key: str) -> httpx.Client:
    return httpx.Client(
        base_url=url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=httpx.Timeout(SERVER_TIMEOUT, connect=CONNECT_TIMEOUT),
        limits=httpx.Limits(keepalive_expiry=KEEPALIVE_S),
    )


def server_answers(whisper: Whisper) -> bool:
    if not whisper.url:
        return True
    try:
        _server(whisper.url, whisper.api_key).get(
            "/health", timeout=HEALTH_TIMEOUT
        ).raise_for_status()
    except httpx.HTTPError:
        return False
    return True


def _post_audio(whisper: Whisper, path: str, pcm: bytes, params=None) -> dict:
    response = _server(whisper.url, whisper.api_key).post(
        path,
        content=pcm,
        params=params,
        headers={"Content-Type": "application/octet-stream"},
    )
    response.raise_for_status()
    return response.json()


def _audio(pcm: bytes):
    import numpy as np

    return np.frombuffer(pcm, np.int16).astype(np.float32) / PCM_SCALE


def _local_language_probs(pcm: bytes, whisper: Whisper) -> list[dict[str, float]]:
    import mlx.core as mx
    from mlx_whisper.audio import N_FRAMES, N_SAMPLES, log_mel_spectrogram
    from mlx_whisper.transcribe import ModelHolder

    model = ModelHolder.get_model(whisper.model, mx.float16)
    mel = log_mel_spectrogram(_audio(pcm), n_mels=model.dims.n_mels, padding=N_SAMPLES)
    return [
        model.detect_language(mel[start : start + N_FRAMES].astype(mx.float16))[1]
        for start in range(0, mel.shape[-2] - N_FRAMES, N_FRAMES)
    ]


def _language_probs(pcm: bytes, whisper: Whisper) -> list[dict[str, float]]:
    if whisper.url:
        return _post_audio(whisper, "/languages", pcm)["windows"]
    return _local_language_probs(pcm, whisper)


def _window_languages(pcm: bytes, whisper: Whisper) -> list[str | None]:
    languages = []
    for probs in _language_probs(pcm, whisper):
        listed = sum(probs.get(code, 0.0) for code in whisper.languages)
        languages.append(
            max(whisper.languages, key=lambda code: probs.get(code, 0.0))
            if listed >= MIN_LANGUAGE_PROB
            else None
        )
    return languages


def _clips_by_language(window_languages: list[str | None]) -> dict[str, list[float]]:
    clips: dict[str, list[float]] = {}
    for i, language in enumerate(window_languages):
        if language is None:
            continue
        start, end = i * WINDOW_S, (i + 1) * WINDOW_S
        times = clips.setdefault(language, [])
        if times and times[-1] == start:
            times[-1] = end
        else:
            times += [start, end]
    return clips


def _fold(text: str) -> str:
    text = _ARABIC_MARKS_RE.sub("", text.lower()).translate(_ARABIC_LETTER_FORMS)
    return " ".join(_WORD_RE.findall(text))


def _only_made_up(text: str) -> bool:
    folded = _fold(text)
    for phrase in MADE_UP_PHRASES:
        folded = folded.replace(phrase, " ")
    return not folded.strip()


def _is_speech(segment: dict) -> bool:
    avg_logprob = segment["avg_logprob"]
    if avg_logprob < MIN_AVG_LOGPROB:
        return False
    if segment["compression_ratio"] > MAX_COMPRESSION_RATIO:
        return False
    if segment["no_speech_prob"] > MAX_NO_SPEECH_PROB:
        return False
    if (
        segment["no_speech_prob"] > NO_SPEECH_PROB_LIMIT
        and avg_logprob < SILENCE_AVG_LOGPROB
    ):
        return False
    return not _only_made_up(segment["text"])


def _speech_text(segments: list[dict]) -> str:
    return " ".join(s["text"].strip() for s in segments if _is_speech(s))


def _transcribe(
    pcm: bytes,
    whisper: Whisper,
    language: str | None = None,
    clip_timestamps: list[float] | None = None,
) -> dict:
    if whisper.url:
        params = {}
        if language:
            params["language"] = language
        if clip_timestamps:
            params["clip_timestamps"] = ",".join(f"{t:g}" for t in clip_timestamps)
        return _post_audio(whisper, "/transcribe", pcm, params)

    import mlx_whisper

    options = {}
    if language:
        options["language"] = language
    if clip_timestamps:
        options["clip_timestamps"] = clip_timestamps
    return mlx_whisper.transcribe(
        _audio(pcm),
        path_or_hf_repo=whisper.model,
        condition_on_previous_text=False,
        **options,
    )


def _transcribe_segments(pcm: bytes, whisper: Whisper) -> tuple[list[dict], str | None]:
    if not whisper.languages:
        result = _transcribe(pcm, whisper)
        return result["segments"], result.get("language")

    clips = _clips_by_language(_window_languages(pcm, whisper))
    segments = [
        segment
        for language, times in clips.items()
        for segment in _transcribe(pcm, whisper, language, times)["segments"]
    ]
    return sorted(segments, key=lambda s: s["start"]), "+".join(clips) or None


def _transcribe_audio(pcm: bytes, whisper: Whisper) -> tuple[str, str | None]:
    segments, language = _transcribe_segments(pcm, whisper)
    return _speech_text(segments), language


def existing_transcript(item: osxphotos.PhotoInfo) -> Transcript | None:
    keyword = next(
        (k for k in item.keywords or () if k.startswith(TRANSCRIPT_TAG_PREFIX)), None
    )
    if keyword is None:
        return None
    if keyword in (NO_AUDIO_TAG, NO_SPEECH_TAG):
        return Transcript(keyword)
    return Transcript(keyword, keyword.removeprefix(TRANSCRIPT_TAG_PREFIX))


def _speech_transcript(
    pcm: bytes | None, whisper: Whisper
) -> tuple[Transcript, str | None]:
    if not pcm:
        return Transcript(NO_AUDIO_TAG), None
    text, language = _transcribe_audio(pcm, whisper)
    if not text:
        return Transcript(NO_SPEECH_TAG), language
    return Transcript(f"{TRANSCRIPT_TAG_PREFIX}{text}", text), language


def transcribe_video(video_path: str, filename: str, whisper: Whisper) -> Transcript:
    t_start = time.monotonic()
    pcm = video_audio(video_path, filename)
    transcript, language = _speech_transcript(pcm, whisper)
    preview = normalize_keyword(transcript.keyword)[:LOG_PREVIEW_CHARS]
    if len(transcript.keyword) > LOG_PREVIEW_CHARS:
        preview += "..."
    logger.info(
        f"Transcribed {filename} "
        f"[{language or '-'}, {time.monotonic() - t_start:.1f}s] {preview}"
    )
    return transcript
