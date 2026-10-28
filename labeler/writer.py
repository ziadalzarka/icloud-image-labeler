"""PhotoScript metadata writes to macOS Photos.app."""

import logging
import re
import subprocess
import threading

import photoscript

from labeler.llm import model_tag

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()

PHOTOS_APP_STARTUP_WAIT = 3  # seconds to wait for Photos.app to start

TRANSCRIPT_TAG_PREFIX = "trans:"
NO_AUDIO_TAG = f"{TRANSCRIPT_TAG_PREFIX}no-audio"
NO_SPEECH_TAG = f"{TRANSCRIPT_TAG_PREFIX}no-speech"
OCR_TAG_PREFIX = "ocr:"
LABEL_TAG_PREFIXES = ("m:", "v:", OCR_TAG_PREFIX)

_DIGIT_COMMA_RE = re.compile(r"(?<=\d),(?=\d)")
_COMMA_RE = re.compile(r"\s*(?:,\s*)+")


def _ensure_photos_app():
    """Check if Photos.app is running; open it if not."""
    result = subprocess.run(["pgrep", "-x", "Photos"], capture_output=True)
    if result.returncode != 0:
        logger.info("Photos.app not running, opening...")
        subprocess.run(["open", "-a", "Photos"])
        import time

        time.sleep(PHOTOS_APP_STARTUP_WAIT)


def _transcript_keywords(keywords: list[str]) -> list[str]:
    return [k for k in keywords if k.startswith(TRANSCRIPT_TAG_PREFIX)]


def normalize_keyword(keyword: str) -> str:
    keyword = _DIGIT_COMMA_RE.sub("", keyword.lower())
    return _COMMA_RE.sub(" ", keyword).strip()


def normalize_keywords(keywords: list[str]) -> list[str]:
    normalized = (normalize_keyword(k) for k in keywords)
    return list(dict.fromkeys(k for k in normalized if k))


def _log_dry_run(labels: dict, tags: list[str | None]):
    logger.info("[DRY RUN] Would write:")
    logger.info(f"  Title: {labels.get('title', '')}")
    logger.info(f"  Description: {labels.get('description', '')}")
    keywords = normalize_keywords(labels.get("keywords", []))
    logger.info(f"  Keywords: {', '.join(keywords)}")
    if labels.get("ocr_text"):
        logger.info(f"  OCR Text: {normalize_keyword(labels['ocr_text'])}")
    for tag in tags:
        if tag:
            logger.info(f"  Tag: {normalize_keyword(tag)}")


def write_metadata(
    photo_uuid: str,
    labels: dict,
    model: str,
    write: bool = True,
    video_tag: str | None = None,
    transcript_tag: str | None = None,
):
    """Write keywords, title, and description to Photos.app."""
    tag = model_tag(model)
    if not write:
        _log_dry_run(labels, [tag, video_tag, transcript_tag])
        return

    _ensure_photos_app()

    keywords = list(labels.get("keywords", []))
    if labels.get("ocr_text"):
        keywords.append(f"{OCR_TAG_PREFIX}{labels['ocr_text']}")
    keywords.append(tag)
    if video_tag:
        keywords.append(video_tag)

    with _write_lock:
        logger.debug("Writing metadata to Photos.app...")
        photo = photoscript.Photo(photo_uuid)
        transcript = (
            [transcript_tag] if transcript_tag else _transcript_keywords(photo.keywords)
        )
        photo.keywords = normalize_keywords(keywords + transcript)
        photo.title = labels.get("title", "")
        photo.description = labels.get("description", "")
        logger.info(f"Written {len(keywords)} keywords, title, and description")


def write_labels_with_transcript(
    photo_uuid: str, labels: dict, transcript_tag: str, write: bool = True
):
    if not write:
        _log_dry_run({**labels, "ocr_text": ""}, [transcript_tag])
        return

    _ensure_photos_app()

    with _write_lock:
        photo = photoscript.Photo(photo_uuid)
        tags = [k for k in photo.keywords if k.startswith(LABEL_TAG_PREFIXES)]
        photo.keywords = normalize_keywords(
            [*labels.get("keywords", []), *tags, transcript_tag]
        )
        photo.title = labels.get("title", "")
        photo.description = labels.get("description", "")


def write_transcript(photo_uuid: str, keyword: str, write: bool = True):
    if not write:
        logger.info(f"[DRY RUN] Would write keyword: {normalize_keyword(keyword)}")
        return

    _ensure_photos_app()

    with _write_lock:
        photo = photoscript.Photo(photo_uuid)
        other = [k for k in photo.keywords if not k.startswith(TRANSCRIPT_TAG_PREFIX)]
        photo.keywords = normalize_keywords([*other, keyword])
