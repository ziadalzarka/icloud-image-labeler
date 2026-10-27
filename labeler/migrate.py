import json
import logging
import time
from datetime import datetime

import osxphotos
import photoscript

from labeler.config import CONFIG_DIR
from labeler.shutdown import is_shutting_down
from labeler.writer import normalize_keywords

logger = logging.getLogger(__name__)

BACKUP_DIR = CONFIG_DIR / "backups"
PROGRESS_EVERY = 500


def _needs_normalizing(keywords: list[str]) -> bool:
    return normalize_keywords(keywords) != keywords


def _normalize_item(uuid: str, backup) -> bool:
    photo = photoscript.Photo(uuid)
    keywords = photo.keywords
    normalized = normalize_keywords(keywords)
    if normalized == keywords:
        return False
    backup.write(json.dumps({"uuid": uuid, "keywords": keywords}, ensure_ascii=False))
    backup.write("\n")
    backup.flush()
    photo.keywords = normalized
    return True


def normalize_library_keywords(write: bool = True, limit: int = 0):
    logger.info("Loading Photos library...")
    photosdb = osxphotos.PhotosDB()
    items = [p for p in photosdb.photos() if _needs_normalizing(p.keywords or [])]
    logger.info(f"Found {len(items)} items with keywords to normalize")
    if limit > 0:
        items = items[:limit]
    if not write:
        for item in items[:10]:
            normalized = normalize_keywords(item.keywords)
            logger.info(f"[DRY RUN] {item.original_filename}: {normalized}")
        return
    if not items:
        return

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / f"keywords-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    logger.info(f"Saving original keywords to {backup_path}")

    changed = failed = 0
    t_start = time.monotonic()
    with backup_path.open("a") as backup:
        for position, item in enumerate(items, start=1):
            if is_shutting_down():
                break
            try:
                if _normalize_item(item.uuid, backup):
                    changed += 1
            except Exception as e:
                failed += 1
                logger.error(f"Failed: {item.original_filename} ({item.uuid}): {e}")
            if position % PROGRESS_EVERY == 0 or position == len(items):
                elapsed = time.monotonic() - t_start
                remaining = elapsed / position * (len(items) - position)
                logger.info(
                    f"[{position}/{len(items)}] {changed} normalized, "
                    f"{failed} failed, about {remaining / 60:.0f} min left"
                )
    logger.info(f"Done: {changed} items normalized, {failed} failed")
