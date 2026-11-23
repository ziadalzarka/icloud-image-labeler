"""Metadata writes to macOS Photos: PhotoKit for keywords and title, Photos.app
for the description."""

import logging
import queue
import re
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import objc
import Photos
from applescript import AppleScript, ScriptError
from Foundation import NSSet
from photoscript.script_loader import configure_run_script

from labeler import pause
from labeler.llm import model_tag

logger = logging.getLogger(__name__)

configure_run_script(retry_enabled=False)

_write_lock = threading.Lock()

PHOTOS_APP_STARTUP_WAIT = 3  # seconds to wait for Photos.app to start
PHOTOS_HUNG_AFTER_S = 60
PHOTOS_QUIT_TIMEOUT_S = 15
PHOTOS_RESTART_WAIT_S = 30
PHOTO_ID_SUFFIX = "/L0/001"
PHOTOKIT_BATCH_SIZE = 128

TRANSCRIPT_TAG_PREFIX = "trans:"
NO_AUDIO_TAG = f"{TRANSCRIPT_TAG_PREFIX}no-audio"
NO_SPEECH_TAG = f"{TRANSCRIPT_TAG_PREFIX}no-speech"
OCR_TAG_PREFIX = "ocr:"
LABEL_TAG_PREFIXES = ("m:", "v:", OCR_TAG_PREFIX)

_DIGIT_COMMA_RE = re.compile(r"(?<=\d),(?=\d)")
_COMMA_RE = re.compile(r"\s*(?:,\s*)+")

_PHOTOS_SCRIPT_SOURCE = """
on setLabels(itemId, theKeywords, theTitle, theDescription)
	tell application "Photos"
		set theItem to media item id itemId
		set keywords of theItem to theKeywords
		set name of theItem to theTitle
	end tell
	setDescription(itemId, theDescription)
end setLabels

on setKeywords(itemId, theKeywords)
	tell application "Photos"
		set keywords of media item id itemId to theKeywords
	end tell
end setKeywords

on setDescription(itemId, theDescription)
	tell application "Photos"
		set theItem to media item id itemId
		repeat 3 times
			set description of theItem to theDescription
			if theDescription is "" then return
			if description of theItem is theDescription then return
		end repeat
	end tell
end setDescription

on getKeywords(itemId)
	tell application "Photos"
		set theKeywords to keywords of media item id itemId
	end tell
	if theKeywords is missing value then return {}
	return theKeywords
end getKeywords
"""

_photos_script: AppleScript | None = None

Keep = Callable[[str], bool]


def _ensure_photos_app():
    """Check if Photos.app is running; open it if not."""
    result = subprocess.run(["pgrep", "-x", "Photos"], capture_output=True)
    if result.returncode != 0:
        logger.info("Photos.app not running, opening...")
        subprocess.run(["open", "-a", "Photos"])
        time.sleep(PHOTOS_APP_STARTUP_WAIT)


class PhotosNotRespondingError(RuntimeError):
    def __init__(self):
        super().__init__(
            f"Photos.app didn't answer for {PHOTOS_HUNG_AFTER_S}s, even after a restart"
        )


@contextmanager
def _photos_write():
    pause.wait_until_photos_can_be_used()
    _ensure_photos_app()
    with _write_lock:
        pause.wait_until_photos_can_be_used()
        yield


def _script() -> AppleScript:
    global _photos_script
    if _photos_script is None:
        _photos_script = _compiled_script()
    return _photos_script


def _compiled_script() -> AppleScript:
    with tempfile.TemporaryDirectory(prefix="image-labeler-") as tmpdir:
        source = Path(tmpdir) / "photos.applescript"
        compiled = Path(tmpdir) / "photos.scpt"
        source.write_text(_PHOTOS_SCRIPT_SOURCE)
        try:
            subprocess.run(
                ["osacompile", "-o", str(compiled), str(source)],
                check=True,
                capture_output=True,
                text=True,
                timeout=PHOTOS_HUNG_AFTER_S,
            )
        except subprocess.TimeoutExpired as e:
            raise PhotosNotRespondingError from e
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"osacompile failed: {e.stderr.strip()}") from e
        return AppleScript(path=str(compiled))


def _update_photo(photo_uuid: str, update):
    with _photos_write(), objc.autorelease_pool():
        try:
            _run_update(photo_uuid, update)
        except PhotosNotRespondingError:
            _restart_photos()
            _run_update(photo_uuid, update)


def _run_update(photo_uuid: str, update):
    started = time.monotonic()
    try:
        update(f"{photo_uuid}{PHOTO_ID_SUFFIX}")
    except ScriptError as e:
        if time.monotonic() - started >= PHOTOS_HUNG_AFTER_S:
            raise PhotosNotRespondingError from e
        raise RuntimeError(f"Photos couldn't update {photo_uuid}: {e}") from e


def _restart_photos():
    logger.warning(
        f"Photos.app didn't answer for {PHOTOS_HUNG_AFTER_S}s, restarting it"
    )
    subprocess.run(["killall", "-9", "Photos"], capture_output=True)
    deadline = time.monotonic() + PHOTOS_QUIT_TIMEOUT_S
    while time.monotonic() < deadline and _is_photos_running():
        time.sleep(1)
    subprocess.run(["open", "-a", "Photos"])
    time.sleep(PHOTOS_RESTART_WAIT_S)


def _is_photos_running() -> bool:
    return (
        subprocess.run(["pgrep", "-x", "Photos"], capture_output=True).returncode == 0
    )


def _text(labels: dict, key: str) -> str:
    return (labels.get(key) or "").strip()


def _starts_with(prefixes: tuple[str, ...]) -> Keep:
    return lambda keyword: keyword.startswith(prefixes)


def _keep_none(_keyword: str) -> bool:
    return False


def _photokit_asset(photo_uuid: str):
    status = Photos.PHPhotoLibrary.authorizationStatusForAccessLevel_(
        Photos.PHAccessLevelReadWrite
    )
    if status != Photos.PHAuthorizationStatusAuthorized:
        return None
    return Photos.PHAsset.fetchAssetsWithLocalIdentifiers_options_(
        [f"{photo_uuid}{PHOTO_ID_SUFFIX}"], None
    ).firstObject()


def _photokit_keywords(asset) -> list[str]:
    found = Photos.PHKeyword.fetchKeywordsForAsset_options_(asset, None)
    return [found.objectAtIndex_(i).title() for i in range(found.count())]


@dataclass
class _Change:
    asset: object
    keywords: list[str]
    title: str | None
    saved: threading.Event = field(default_factory=threading.Event)
    error: object = None


class _PhotoKitSaver:
    def __init__(self):
        self._pending: queue.Queue[_Change] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()

    def save(self, asset, keywords: list[str], title: str | None) -> bool:
        change = _Change(asset, keywords, title)
        self._start()
        self._pending.put(change)
        change.saved.wait()
        if change.error is None:
            return True
        logger.warning(
            f"PhotoKit couldn't update {asset.localIdentifier()} "
            f"({change.error}), writing it through Photos.app"
        )
        return False

    def _start(self):
        with self._start_lock:
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="photokit-saver", daemon=True
                )
                self._thread.start()

    def _run(self):
        while True:
            batch = [self._pending.get()]
            while len(batch) < PHOTOKIT_BATCH_SIZE:
                try:
                    batch.append(self._pending.get_nowait())
                except queue.Empty:
                    break
            try:
                with objc.autorelease_pool():
                    self._save_batch(batch)
            except Exception as e:
                for change in batch:
                    change.error = change.error or e
            for change in batch:
                change.saved.set()

    def _save_batch(self, batch: list[_Change]):
        if _perform_changes(batch) or len(batch) == 1:
            return
        for change in batch:
            change.error = None
            _perform_changes([change])


def _perform_changes(batch: list[_Change]) -> bool:
    def change_block():
        for change in batch:
            try:
                request = Photos.PHAssetChangeRequest.changeRequestForAsset_(
                    change.asset
                )
                request.setKeywordTitles_(NSSet.setWithArray_(change.keywords))
                if change.title is not None:
                    request.setTitle_(change.title)
            except Exception as e:
                change.error = e

    library = Photos.PHPhotoLibrary.sharedPhotoLibrary()
    done, error = library.performChangesAndWait_error_(change_block, None)
    if done:
        return True
    for change in batch:
        change.error = change.error or error
    return False


_photokit_saver = _PhotoKitSaver()


def _write_with_photokit(
    photo_uuid: str, keywords: list[str], keep: Keep, labels: dict | None
) -> bool:
    asset = _photokit_asset(photo_uuid)
    if asset is None:
        return False
    try:
        current = _photokit_keywords(asset)
    except Exception as e:
        logger.warning(f"PhotoKit couldn't read keywords of {photo_uuid}: {e}")
        return False
    merged = normalize_keywords([*keywords, *filter(keep, current)])
    if labels is None:
        pause.wait_until_photos_can_be_used()
        return _photokit_saver.save(asset, merged, None)
    description = _text(labels, "description")
    _update_photo(
        photo_uuid,
        lambda item_id: _script().call("setDescription", item_id, description),
    )
    return _photokit_saver.save(asset, merged, _text(labels, "title"))


def _write_with_applescript(
    item_id: str, keywords: list[str], keep: Keep, labels: dict | None
):
    current = _script().call("getKeywords", item_id) or []
    merged = normalize_keywords([*keywords, *filter(keep, current)])
    if labels is None:
        _script().call("setKeywords", item_id, merged)
        return
    _script().call(
        "setLabels",
        item_id,
        merged,
        _text(labels, "title"),
        _text(labels, "description"),
    )


def _write(
    photo_uuid: str, keywords: list[str], keep: Keep, labels: dict | None = None
):
    with objc.autorelease_pool():
        if _write_with_photokit(photo_uuid, keywords, keep, labels):
            return
    _update_photo(
        photo_uuid,
        lambda item_id: _write_with_applescript(item_id, keywords, keep, labels),
    )


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
    """Write keywords, title, and description to Photos."""
    tag = model_tag(model)
    if not write:
        _log_dry_run(labels, [tag, video_tag, transcript_tag])
        return

    keywords = list(labels.get("keywords", []))
    if labels.get("ocr_text"):
        keywords.append(f"{OCR_TAG_PREFIX}{labels['ocr_text']}")
    keywords.append(tag)
    if video_tag:
        keywords.append(video_tag)
    if transcript_tag:
        keywords.append(transcript_tag)
    keywords = normalize_keywords(keywords)
    keep = _keep_none if transcript_tag else _starts_with((TRANSCRIPT_TAG_PREFIX,))

    logger.debug("Writing metadata to Photos...")
    _write(photo_uuid, keywords, keep, labels)
    logger.info(f"Written {len(keywords)} keywords, title, and description")


def write_labels_with_transcript(
    photo_uuid: str, labels: dict, transcript_tag: str, write: bool = True
):
    if not write:
        _log_dry_run({**labels, "ocr_text": ""}, [transcript_tag])
        return

    keywords = normalize_keywords([*labels.get("keywords", []), transcript_tag])
    _write(photo_uuid, keywords, _starts_with(LABEL_TAG_PREFIXES), labels)


def write_transcript(photo_uuid: str, keyword: str, write: bool = True):
    if not write:
        logger.info(f"[DRY RUN] Would write keyword: {normalize_keyword(keyword)}")
        return

    _write(
        photo_uuid,
        normalize_keywords([keyword]),
        lambda k: not k.startswith(TRANSCRIPT_TAG_PREFIX),
    )
