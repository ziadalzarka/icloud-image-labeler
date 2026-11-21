"""Query macOS Photos library for unprocessed media via osxphotos."""

import logging
import threading
from datetime import datetime, timedelta

import osxphotos

from . import metrics
from .writer import TRANSCRIPT_TAG_PREFIX

logger = logging.getLogger(__name__)

_MODEL_TAG_PREFIX = "m:"

_photosdb_lock = threading.Lock()


def load_photos_db() -> osxphotos.PhotosDB:
    logger.info("Loading Photos library...")
    with _photosdb_lock:
        return osxphotos.PhotosDB()


def _has_model_tag(p: osxphotos.PhotoInfo) -> bool:
    return any(k.startswith(_MODEL_TAG_PREFIX) for k in p.keywords or ())


def _has_transcript(p: osxphotos.PhotoInfo) -> bool:
    return any(k.startswith(TRANSCRIPT_TAG_PREFIX) for k in p.keywords or ())


def is_unlabeled(p: osxphotos.PhotoInfo) -> bool:
    return all(k.startswith(TRANSCRIPT_TAG_PREFIX) for k in p.keywords or ())


def _date_range(
    days_back: int, to_days: int
) -> tuple[datetime | None, datetime | None, str]:
    from_date = datetime.now() - timedelta(days=days_back) if days_back > 0 else None
    to_date = datetime.now() - timedelta(days=to_days) if to_days > 0 else None
    if from_date:
        description = f"since {from_date.strftime('%Y-%m-%d')}"
        if to_date:
            description += f" until {to_date.strftime('%Y-%m-%d')}"
    elif to_date:
        description = f"until {to_date.strftime('%Y-%m-%d')}"
    else:
        description = "all time"
    return from_date, to_date, description


def _needs_reindex(
    p: osxphotos.PhotoInfo, model_tags: set[str], expected_video_tag: str | None
) -> bool:
    keywords = set(p.keywords or ())
    if not keywords & model_tags:
        return True
    return (
        not p.isphoto
        and expected_video_tag is not None
        and expected_video_tag not in keywords
    )


def _is_outdated(
    p: osxphotos.PhotoInfo, model_tags: set[str], expected_video_tag: str | None
) -> bool:
    return _has_model_tag(p) and _needs_reindex(p, model_tags, expected_video_tag)


def _newest(items: list[osxphotos.PhotoInfo], limit: int) -> list[osxphotos.PhotoInfo]:
    return items[:limit] if limit > 0 else items


def _outdated_items(
    recent: list[osxphotos.PhotoInfo],
    skip_uuids: set[str],
    model_tags: set[str],
    expected_video_tag: str | None,
    photo_limit: int,
    video_limit: int,
) -> list[osxphotos.PhotoInfo]:
    outdated = sorted(
        (
            p
            for p in recent
            if not p.hidden
            and p.uuid not in skip_uuids
            and _is_outdated(p, model_tags, expected_video_tag)
        ),
        key=lambda p: p.date_added or p.date,
        reverse=True,
    )
    photos = [p for p in outdated if p.isphoto]
    videos = [p for p in outdated if not p.isphoto]
    taken_photos = _newest(photos, photo_limit)
    taken_videos = _newest(videos, video_limit)
    if outdated:
        logger.info(
            f"Found {len(photos)} photos and {len(videos)} videos labeled with "
            "another model or other frame settings; relabeling "
            f"{len(taken_photos)} photos and {len(taken_videos)} videos this cycle"
        )
    return taken_photos + taken_videos


def get_unprocessed_media(
    photosdb: osxphotos.PhotosDB,
    limit: int = 0,
    days_back: int = 0,
    to_days: int = 0,
    photo: bool = True,
    video: bool = True,
    reindex: bool = False,
    expected_model_tags: set[str] | None = None,
    expected_video_tag: str | None = None,
    outdated_photo_limit: int = 0,
    outdated_video_limit: int = 0,
) -> list[osxphotos.PhotoInfo]:
    """Query Photos library for unprocessed media.

    Args:
        limit: Max items to return. 0 = no limit (all unprocessed).
        days_back: Look back N days from now. 0 = no date filter (all photos).
        to_days: Skip the most recent N days (e.g. 7 = exclude last 7 days).
        reindex: If True, include items whose model tag matches none of
            ``expected_model_tags`` (stale or never processed), and videos
            missing ``expected_video_tag``. Otherwise only items labeled by
            another model or with other frame settings are relabeled, up to
            ``outdated_photo_limit`` photos and ``outdated_video_limit`` videos.
        expected_model_tags: Set of valid model tags (``m:<hash>``). An item
            is considered up-to-date if any of its keywords appears here.
    """
    if not expected_model_tags:
        raise ValueError("get_unprocessed_media requires expected_model_tags")
    if not photo and not video:
        return []

    from_date, to_date, date_range = _date_range(days_back, to_days)
    logger.debug(f"Querying media ({date_range})...")
    recent = photosdb.photos(
        images=photo, movies=video, from_date=from_date, to_date=to_date
    )
    logger.debug(f"Found {len(recent)} items in date range")

    skip_uuids = metrics.get_permanent_failure_uuids()
    if skip_uuids:
        logger.debug(f"Skipping {len(skip_uuids)} item(s) with permanent failures")

    if reindex:
        items = [
            p
            for p in recent
            if not p.hidden
            and p.uuid not in skip_uuids
            and _needs_reindex(p, expected_model_tags, expected_video_tag)
        ]
    else:
        items = [
            p
            for p in recent
            if is_unlabeled(p) and not p.hidden and p.uuid not in skip_uuids
        ]
        items += _outdated_items(
            recent,
            skip_uuids,
            expected_model_tags,
            expected_video_tag,
            outdated_photo_limit,
            outdated_video_limit,
        )

    photo_count = sum(1 for p in items if p.isphoto)
    video_count = sum(1 for p in items if not p.isphoto)
    missing_count = sum(1 for p in items if p.ismissing)
    label = "reindex candidates" if reindex else "unprocessed items"
    logger.info(
        f"Found {len(items)} {label} "
        f"({photo_count} photos, {video_count} videos, {missing_count} iCloud-only)"
    )

    # Sort by date added (most recent first)
    items.sort(key=lambda p: p.date_added or p.date, reverse=True)

    selected = items[:limit] if limit > 0 else items
    if selected:
        logger.info(
            f"Selected {len(selected)} item(s), newest: {selected[0].original_filename}"
        )
    return selected


def get_untranscribed_videos(
    photosdb: osxphotos.PhotosDB,
    days_back: int = 0,
    to_days: int = 0,
    exclude_uuids: set[str] | None = None,
    limit: int = 0,
) -> list[osxphotos.PhotoInfo]:
    from_date, to_date, date_range = _date_range(days_back, to_days)
    logger.debug(f"Querying labeled videos without a transcript ({date_range})...")
    videos = photosdb.photos(
        images=False, movies=True, from_date=from_date, to_date=to_date
    )
    skip_uuids = metrics.get_permanent_failure_uuids() | (exclude_uuids or set())
    items = sorted(
        (
            p
            for p in videos
            if not p.hidden
            and p.uuid not in skip_uuids
            and _has_model_tag(p)
            and not _has_transcript(p)
        ),
        key=lambda p: p.date_added or p.date,
        reverse=True,
    )
    taken = items[:limit] if limit > 0 else items
    if items:
        logger.info(
            f"Found {len(items)} labeled videos without a transcript; "
            f"transcribing {len(taken)} this cycle"
        )
    return taken
