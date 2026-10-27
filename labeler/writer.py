"""PhotoScript metadata writes to macOS Photos.app."""

import logging
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


def lowercase_keywords(keywords: list[str]) -> list[str]:
    return list(dict.fromkeys(k.lower() for k in keywords))


def write_metadata(
    photo_uuid: str,
    labels: dict,
    model: str,
    write: bool = True,
    video_tag: str | None = None,
):
    """Write keywords, title, and description to Photos.app."""
    tag = model_tag(model)
    if not write:
        logger.info("[DRY RUN] Would write:")
        logger.info(f"  Title: {labels.get('title', '')}")
        logger.info(f"  Description: {labels.get('description', '')}")
        keywords = lowercase_keywords(labels.get("keywords", []))
        logger.info(f"  Keywords: {', '.join(keywords)}")
        if labels.get("ocr_text"):
            logger.info(f"  OCR Text: {labels['ocr_text'].lower()}")
        logger.info(f"  Model tag: {tag}")
        if video_tag:
            logger.info(f"  Video tag: {video_tag}")
        return

    _ensure_photos_app()

    keywords = list(labels.get("keywords", []))
    if labels.get("ocr_text"):
        keywords.append(f"ocr:{labels['ocr_text']}")
    keywords.append(tag)
    if video_tag:
        keywords.append(video_tag)

    with _write_lock:
        logger.debug("Writing metadata to Photos.app...")
        photo = photoscript.Photo(photo_uuid)
        photo.keywords = lowercase_keywords(
            keywords + _transcript_keywords(photo.keywords)
        )
        photo.title = labels.get("title", "")
        photo.description = labels.get("description", "")
        logger.info(f"Written {len(keywords)} keywords, title, and description")


def write_transcript(photo_uuid: str, keyword: str, write: bool = True):
    if not write:
        logger.info(f"[DRY RUN] Would write keyword: {keyword.lower()}")
        return

    _ensure_photos_app()

    with _write_lock:
        photo = photoscript.Photo(photo_uuid)
        other = [k for k in photo.keywords if not k.startswith(TRANSCRIPT_TAG_PREFIX)]
        photo.keywords = lowercase_keywords([*other, keyword])
