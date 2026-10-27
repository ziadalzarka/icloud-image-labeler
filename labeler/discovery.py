"""Query macOS Photos library for unprocessed media via osxphotos."""

import logging
from datetime import datetime, timedelta

import osxphotos

from . import metrics

logger = logging.getLogger(__name__)

_MODEL_TAG_PREFIX = "m:"


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


def _is_outdated_video(p: osxphotos.PhotoInfo, expected_video_tag: str) -> bool:
    keywords = p.keywords or ()
    return (
        not p.isphoto
        and expected_video_tag not in keywords
        and any(k.startswith(_MODEL_TAG_PREFIX) for k in keywords)
    )


def _outdated_videos(
    recent: list[osxphotos.PhotoInfo],
    skip_uuids: set[str],
    expected_video_tag: str | None,
    limit: int,
) -> list[osxphotos.PhotoInfo]:
    if expected_video_tag is None:
        return []
    outdated = sorted(
        (
            p
            for p in recent
            if not p.hidden
            and p.uuid not in skip_uuids
            and _is_outdated_video(p, expected_video_tag)
        ),
        key=lambda p: p.date_added or p.date,
        reverse=True,
    )
    taken = outdated[:limit] if limit > 0 else outdated
    if outdated:
        logger.info(
            f"Found {len(outdated)} videos labeled with other frame settings; "
            f"relabeling {len(taken)} this cycle"
        )
    return taken


def get_unprocessed_media(
    limit: int = 0,
    days_back: int = 0,
    to_days: int = 0,
    photo: bool = True,
    video: bool = True,
    reindex: bool = False,
    expected_model_tags: set[str] | None = None,
    expected_video_tag: str | None = None,
    outdated_video_limit: int = 0,
) -> list[osxphotos.PhotoInfo]:
    """Query Photos library for unprocessed media.

    Args:
        limit: Max items to return. 0 = no limit (all unprocessed).
        days_back: Look back N days from now. 0 = no date filter (all photos).
        to_days: Skip the most recent N days (e.g. 7 = exclude last 7 days).
        reindex: If True, include items whose model tag matches none of
            ``expected_model_tags`` (stale or never processed), and videos
            missing ``expected_video_tag``.
        expected_model_tags: Set of valid model tags (``m:<hash>``). An item
            is considered up-to-date if any of its keywords appears here.
    """
    if reindex and not expected_model_tags:
        raise ValueError("reindex=True requires expected_model_tags")
    logger.info("Loading Photos library...")
    photosdb = osxphotos.PhotosDB()

    from_date = datetime.now() - timedelta(days=days_back) if days_back > 0 else None
    to_date = datetime.now() - timedelta(days=to_days) if to_days > 0 else None
    if from_date:
        date_range = f"since {from_date.strftime('%Y-%m-%d')}"
        if to_date:
            date_range += f" until {to_date.strftime('%Y-%m-%d')}"
    elif to_date:
        date_range = f"until {to_date.strftime('%Y-%m-%d')}"
    else:
        date_range = "all time"
    logger.debug(f"Querying media ({date_range})...")
    recent = photosdb.photos(from_date=from_date, to_date=to_date)
    logger.debug(f"Found {len(recent)} items in date range")

    skip_uuids = metrics.get_permanent_failure_uuids()
    if skip_uuids:
        logger.debug(f"Skipping {len(skip_uuids)} item(s) with permanent failures")

    if reindex:
        tags = expected_model_tags or set()
        # Include items whose model tag is missing or not in the pool's tag set.
        items = [
            p
            for p in recent
            if not p.hidden
            and p.uuid not in skip_uuids
            and _needs_reindex(p, tags, expected_video_tag)
        ]
    else:
        # Filter: no keywords, not hidden, not a known-permanent failure
        items = [
            p
            for p in recent
            if not p.keywords and not p.hidden and p.uuid not in skip_uuids
        ]
        items += _outdated_videos(
            recent,
            skip_uuids,
            expected_video_tag if video else None,
            outdated_video_limit,
        )

    # Filter by media type
    if photo and not video:
        items = [p for p in items if p.isphoto]
    elif video and not photo:
        items = [p for p in items if not p.isphoto]
    elif not photo and not video:
        return []

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
