import json
import logging
import time
from collections import Counter

from labeler.config import CONFIG_DIR
from labeler.llm import model_tag

logger = logging.getLogger(__name__)

SNAPSHOT_PATH = CONFIG_DIR / "library.json"
MODEL_NAMES_PATH = CONFIG_DIR / "model-tags.json"
MODEL_TAG_PREFIX = "m:"


def _model_tag_of(keywords: set[str], current_tags: set[str]) -> str | None:
    tags = {k for k in keywords if k.startswith(MODEL_TAG_PREFIX)}
    if not tags:
        return None
    return next(iter(tags & current_tags), None) or min(tags)


def _count(items, current_tags: set[str], video_tag: str | None) -> dict:
    models: Counter = Counter()
    unlabeled = 0
    settings_outdated = 0
    total = 0
    for p in items:
        if p.hidden:
            continue
        total += 1
        keywords = set(p.keywords or ())
        tag = _model_tag_of(keywords, current_tags)
        if tag is None:
            unlabeled += 1
            continue
        models[tag] += 1
        if tag in current_tags and video_tag and not p.isphoto:
            settings_outdated += video_tag not in keywords
    return {
        "total": total,
        "unlabeled": unlabeled,
        "settings_outdated": settings_outdated,
        "models": dict(models),
    }


def summarize(photosdb, current_tags: set[str], video_tag: str | None) -> dict:
    photos = photosdb.photos(images=True, movies=False)
    videos = photosdb.photos(images=False, movies=True)
    return {
        "updated_at": time.time(),
        "current_tags": sorted(current_tags),
        "photos": _count(photos, current_tags, None),
        "videos": _count(videos, current_tags, video_tag),
    }


def save(snapshot: dict) -> None:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    written = SNAPSHOT_PATH.with_name(f"{SNAPSHOT_PATH.name}.new")
    written.write_text(json.dumps(snapshot))
    written.replace(SNAPSHOT_PATH)


def save_summary(photosdb, current_tags: set[str], video_tag: str | None) -> None:
    try:
        save(summarize(photosdb, current_tags, video_tag))
    except Exception as e:
        logger.warning(f"Couldn't save the library summary: {e}")


def known_model_names() -> dict[str, str]:
    try:
        return json.loads(MODEL_NAMES_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def remember_models(names) -> dict[str, str]:
    known = known_model_names()
    found = {model_tag(name): name for name in names if name}
    merged = {**known, **found}
    if merged != known:
        MODEL_NAMES_PATH.parent.mkdir(parents=True, exist_ok=True)
        written = MODEL_NAMES_PATH.with_name(f"{MODEL_NAMES_PATH.name}.new")
        written.write_text(json.dumps(merged, indent=2, sort_keys=True))
        written.replace(MODEL_NAMES_PATH)
    return merged


def load() -> dict | None:
    try:
        return json.loads(SNAPSHOT_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return None
