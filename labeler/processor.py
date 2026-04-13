"""Batch orchestration: parallel photo processing, sequential video processing."""

import logging
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urlparse

import osxphotos
from openai import APIConnectionError, APIStatusError, APITimeoutError

from labeler import metrics
from labeler.exporter import export_photo_as_base64, export_video_frames_as_base64
from labeler.llm import ServerPool, create_client, label_photo, label_video
from labeler.shutdown import is_shutting_down
from labeler.shutdown import wait as shutdown_wait
from labeler.writer import write_metadata

logger = logging.getLogger(__name__)

MAX_ITEM_FAILURES = 10
RETRY_BASE_DELAY = 5  # seconds
RETRY_MAX_DELAY = 300  # seconds
_HTTP_SERVER_ERROR = 500
_HTTP_BAD_REQUEST = 400
_POLL_INTERVAL = 0.1  # seconds between checking futures
_FUTURE_DRAIN_TIMEOUT = 5  # seconds to wait for remaining futures
DEFAULT_REFRESH_INTERVAL = 21600  # seconds (6 hours)


class MaxFailuresExceeded(RuntimeError):
    """Raised when a single item exceeds MAX_ITEM_FAILURES."""


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(
        exc, (APIConnectionError, APITimeoutError, ConnectionError, TimeoutError)
    ):
        return True
    if isinstance(exc, APIStatusError):
        if exc.status_code >= _HTTP_SERVER_ERROR:
            return True
        # LM Studio model crash returns 400 with "crashed" in the message
        if exc.status_code == _HTTP_BAD_REQUEST and "crashed" in str(exc).lower():
            return True
    return False


def _retry_delay(attempt: int) -> float:
    return min(RETRY_BASE_DELAY * (2**attempt), RETRY_MAX_DELAY)


def _format_date(item: osxphotos.PhotoInfo) -> str:
    dt = item.date_added or item.date
    return dt.strftime("%Y-%m-%d") if dt else "?"


def _server_label(server) -> str:
    """Short '[host model]' tag for per-item logs."""
    host = urlparse(server.base_url).hostname or server.base_url
    return f"[{host} {server.model}]"


def _record_error(
    item: osxphotos.PhotoInfo,
    media_type: str,
    model: str | None,
    error: Exception,
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
        """Record a failure for the given item.

        Raises MaxFailuresExceeded if the failure limit is reached.
        """
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
    server,
    write: bool,
) -> None:
    """LLM label + write metadata for an already-exported photo."""
    t_start = time.monotonic()
    client = create_client(server.base_url, api_key=server.api_key)

    logger.info(f"{_server_label(server)} Labeling photo: {item.original_filename}")
    t_llm = time.monotonic()
    labels, llm_retries = label_photo(
        client, server.model, image_b64, item.original_filename
    )
    llm_duration = time.monotonic() - t_llm

    t_write = time.monotonic()
    write_metadata(item.uuid, labels, model=server.model, write=write)
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
        model=server.model,
    )


def _label_photo_with_retry(
    item,
    image_b64,
    export_meta,
    export_duration,
    pool: ServerPool,
    write,
    tracker,
):
    attempt = 0
    last_model: str | None = None
    while True:
        server = pool.next()
        last_model = server.model
        try:
            _label_and_write_photo(
                item,
                image_b64,
                export_meta,
                export_duration,
                server,
                write,
            )
            return
        except Exception as e:
            if _is_retryable_error(e):
                delay = _retry_delay(attempt)
                attempt += 1
                logger.warning(
                    f"Retryable error on {server.base_url} "
                    f"(attempt {attempt}): {e}. Retrying in {delay}s..."
                )
                if shutdown_wait(delay):
                    raise
                continue
            tracker.record_failure(item.uuid, item.original_filename)
            _record_error(item, "photo", last_model, e)
            raise


# --- Video processing (fully on main thread) ------------------------------


def _process_single_video(
    item: osxphotos.PhotoInfo,
    server,
    video_frames: int,
    max_dimension: int,
    write: bool,
) -> None:
    """Export frames, label, write metadata, record metrics for one video."""
    t_start = time.monotonic()
    client = create_client(server.base_url, api_key=server.api_key)

    t_export = time.monotonic()
    frames_b64, export_meta = export_video_frames_as_base64(
        item, num_frames=video_frames, max_dimension=max_dimension
    )
    export_duration = time.monotonic() - t_export

    if not frames_b64:
        raise RuntimeError(f"No frames extracted from {item.original_filename}")

    logger.info(
        f"{_server_label(server)} Labeling video: "
        f"{item.original_filename} ({len(frames_b64)} frames)"
    )
    t_llm = time.monotonic()
    labels, llm_retries = label_video(
        client, server.model, frames_b64, item.original_filename
    )
    llm_duration = time.monotonic() - t_llm

    t_write = time.monotonic()
    write_metadata(item.uuid, labels, model=server.model, write=write)
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
        model=server.model,
    )


def _process_video_with_retry(
    item, pool: ServerPool, video_frames, max_dimension, write, tracker
):
    attempt = 0
    last_model: str | None = None
    while True:
        server = pool.next()
        last_model = server.model
        try:
            _process_single_video(
                item,
                server,
                video_frames,
                max_dimension,
                write,
            )
            return
        except Exception as e:
            if _is_retryable_error(e):
                delay = _retry_delay(attempt)
                attempt += 1
                logger.warning(
                    f"Retryable error on {server.base_url} "
                    f"(attempt {attempt}): {e}. Retrying in {delay}s..."
                )
                if shutdown_wait(delay):
                    raise
                continue
            tracker.record_failure(item.uuid, item.original_filename)
            _record_error(item, "video", last_model, e)
            raise


# --- Batch state and helpers ------------------------------------------------


@dataclass
class _BatchState:
    """Mutable state for a batch processing run."""

    photos: list = field(default_factory=list)
    videos: list = field(default_factory=list)
    seen_uuids: set = field(default_factory=set)
    total: int = 0
    processed: int = 0
    photos_ok: int = 0
    photos_fail: int = 0
    videos_ok: int = 0
    videos_fail: int = 0
    last_refresh: float = 0.0


def _init_batch(items: list[osxphotos.PhotoInfo]) -> _BatchState:
    """Split items into photos/videos and create initial batch state."""
    photos = [p for p in items if p.isphoto]
    videos = [p for p in items if not p.isphoto]
    seen_uuids = {p.uuid for p in items}
    return _BatchState(
        photos=photos,
        videos=videos,
        seen_uuids=seen_uuids,
        total=len(items),
    )


def _maybe_refresh(
    state: _BatchState,
    discover_fn,
    refresh_interval: int,
    photo_insert_idx: int = 0,
    video_insert_idx: int = 0,
) -> None:
    """Re-query for new items if refresh interval has elapsed."""
    if discover_fn is None:
        return
    if time.monotonic() - state.last_refresh < refresh_interval:
        return
    state.last_refresh = time.monotonic()
    logger.info("Refreshing media list...")
    try:
        fresh = discover_fn()
    except Exception as e:
        logger.warning(f"Refresh failed: {e}")
        return
    new_items = [p for p in fresh if p.uuid not in state.seen_uuids]
    if not new_items:
        logger.info(f"Refresh complete: no new items ({len(fresh)} returned, all seen)")
        return
    for p in new_items:
        state.seen_uuids.add(p.uuid)
    new_photos = [p for p in new_items if p.isphoto]
    new_videos = [p for p in new_items if not p.isphoto]
    state.photos[photo_insert_idx:photo_insert_idx] = new_photos
    state.videos[video_insert_idx:video_insert_idx] = new_videos
    state.total += len(new_items)
    logger.info(
        f"Added {len(new_items)} new items "
        f"({len(new_photos)} photos, "
        f"{len(new_videos)} videos), total now {state.total}"
    )


# --- Batch orchestration helpers --------------------------------------------


def _collect_completed_futures(in_flight: dict, state: _BatchState) -> None:
    """Drain done futures from in_flight, updating state counters."""
    for fut in [f for f in in_flight if f.done()]:
        photo = in_flight.pop(fut)
        state.processed += 1
        try:
            fut.result()
            state.photos_ok += 1
            logger.info(
                f"[{state.processed}/{state.total}] Done: "
                f"{photo.original_filename} "
                f"(added {_format_date(photo)})"
            )
        except MaxFailuresExceeded:
            raise
        except Exception as e:
            state.photos_fail += 1
            logger.error(
                f"[{state.processed}/{state.total}] Failed: "
                f"{photo.original_filename}: {e}"
            )


def _export_and_submit_photo(
    photo,
    executor,
    in_flight,
    state,
    server_pool: ServerPool,
    max_dimension,
    write,
    tracker,
    discover_fn,
    refresh_interval,
    photo_idx,
):
    """Export one photo on the main thread and submit LLM+write to the pool."""
    _maybe_refresh(
        state,
        discover_fn,
        refresh_interval,
        photo_insert_idx=photo_idx,
        video_insert_idx=0,
    )

    try:
        t_export = time.monotonic()
        image_b64, export_meta = export_photo_as_base64(
            photo, max_dimension=max_dimension
        )
        export_duration = time.monotonic() - t_export
    except Exception as e:
        state.processed += 1
        state.photos_fail += 1
        _record_error(photo, "photo", None, e)
        logger.error(
            f"[{state.processed}/{state.total}] Export failed: "
            f"{photo.original_filename}: {e}"
        )
        tracker.record_failure(photo.uuid, photo.original_filename)
        return

    fut = executor.submit(
        _label_photo_with_retry,
        photo,
        image_b64,
        export_meta,
        export_duration,
        server_pool,
        write,
        tracker,
    )
    in_flight[fut] = photo


def _drain_remaining_futures(in_flight: dict, state: _BatchState) -> None:
    """Drain in-flight futures after the main photo loop exits."""
    if is_shutting_down():
        for fut in in_flight:
            fut.cancel()
    for fut in list(in_flight):
        photo = in_flight[fut]
        if fut.cancelled():
            continue
        state.processed += 1
        try:
            fut.result(timeout=_FUTURE_DRAIN_TIMEOUT)
            state.photos_ok += 1
            logger.info(
                f"[{state.processed}/{state.total}] Done: "
                f"{photo.original_filename} "
                f"(added {_format_date(photo)})"
            )
        except MaxFailuresExceeded:
            raise
        except Exception as e:
            state.photos_fail += 1
            logger.error(
                f"[{state.processed}/{state.total}] Failed: "
                f"{photo.original_filename}: {e}"
            )


def _process_photos_parallel(
    state,
    threads,
    server_pool: ServerPool,
    max_dimension,
    write,
    tracker,
    discover_fn,
    refresh_interval,
):
    """Process photos: export on main thread, LLM+write in worker threads."""
    executor = ThreadPoolExecutor(max_workers=threads)
    in_flight: dict = {}  # future -> PhotoInfo
    photo_idx = 0
    try:
        while (photo_idx < len(state.photos) or in_flight) and not is_shutting_down():
            _collect_completed_futures(in_flight, state)

            # Backpressure: wait if all worker slots are busy
            if photo_idx < len(state.photos) and len(in_flight) >= threads:
                time.sleep(_POLL_INTERVAL)
                continue

            # Drain remaining futures
            if photo_idx >= len(state.photos):
                time.sleep(_POLL_INTERVAL)
                continue

            photo = state.photos[photo_idx]
            photo_idx += 1

            _export_and_submit_photo(
                photo,
                executor,
                in_flight,
                state,
                server_pool,
                max_dimension,
                write,
                tracker,
                discover_fn,
                refresh_interval,
                photo_idx,
            )

        _drain_remaining_futures(in_flight, state)
    finally:
        executor.shutdown(
            wait=not is_shutting_down(), cancel_futures=is_shutting_down()
        )


def _process_videos_sequential(
    state,
    server_pool: ServerPool,
    video_frames,
    max_dimension,
    write,
    tracker,
    discover_fn,
    refresh_interval,
):
    """Process videos sequentially on the main thread."""
    video_idx = 0
    while video_idx < len(state.videos) and not is_shutting_down():
        video = state.videos[video_idx]
        video_idx += 1
        state.processed += 1

        _maybe_refresh(
            state,
            discover_fn,
            refresh_interval,
            photo_insert_idx=len(state.photos),
            video_insert_idx=video_idx,
        )

        try:
            _process_video_with_retry(
                video,
                server_pool,
                video_frames,
                max_dimension,
                write,
                tracker,
            )
            state.videos_ok += 1
            logger.info(
                f"[{state.processed}/{state.total}] Done: "
                f"{video.original_filename} "
                f"(added {_format_date(video)})"
            )
        except MaxFailuresExceeded:
            raise
        except Exception as e:
            state.videos_fail += 1
            logger.error(
                f"[{state.processed}/{state.total}] Failed: "
                f"{video.original_filename}: {e}"
            )


# --- Batch orchestration ---------------------------------------------------


def process_batch(
    items: list[osxphotos.PhotoInfo],
    server_pool: ServerPool,
    threads: int,
    video_frames: int,
    max_dimension: int = 1024,
    write: bool = True,
    discover_fn=None,
    refresh_interval: int = DEFAULT_REFRESH_INTERVAL,
):
    """Process a batch of media: photos in parallel, then videos sequentially.

    Photo exports happen on the main thread (osxphotos uses SQLite which is
    bound to the creating thread), then LLM + write run in worker threads.

    If discover_fn is provided, the main thread will call it every
    refresh_interval seconds to pick up newly added items.

    LLM calls are distributed round-robin across ``server_pool``. On retry a
    fresh server is selected so a crashed backend rotates away.
    """
    state = _init_batch(items)
    tracker = ItemFailureTracker()

    run_model = ",".join(server_pool.models())
    run_id = metrics.start_run(
        model=run_model,
        threads=threads,
        dry_run=not write,
        photos_found=len(state.photos),
        videos_found=len(state.videos),
    )
    state.last_refresh = time.monotonic()

    if state.photos:
        logger.info(
            f"Processing {len(state.photos)} photos "
            f"(up to {threads} threads across {len(server_pool)} server(s))..."
        )
        _process_photos_parallel(
            state,
            threads,
            server_pool,
            max_dimension,
            write,
            tracker,
            discover_fn,
            refresh_interval,
        )

    if is_shutting_down():
        logger.info("Shutdown requested, stopping batch processing.")

    if state.videos:
        logger.info(f"Processing {len(state.videos)} videos sequentially...")
        _process_videos_sequential(
            state,
            server_pool,
            video_frames,
            max_dimension,
            write,
            tracker,
            discover_fn,
            refresh_interval,
        )

    metrics.finish_run(
        run_id=run_id,
        photos_processed=state.photos_ok,
        videos_processed=state.videos_ok,
        photos_failed=state.photos_fail,
        videos_failed=state.videos_fail,
    )
