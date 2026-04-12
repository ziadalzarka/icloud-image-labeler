"""Query macOS Photos library for unprocessed media via osxphotos."""

import logging
from datetime import datetime, timedelta

import osxphotos

logger = logging.getLogger(__name__)

_MODEL_TAG_PREFIX = "m:"


def get_unprocessed_media(
    limit: int = 0,
    days_back: int = 0,
    to_days: int = 0,
    photo: bool = True,
    video: bool = True,
    reindex: bool = False,
    expected_model_tag: str | None = None,
) -> list[osxphotos.PhotoInfo]:
    """Query Photos library for unprocessed media.

    Args:
        limit: Max items to return. 0 = no limit (all unprocessed).
        days_back: Look back N days from now. 0 = no date filter (all photos).
        to_days: Skip the most recent N days (e.g. 7 = exclude last 7 days).
        reindex: If True, include items whose model tag is missing or differs
            from ``expected_model_tag``. Requires ``expected_model_tag``.
        expected_model_tag: Current model tag (``m:<hash>``) used when
            ``reindex`` is True.
    """
    if reindex and not expected_model_tag:
        raise ValueError("reindex=True requires expected_model_tag")
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

    if reindex:
        # Include items missing the expected model tag (stale or never processed).
        def _needs_reindex(p: osxphotos.PhotoInfo) -> bool:
            if p.hidden:
                return False
            if expected_model_tag in (p.keywords or ()):
                return False
            return True

        items = [p for p in recent if _needs_reindex(p)]
    else:
        # Filter: no keywords, not hidden
        items = [p for p in recent if not p.keywords and not p.hidden]

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
