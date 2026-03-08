import logging
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import osxphotos
from openai import APIConnectionError, APITimeoutError, APIStatusError

from labeler.exporter import export_photo_as_base64, export_video_frames_as_base64
from labeler.llm import create_client, label_photo, label_video
from labeler.writer import write_metadata
from labeler import metrics

logger = logging.getLogger(__name__)

MAX_ITEM_FAILURES = 10
NETWORK_RETRY_DELAY = 90  # seconds


def _is_network_error(exc: Exception) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError, ConnectionError, TimeoutError)):
        return True
    if isinstance(exc, APIStatusError) and exc.status_code >= 500:
        return True
    return False


def _process_single_photo(
    photo: osxphotos.PhotoInfo,
    base_url: str,
    model: str,
    max_dimension: int,
    write: bool,
) -> None:
    """Process a single photo: export, label, write metadata, record metrics."""
    t_start = time.monotonic()

    client = create_client(base_url)

    t_export = time.monotonic()
    image_b64, export_meta = export_photo_as_base64(photo, max_dimension=max_dimension)
    export_duration = time.monotonic() - t_export

    t_llm = time.monotonic()
    labels, llm_retries = label_photo(client, model, image_b64, photo.original_filename)
    llm_duration = time.monotonic() - t_llm

    t_write = time.monotonic()
    write_metadata(photo.uuid, labels, write=write)
    write_duration = time.monotonic() - t_write

    total_duration = time.monotonic() - t_start

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


def process_batch(
    items: list[osxphotos.PhotoInfo],
    base_url: str,
    model: str,
    threads: int,
    video_frames: int,
    max_dimension: int = 1024,
    write: bool = True,
):
    """Process a batch of media: photos in parallel, then videos sequentially."""
    photos = [p for p in items if p.isphoto]
    videos = [p for p in items if not p.isphoto]
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

    # Phase 1: Photos in parallel
    if photos:
        logger.info(f"Processing {len(photos)} photos (up to {threads} threads)...")
        with ThreadPoolExecutor(max_workers=threads) as pool:
            future_to_photo = {
                pool.submit(
                    _process_photo_with_retry, p, base_url, model, max_dimension, write, tracker
                ): p
                for p in photos
            }
            for future in as_completed(future_to_photo):
                photo = future_to_photo[future]
                processed += 1
                try:
                    future.result()
                    photos_ok += 1
                    logger.info(f"[{processed}/{total}] Done: {photo.original_filename}")
                except RuntimeError as e:
                    if "failed" in str(e) and "times" in str(e):
                        raise  # Max failures exceeded
                    photos_fail += 1
                    logger.error(f"[{processed}/{total}] Failed: {photo.original_filename}: {e}")
                except Exception as e:
                    photos_fail += 1
                    logger.error(f"[{processed}/{total}] Failed: {photo.original_filename}: {e}")

    # Phase 2: Videos sequentially
    if videos:
        logger.info(f"Processing {len(videos)} videos sequentially...")
        for video in videos:
            processed += 1
            try:
                _process_video_with_retry(video, base_url, model, video_frames, max_dimension, write, tracker)
                videos_ok += 1
                logger.info(f"[{processed}/{total}] Done: {video.original_filename}")
            except RuntimeError as e:
                if "failed" in str(e) and "times" in str(e):
                    raise
                videos_fail += 1
                logger.error(f"[{processed}/{total}] Failed: {video.original_filename}: {e}")
            except Exception as e:
                videos_fail += 1
                logger.error(f"[{processed}/{total}] Failed: {video.original_filename}: {e}")

    metrics.finish_run(
        run_id=run_id,
        photos_processed=photos_ok,
        videos_processed=videos_ok,
        photos_failed=photos_fail,
        videos_failed=videos_fail,
    )


def _process_photo_with_retry(photo, base_url, model, max_dimension, write, tracker):
    while True:
        try:
            _process_single_photo(photo, base_url, model, max_dimension, write)
            return
        except Exception as e:
            if _is_network_error(e):
                logger.warning(f"Network error: {e}. Retrying in {NETWORK_RETRY_DELAY}s...")
                time.sleep(NETWORK_RETRY_DELAY)
                continue
            tracker.record_failure(photo.uuid, photo.original_filename)
            _record_error(photo, "photo", model, e)
            raise


def _process_video_with_retry(photo, base_url, model, video_frames, max_dimension, write, tracker):
    while True:
        try:
            _process_single_video(photo, base_url, model, video_frames, max_dimension, write)
            return
        except Exception as e:
            if _is_network_error(e):
                logger.warning(f"Network error: {e}. Retrying in {NETWORK_RETRY_DELAY}s...")
                time.sleep(NETWORK_RETRY_DELAY)
                continue
            tracker.record_failure(photo.uuid, photo.original_filename)
            _record_error(photo, "video", model, e)
            raise
