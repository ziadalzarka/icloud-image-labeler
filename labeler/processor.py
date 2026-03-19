import logging
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import osxphotos
from openai import APIConnectionError, APIStatusError, APITimeoutError

from labeler import metrics
from labeler.exporter import export_photo_as_base64, export_video_frames_as_base64
from labeler.llm import create_client, label_photo, label_video
from labeler.shutdown import is_shutting_down
from labeler.shutdown import wait as shutdown_wait
from labeler.writer import write_metadata

logger = logging.getLogger(__name__)

MAX_ITEM_FAILURES = 10
RETRY_BASE_DELAY = 5  # seconds
RETRY_MAX_DELAY = 300  # seconds


class MaxFailuresExceeded(RuntimeError):
    """Raised when a single item exceeds MAX_ITEM_FAILURES."""


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(
        exc, (APIConnectionError, APITimeoutError, ConnectionError, TimeoutError)
    ):
        return True
    if isinstance(exc, APIStatusError):
        if exc.status_code >= 500:
            return True
        # LM Studio model crash returns 400 with "crashed" in the message
        if exc.status_code == 400 and "crashed" in str(exc).lower():
            return True
    return False


def _retry_delay(attempt: int) -> float:
    return min(RETRY_BASE_DELAY * (2**attempt), RETRY_MAX_DELAY)


def _format_date(item: osxphotos.PhotoInfo) -> str:
    dt = item.date_added or item.date
    return dt.strftime("%Y-%m-%d") if dt else "?"


def _record_error(
    item: osxphotos.PhotoInfo, media_type: str, model: str, error: Exception
):
    """Record a failed item in metrics."""
    metrics.record_item(
        uuid=item.uuid,
        filename=item.original_filename,
        media_type=media_type,
        is_icloud_only=item.ismissing,
        status="error",
        error_message=str(error),
        model=model,
    )


class ItemFailureTracker:
    """Track per-item failure counts. Raises MaxFailuresExceeded after limit."""

    def __init__(self):
        self._counts: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def record_failure(self, uuid: str, filename: str):
        with self._lock:
            self._counts[uuid] += 1
            count = self._counts[uuid]
        if count >= MAX_ITEM_FAILURES:
            raise MaxFailuresExceeded(
                f"Item {filename} ({uuid[:8]}...) failed {count} times. Stopping."
            )
        logger.warning(f"{filename} failed ({count}/{MAX_ITEM_FAILURES})")


# --- Photo processing (export on main thread, LLM+write in worker) --------


def _label_and_write_photo(
    item: osxphotos.PhotoInfo,
    image_b64: str,
    export_meta: dict,
    export_duration: float,
    base_url: str,
    model: str,
    write: bool,
    api_key: str = "",
) -> None:
    """LLM label + write metadata for an already-exported photo."""
    t_start = time.monotonic()
    client = create_client(base_url, api_key=api_key)

    t_llm = time.monotonic()
    labels, llm_retries = label_photo(client, model, image_b64, item.original_filename)
    llm_duration = time.monotonic() - t_llm

    t_write = time.monotonic()
    write_metadata(item.uuid, labels, write=write)
    write_duration = time.monotonic() - t_write

    metrics.record_item(
        uuid=item.uuid,
        filename=item.original_filename,
        media_type="photo",
        is_icloud_only=item.ismissing,
        status="success",
        export_duration_s=export_duration,
        llm_duration_s=llm_duration,
        write_duration_s=write_duration,
        total_duration_s=export_duration + (time.monotonic() - t_start),
        image_size_bytes=export_meta.get("image_size_bytes"),
        image_width=export_meta.get("image_width"),
        image_height=export_meta.get("image_height"),
        llm_retries=llm_retries,
        keywords_count=len(labels.get("keywords", [])),
        has_ocr=bool(labels.get("ocr_text")),
        model=model,
    )


def _label_photo_with_retry(
    item,
    image_b64,
    export_meta,
    export_duration,
    base_url,
    model,
    write,
    tracker,
    api_key="",
):
    attempt = 0
    while True:
        try:
            _label_and_write_photo(
                item,
                image_b64,
                export_meta,
                export_duration,
                base_url,
                model,
                write,
                api_key=api_key,
            )
            return
        except Exception as e:
            if _is_retryable_error(e):
                delay = _retry_delay(attempt)
                attempt += 1
                logger.warning(
                    f"Retryable error (attempt {attempt}): {e}. Retrying in {delay}s..."
                )
                if shutdown_wait(delay):
                    raise
                continue
            tracker.record_failure(item.uuid, item.original_filename)
            _record_error(item, "photo", model, e)
            raise


# --- Video processing (fully on main thread) ------------------------------


def _process_single_video(
    item: osxphotos.PhotoInfo,
    base_url: str,
    model: str,
    video_frames: int,
    max_dimension: int,
    write: bool,
    api_key: str = "",
) -> None:
    """Export frames, label, write metadata, record metrics for one video."""
    t_start = time.monotonic()
    client = create_client(base_url, api_key=api_key)

    t_export = time.monotonic()
    frames_b64, export_meta = export_video_frames_as_base64(
        item, num_frames=video_frames, max_dimension=max_dimension
    )
    export_duration = time.monotonic() - t_export

    if not frames_b64:
        raise RuntimeError(f"No frames extracted from {item.original_filename}")

    t_llm = time.monotonic()
    labels, llm_retries = label_video(client, model, frames_b64, item.original_filename)
    llm_duration = time.monotonic() - t_llm

    t_write = time.monotonic()
    write_metadata(item.uuid, labels, write=write)
    write_duration = time.monotonic() - t_write

    metrics.record_item(
        uuid=item.uuid,
        filename=item.original_filename,
        media_type="video",
        is_icloud_only=item.ismissing,
        status="success",
        export_duration_s=export_duration,
        llm_duration_s=llm_duration,
        write_duration_s=write_duration,
        total_duration_s=time.monotonic() - t_start,
        image_size_bytes=export_meta.get("image_size_bytes"),
        image_width=export_meta.get("image_width"),
        image_height=export_meta.get("image_height"),
        num_frames=export_meta.get("num_frames"),
        llm_retries=llm_retries,
        keywords_count=len(labels.get("keywords", [])),
        has_ocr=bool(labels.get("ocr_text")),
        model=model,
    )


def _process_video_with_retry(
    item, base_url, model, video_frames, max_dimension, write, tracker, api_key=""
):
    attempt = 0
    while True:
        try:
            _process_single_video(
                item,
                base_url,
                model,
                video_frames,
                max_dimension,
                write,
                api_key=api_key,
            )
            return
        except Exception as e:
            if _is_retryable_error(e):
                delay = _retry_delay(attempt)
                attempt += 1
                logger.warning(
                    f"Retryable error (attempt {attempt}): {e}. Retrying in {delay}s..."
                )
                if shutdown_wait(delay):
                    raise
                continue
            tracker.record_failure(item.uuid, item.original_filename)
            _record_error(item, "video", model, e)
            raise


# --- Batch orchestration ---------------------------------------------------


def process_batch(
    items: list[osxphotos.PhotoInfo],
    base_url: str,
    model: str,
    threads: int,
    video_frames: int,
    max_dimension: int = 1024,
    write: bool = True,
    discover_fn=None,
    refresh_interval: int = 21600,
    api_key: str = "",
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
        model=model,
        threads=threads,
        dry_run=not write,
        photos_found=len(photos),
        videos_found=len(videos),
    )
    photos_ok = photos_fail = videos_ok = videos_fail = 0
    last_refresh = time.monotonic()

    def _maybe_refresh(photo_insert_idx: int = 0, video_insert_idx: int = 0):
        """Re-query for new items if refresh interval has elapsed."""
        nonlocal last_refresh, total
        if discover_fn is None:
            return
        if time.monotonic() - last_refresh < refresh_interval:
            return
        last_refresh = time.monotonic()
        logger.info("Refreshing media list...")
        try:
            fresh = discover_fn()
        except Exception as e:
            logger.warning(f"Refresh failed: {e}")
            return
        new_items = [p for p in fresh if p.uuid not in seen_uuids]
        if not new_items:
            logger.info(
                f"Refresh complete: no new items ({len(fresh)} returned, all seen)"
            )
            return
        for p in new_items:
            seen_uuids.add(p.uuid)
        new_photos = [p for p in new_items if p.isphoto]
        new_videos = [p for p in new_items if not p.isphoto]
        photos[photo_insert_idx:photo_insert_idx] = new_photos
        videos[video_insert_idx:video_insert_idx] = new_videos
        total += len(new_items)
        logger.info(
            f"Added {len(new_items)} new items ({len(new_photos)} photos, {len(new_videos)} videos), total now {total}"
        )

    # Phase 1: Photos — export on main thread, LLM+write in parallel
    if photos:
        logger.info(f"Processing {len(photos)} photos (up to {threads} threads)...")
        pool = ThreadPoolExecutor(max_workers=threads)
        in_flight: dict = {}  # future -> PhotoInfo
        i = 0
        try:
            while (i < len(photos) or in_flight) and not is_shutting_down():
                # Collect completed futures
                for fut in [f for f in in_flight if f.done()]:
                    photo = in_flight.pop(fut)
                    processed += 1
                    try:
                        fut.result()
                        photos_ok += 1
                        logger.info(
                            f"[{processed}/{total}] Done: {photo.original_filename} (added {_format_date(photo)})"
                        )
                    except MaxFailuresExceeded:
                        raise
                    except Exception as e:
                        photos_fail += 1
                        logger.error(
                            f"[{processed}/{total}] Failed: {photo.original_filename}: {e}"
                        )

                # Backpressure: wait if all worker slots are busy
                if i < len(photos) and len(in_flight) >= threads:
                    time.sleep(0.1)
                    continue

                # Drain remaining futures
                if i >= len(photos):
                    time.sleep(0.1)
                    continue

                p = photos[i]
                i += 1

                _maybe_refresh(photo_insert_idx=i, video_insert_idx=0)

                # Export on main thread (osxphotos SQLite is thread-bound)
                try:
                    t_export = time.monotonic()
                    image_b64, export_meta = export_photo_as_base64(
                        p, max_dimension=max_dimension
                    )
                    export_duration = time.monotonic() - t_export
                except Exception as e:
                    processed += 1
                    photos_fail += 1
                    _record_error(p, "photo", model, e)
                    logger.error(
                        f"[{processed}/{total}] Export failed: {p.original_filename}: {e}"
                    )
                    tracker.record_failure(p.uuid, p.original_filename)
                    continue

                fut = pool.submit(
                    _label_photo_with_retry,
                    p,
                    image_b64,
                    export_meta,
                    export_duration,
                    base_url,
                    model,
                    write,
                    tracker,
                    api_key,
                )
                in_flight[fut] = p

            # Drain any remaining in-flight futures
            if is_shutting_down():
                for fut in in_flight:
                    fut.cancel()
            for fut in list(in_flight):
                photo = in_flight[fut]
                if fut.cancelled():
                    continue
                processed += 1
                try:
                    fut.result(timeout=5)
                    photos_ok += 1
                    logger.info(
                        f"[{processed}/{total}] Done: {photo.original_filename} (added {_format_date(photo)})"
                    )
                except MaxFailuresExceeded:
                    raise
                except Exception as e:
                    photos_fail += 1
                    logger.error(
                        f"[{processed}/{total}] Failed: {photo.original_filename}: {e}"
                    )
        finally:
            pool.shutdown(
                wait=not is_shutting_down(), cancel_futures=is_shutting_down()
            )

    if is_shutting_down():
        logger.info("Shutdown requested, stopping batch processing.")

    # Phase 2: Videos sequentially (on main thread)
    if videos:
        logger.info(f"Processing {len(videos)} videos sequentially...")
        i = 0
        while i < len(videos) and not is_shutting_down():
            video = videos[i]
            i += 1
            processed += 1

            _maybe_refresh(photo_insert_idx=len(photos), video_insert_idx=i)

            try:
                _process_video_with_retry(
                    video,
                    base_url,
                    model,
                    video_frames,
                    max_dimension,
                    write,
                    tracker,
                    api_key,
                )
                videos_ok += 1
                logger.info(
                    f"[{processed}/{total}] Done: {video.original_filename} (added {_format_date(video)})"
                )
            except MaxFailuresExceeded:
                raise
            except Exception as e:
                videos_fail += 1
                logger.error(
                    f"[{processed}/{total}] Failed: {video.original_filename}: {e}"
                )

    metrics.finish_run(
        run_id=run_id,
        photos_processed=photos_ok,
        videos_processed=videos_ok,
        photos_failed=photos_fail,
        videos_failed=videos_fail,
    )
