import json
import logging
import time
from collections.abc import Callable
from datetime import datetime

import osxphotos
import photoscript

from labeler.config import CONFIG_DIR
from labeler.shutdown import is_shutting_down
from labeler.writer import NO_AUDIO_TAG, TRANSCRIPT_TAG_PREFIX, normalize_keywords

logger = logging.getLogger(__name__)

BACKUP_DIR = CONFIG_DIR / "backups"
PROGRESS_EVERY = 500

KeywordChange = Callable[[list[str]], list[str]]


def _without_transcripts(keywords: list[str]) -> list[str]:
    return [
        k
        for k in keywords
        if not k.startswith(TRANSCRIPT_TAG_PREFIX) or k == NO_AUDIO_TAG
    ]


def _change_item(uuid: str, change: KeywordChange, backup) -> bool:
    photo = photoscript.Photo(uuid)
    keywords = photo.keywords
    changed = change(keywords)
    if changed == keywords:
        return False
    backup.write(json.dumps({"uuid": uuid, "keywords": keywords}, ensure_ascii=False))
    backup.write("\n")
    backup.flush()
    photo.keywords = changed
    return True


def _change_library_keywords(
    change: KeywordChange,
    backup_name: str,
    write: bool,
    limit: int,
    videos_only: bool = False,
):
    logger.info("Loading Photos library...")
    photosdb = osxphotos.PhotosDB()
    media = photosdb.photos(images=not videos_only, movies=True)
    items = [p for p in media if change(p.keywords or []) != (p.keywords or [])]
    logger.info(f"Found {len(items)} items with keywords to change")
    if limit > 0:
        items = items[:limit]
    if not write:
        for item in items[:10]:
            logger.info(f"[DRY RUN] {item.original_filename}: {change(item.keywords)}")
        return
    if not items:
        return

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / f"{backup_name}-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    logger.info(f"Saving original keywords to {backup_path}")

    changed = failed = 0
    t_start = time.monotonic()
    with backup_path.open("a") as backup:
        for position, item in enumerate(items, start=1):
            if is_shutting_down():
                break
            try:
                if _change_item(item.uuid, change, backup):
                    changed += 1
            except Exception as e:
                failed += 1
                logger.error(f"Failed: {item.original_filename} ({item.uuid}): {e}")
            if position % PROGRESS_EVERY == 0 or position == len(items):
                elapsed = time.monotonic() - t_start
                remaining = elapsed / position * (len(items) - position)
                logger.info(
                    f"[{position}/{len(items)}] {changed} changed, "
                    f"{failed} failed, about {remaining / 60:.0f} min left"
                )
    logger.info(f"Done: {changed} items changed, {failed} failed")


def normalize_library_keywords(write: bool = True, limit: int = 0):
    _change_library_keywords(normalize_keywords, "keywords", write, limit)


def remove_transcripts(write: bool = True, limit: int = 0):
    _change_library_keywords(
        _without_transcripts, "transcripts", write, limit, videos_only=True
    )
