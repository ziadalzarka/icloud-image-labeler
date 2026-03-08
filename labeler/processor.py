import logging
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import osxphotos
from openai import APIConnectionError, APITimeoutError, APIStatusError

from labeler.exporter import export_photo_as_base64, export_video_frames_as_base64
from labeler.llm import create_client, label_photo, label_video
from labeler.writer import write_metadata
from labeler import metrics

logger = logging.getLogger(__name__)

MAX_ITEM_FAILURES = 10
RETRY_BASE_DELAY = 5  # seconds
RETRY_MAX_DELAY = 300  # seconds


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError, ConnectionError, TimeoutError)):
        return True
    if isinstance(exc, APIStatusError):
        if exc.status_code >= 500:
            return True
        # LM Studio model crash returns 400 with "crashed" in the message
        if exc.status_code == 400 and "crashed" in str(exc).lower():
            return True
    return False


def _label_and_write_photo(
    photo: osxphotos.PhotoInfo,
    image_b64: str,
    export_meta: dict,
    export_duration: float,
    base_url: str,
    model: str,
    write: bool,
) -> None:
    """LLM label + write metadata for an already-exported photo. Runs in worker thread."""
    t_start = time.monotonic()

    client = create_client(base_url)

    t_llm = time.monotonic()
    labels, llm_retries = label_photo(client, model, image_b64, photo.original_filename)
    llm_duration = time.monotonic() - t_llm

    t_write = time.monotonic()
    write_metadata(photo.uuid, labels, write=write)
    write_duration = time.monotonic() - t_write

    total_duration = export_duration + (time.monotonic() - t_start)

    metrics.record_item(
        uuid=photo.uuid,
        filename=photo.original_filename,
        media_type="photo",
        is_icloud_only=photo.ismissing,
        status="success",
        export_duration_s=export_duration,
        llm_duration_s=llm_duration,
        write_duration_s=write_duration,
        total_duration_s=total_duration,
        image_size_bytes=export_meta.get("image_size_bytes"),
        image_width=export_meta.get("image_width"),
        image_height=export_meta.get("image_height"),
        llm_retries=llm_retries,
        keywords_count=len(labels.get("keywords", [])),
        has_ocr=bool(labels.get("ocr_text")),
        model=model,
    )


def _process_single_video(
    photo: osxphotos.PhotoInfo,
    base_url: str,
    model: str,
    video_frames: int,
    max_dimension: int,
    write: bool,
) -> None:
    """Process a single video: export frames, label, write metadata, record metrics."""
    t_start = time.monotonic()

    client = create_client(base_url)

    t_export = time.monotonic()
    frames_b64, export_meta = export_video_frames_as_base64(
        photo, num_frames=video_frames, max_dimension=max_dimension
    )
    export_duration = time.monotonic() - t_export

    if not frames_b64:
        raise RuntimeError(f"No frames extracted from {photo.original_filename}")

    t_llm = time.monotonic()
    labels, llm_retries = label_video(client, model, frames_b64, photo.original_filename)
    llm_duration = time.monotonic() - t_llm

    t_write = time.monotonic()
    write_metadata(photo.uuid, labels, write=write)
    write_duration = time.monotonic() - t_write

    total_duration = time.monotonic() - t_start

    metrics.record_item(
        uuid=photo.uuid,
        filename=photo.original_filename,
        media_type="video",
        is_icloud_only=photo.ismissing,
        status="success",
        export_duration_s=export_duration,
        llm_duration_s=llm_duration,
        write_duration_s=write_duration,
        total_duration_s=total_duration,
        image_size_bytes=export_meta.get("image_size_bytes"),
        image_width=export_meta.get("image_width"),
        image_height=export_meta.get("image_height"),
        num_frames=export_meta.get("num_frames"),
        llm_retries=llm_retries,
        keywords_count=len(labels.get("keywords", [])),
        has_ocr=bool(labels.get("ocr_text")),
        model=model,
    )


class ItemFailureTracker:
    """Track per-item failure counts. Raises after MAX_ITEM_FAILURES."""

    def __init__(self):
        self._counts: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def record_failure(self, uuid: str, filename: str):
        with self._lock:
            self._counts[uuid] += 1
            count = self._counts[uuid]
        if count >= MAX_ITEM_FAILURES:
            raise RuntimeError(
                f"Item {filename} ({uuid[:8]}...) failed {count} times. Stopping."
            )
        logger.warning(f"{filename} failed ({count}/{MAX_ITEM_FAILURES})")


def _record_error(photo, media_type, model, error):
    """Record a failed item in metrics."""
    metrics.record_item(
        uuid=photo.uuid,
        filename=photo.original_filename,
        media_type=media_type,
        is_icloud_only=photo.ismissing,
        status="error",
        error_message=str(error),
        model=model,
    )


def _label_photo_with_retry(photo, image_b64, export_meta, export_duration,
                             base_url, model, write, tracker):
    attempt = 0
    while True:
        try:
            _label_and_write_photo(photo, image_b64, export_meta, export_duration,
                                   base_url, model, write)
            return
        except Exception as e:
            if _is_retryable_error(e):
                delay = min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)
                attempt += 1
                logger.warning(f"Retryable error (attempt {attempt}): {e}. Retrying in {delay}s...")
                time.sleep(delay)
                continue
            tracker.record_failure(photo.uuid, photo.original_filename)
            _record_error(photo, "photo", model, e)
            raise


def process_batch(
    items: list[osxphotos.PhotoInfo],
    base_url: str,
    model: str,
    threads: int,
    video_frames: int,
    max_dimension: int = 1024,
    write: bool = True,
    discover_fn=None,
    refresh_interval: int = 600,
):
    """Process a batch of media: photos in parallel, then videos sequentially.

    Photo exports happen on the main thread (osxphotos uses SQLite which is
    bound to the creating thread), then LLM + write run in worker threads.

    If discover_fn is provided, the main thread will call it every
    refresh_interval seconds to pick up newly added items.
    """
    photos = [p for p in items if p.isphoto]
    videos = [p for p in items if not p.isphoto]
    seen_uuids = {p.uuid for p in items}
    tracker = ItemFailureTracker()
    total = len(items)
    processed = 0

    run_id = metrics.start_run(
        model=model, threads=threads, dry_run=not write,
        photos_found=len(photos), videos_found=len(videos),
    )
    photos_ok = 0
    photos_fail = 0
    videos_ok = 0
    videos_fail = 0

    last_refresh = time.monotonic()

    def _maybe_refresh(photo_insert_idx: int = 0, video_insert_idx: int = 0):
        """Check for new items if refresh interval has elapsed.
        New items are inserted at the given indices so they're processed next."""
        nonlocal last_refresh, total
        if discover_fn is None:
            logger.debug("Refresh skipped: no discover_fn")
            return
        now = time.monotonic()
        elapsed = now - last_refresh
        if elapsed < refresh_interval:
            logger.debug(f"Refresh skipped: {elapsed:.0f}s / {refresh_interval}s elapsed")
            return
        last_refresh = now
        logger.info("Refreshing media list...")
        try:
            fresh = discover_fn()
        except Exception as e:
            logger.warning(f"Refresh failed: {e}")
            return
        new_items = [p for p in fresh if p.uuid not in seen_uuids]
        if not new_items:
            logger.info(f"Refresh complete: no new items (query returned {len(fresh)}, all already seen)")
            return
        for p in new_items:
            seen_uuids.add(p.uuid)
        new_photos = [p for p in new_items if p.isphoto]
        new_videos = [p for p in new_items if not p.isphoto]
        # Insert at current position so new items are processed next
        photos[photo_insert_idx:photo_insert_idx] = new_photos
        videos[video_insert_idx:video_insert_idx] = new_videos
        total += len(new_items)
        logger.info(f"Added {len(new_items)} new items ({len(new_photos)} photos, {len(new_videos)} videos), total now {total}")

    # Phase 1: Photos — export on main thread, LLM+write in parallel
    if photos:
        logger.info(f"Processing {len(photos)} photos (up to {threads} threads)...")
        with ThreadPoolExecutor(max_workers=threads) as pool:
            in_flight: dict = {}  # future -> photo
            # Use index loop since photos list may grow via refresh
            i = 0
            while i < len(photos) or in_flight:
                # Collect any completed futures before exporting more
                done = [f for f in in_flight if f.done()]
                for fut in done:
                    photo = in_flight.pop(fut)
                    processed += 1
                    try:
                        fut.result()
                        photos_ok += 1
                        added = (photo.date_added or photo.date).strftime("%Y-%m-%d") if (photo.date_added or photo.date) else "?"
                        logger.info(f"[{processed}/{total}] Done: {photo.original_filename} (added {added})")
                    except RuntimeError as e:
                        if "failed" in str(e) and "times" in str(e):
                            raise
                        photos_fail += 1
                        logger.error(f"[{processed}/{total}] Failed: {photo.original_filename}: {e}")
                    except Exception as e:
                        photos_fail += 1
                        logger.error(f"[{processed}/{total}] Failed: {photo.original_filename}: {e}")

                # If all worker slots are busy, wait for one to finish
                if i < len(photos) and len(in_flight) >= threads:
                    time.sleep(0.1)
                    continue

                # No more photos to export — just drain remaining futures
                if i >= len(photos):
                    time.sleep(0.1)
                    continue

                p = photos[i]
                i += 1

                _maybe_refresh(photo_insert_idx=i, video_insert_idx=0)

                # Export on main thread (osxphotos SQLite is thread-bound)
                try:
                    t_export = time.monotonic()
                    image_b64, export_meta = export_photo_as_base64(p, max_dimension=max_dimension)
                    export_duration = time.monotonic() - t_export
                except Exception as e:
                    processed += 1
                    photos_fail += 1
                    _record_error(p, "photo", model, e)
                    logger.error(f"[{processed}/{total}] Export failed: {p.original_filename}: {e}")
                    tracker.record_failure(p.uuid, p.original_filename)
                    continue

                # Dispatch LLM + write to worker thread
                fut = pool.submit(
                    _label_photo_with_retry, p, image_b64, export_meta, export_duration,
                    base_url, model, write, tracker,
                )
                in_flight[fut] = p

    # Phase 2: Videos sequentially (already on main thread)
    if videos:
        logger.info(f"Processing {len(videos)} videos sequentially...")
        i = 0
        while i < len(videos):
            video = videos[i]
            i += 1
            processed += 1

            _maybe_refresh(photo_insert_idx=len(photos), video_insert_idx=i)

            attempt = 0
            while True:
                try:
                    _process_single_video(video, base_url, model, video_frames, max_dimension, write)
                    videos_ok += 1
                    added = (video.date_added or video.date).strftime("%Y-%m-%d") if (video.date_added or video.date) else "?"
                    logger.info(f"[{processed}/{total}] Done: {video.original_filename} (added {added})")
                    break
                except Exception as e:
                    if _is_retryable_error(e):
                        delay = min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)
                        attempt += 1
                        logger.warning(f"Retryable error (attempt {attempt}): {e}. Retrying in {delay}s...")
                        time.sleep(delay)
                        continue
                    if isinstance(e, RuntimeError) and "failed" in str(e) and "times" in str(e):
                        raise
                    tracker.record_failure(video.uuid, video.original_filename)
                    _record_error(video, "video", model, e)
                    videos_fail += 1
                    logger.error(f"[{processed}/{total}] Failed: {video.original_filename}: {e}")
                    break

    metrics.finish_run(
        run_id=run_id,
        photos_processed=photos_ok,
        videos_processed=videos_ok,
        photos_failed=photos_fail,
        videos_failed=videos_fail,
    )
