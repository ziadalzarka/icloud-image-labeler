import logging
import subprocess
import threading

import photoscript

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()


def _ensure_photos_app():
    """Check if Photos.app is running; open it if not."""
    result = subprocess.run(
        ["pgrep", "-x", "Photos"], capture_output=True
    )
    if result.returncode != 0:
        logger.info("Photos.app not running, opening...")
        subprocess.run(["open", "-a", "Photos"])
        import time
        time.sleep(3)


def write_metadata(photo_uuid: str, labels: dict, write: bool = True):
    """Write keywords, title, and description to Photos.app."""
    if not write:
        logger.info(f"[DRY RUN] Would write:")
        logger.info(f"  Title: {labels.get('title', '')}")
        logger.info(f"  Description: {labels.get('description', '')}")
        logger.info(f"  Keywords: {', '.join(labels.get('keywords', []))}")
        if labels.get("ocr_text"):
            logger.info(f"  OCR Text: {labels['ocr_text']}")
        return

    _ensure_photos_app()

    keywords = list(labels.get("keywords", []))
    if labels.get("ocr_text"):
        keywords.append(f"ocr:{labels['ocr_text']}")

    with _write_lock:
        logger.debug(f"Writing metadata to Photos.app...")
        photo = photoscript.Photo(photo_uuid)
        photo.keywords = keywords
        photo.title = labels.get("title", "")
        photo.description = labels.get("description", "")
        logger.info(f"Written {len(keywords)} keywords, title, and description")
