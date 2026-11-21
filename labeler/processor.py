"""Batch orchestration: items exported in turn, labeled and written in parallel."""

import logging
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from urllib.parse import urlparse

import osxphotos
from openai import APIConnectionError, APIStatusError, APITimeoutError

from labeler import metrics
from labeler.exporter import (
    export_photo_as_base64,
    exported_video,
    video_frames_as_base64,
)
from labeler.llm import (
    ServerPool,
    add_transcript_to_labels,
    create_client,
    label_photo,
    label_video,
    video_settings_tag,
)
from labeler.shutdown import is_shutting_down
from labeler.shutdown import wait as shutdown_wait
from labeler.transcriber import (
    Transcript,
    Whisper,
    existing_transcript,
    server_answers,
    transcribe_video,
)
from labeler.writer import (
    LABEL_TAG_PREFIXES,
    OCR_TAG_PREFIX,
    TRANSCRIPT_TAG_PREFIX,
    write_labels_with_transcript,
    write_metadata,
    write_transcript,
)

logger = logging.getLogger(__name__)

MAX_ITEM_FAILURES = 10
RETRY_BASE_DELAY = 5  # seconds
RETRY_MAX_DELAY = 300  # seconds
_HTTP_SERVER_ERROR = 500
_HTTP_BAD_REQUEST = 400
_HTTP_TOO_MANY_REQUESTS = 429
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
        if exc.status_code == _HTTP_TOO_MANY_REQUESTS:
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


def _server_tag(server) -> str:
    """Stable 'host:model' identifier stored on each metric row."""
    host = urlparse(server.base_url).hostname or server.base_url
    return f"{host}:{server.model}"


def _record_error(
    item: osxphotos.PhotoInfo,
    media_type: str,
    model: str | None,
    server: str | None,
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
        server=server,
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


# --- Photos ----------------------------------------------------------------


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
    labels, llm_retries, in_toks, out_toks = label_photo(
        client,
        server.model,
        image_b64,
        item.original_filename,
        reasoning_effort=server.reasoning_effort or None,
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
        server=_server_tag(server),
        input_tokens=in_toks,
        output_tokens=out_toks,
    )


def _run_with_retry(item, media_type: str, pool: ServerPool, tracker, work):
    attempt = 0
    while True:
        server = pool.acquire()
        released = False
        try:
            work(server)
            return
        except Exception as e:
            if _is_retryable_error(e):
                pool.release(server)
                released = True
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
            _record_error(item, media_type, server.model, _server_tag(server), e)
            raise
        finally:
            if not released:
                pool.release(server)


def _export_photo(item: osxphotos.PhotoInfo, max_dimension: int, write: bool):
    t_export = time.monotonic()
    image_b64, export_meta = export_photo_as_base64(item, max_dimension=max_dimension)
    return partial(
        _label_and_write_photo,
        item,
        image_b64,
        export_meta,
        time.monotonic() - t_export,
        write=write,
    )


# --- Videos ----------------------------------------------------------------


def _transcribe_or_none(
    video_path: str, filename: str, whisper: Whisper
) -> Transcript | None:
    try:
        return transcribe_video(video_path, filename, whisper)
    except Exception as e:
        logger.warning(f"Transcription failed, labeling without it: {filename}: {e}")
        return None


@dataclass(frozen=True)
class _ExportedVideo:
    frames_b64: list[str]
    meta: dict
    export_duration: float
    prepare_duration: float
    transcript: Transcript | None


def _label_and_write_video(
    item: osxphotos.PhotoInfo,
    video: _ExportedVideo,
    server,
    video_frame_batch: int,
    video_tag: str,
    write: bool,
) -> None:
    t_start = time.monotonic()
    client = create_client(server.base_url, api_key=server.api_key)
    transcript = video.transcript

    logger.info(
        f"{_server_label(server)} Labeling video: "
        f"{item.original_filename} ({len(video.frames_b64)} frames"
        f"{', with transcript' if transcript and transcript.text else ''})"
    )
    t_llm = time.monotonic()
    labels, llm_retries, in_toks, out_toks = label_video(
        client,
        server.model,
        video.frames_b64,
        item.original_filename,
        batch_size=video_frame_batch,
        transcript=transcript.text if transcript else "",
        reasoning_effort=server.reasoning_effort or None,
    )
    llm_duration = time.monotonic() - t_llm

    t_write = time.monotonic()
    write_metadata(
        item.uuid,
        labels,
        model=server.model,
        write=write,
        video_tag=video_tag,
        transcript_tag=transcript.keyword if transcript else None,
    )
    write_duration = time.monotonic() - t_write

    metrics.record_item(
        uuid=item.uuid,
        filename=item.original_filename,
        media_type="video",
        is_icloud_only=item.ismissing,
        status="success",
        export_duration_s=video.export_duration,
        llm_duration_s=llm_duration,
        write_duration_s=write_duration,
        total_duration_s=video.prepare_duration + time.monotonic() - t_start,
        image_size_bytes=video.meta.get("image_size_bytes"),
        image_width=video.meta.get("image_width"),
        image_height=video.meta.get("image_height"),
        num_frames=video.meta.get("num_frames"),
        llm_retries=llm_retries,
        keywords_count=len(labels.get("keywords", [])),
        has_ocr=bool(labels.get("ocr_text")),
        model=server.model,
        server=_server_tag(server),
        input_tokens=in_toks,
        output_tokens=out_toks,
    )


def _export_video(
    item: osxphotos.PhotoInfo,
    video_frames: int,
    video_frame_batch: int,
    max_dimension: int,
    whisper: Whisper | None,
    write: bool,
):
    t_start = time.monotonic()
    transcript = existing_transcript(item)

    with exported_video(item) as video_path:
        frames_b64, export_meta = video_frames_as_base64(
            video_path,
            item.original_filename,
            num_frames=video_frames,
            max_dimension=max_dimension,
        )
        export_duration = time.monotonic() - t_start
        if frames_b64 and whisper and transcript is None:
            transcript = _transcribe_or_none(
                video_path, item.original_filename, whisper
            )

    if not frames_b64:
        raise RuntimeError(f"No frames extracted from {item.original_filename}")

    video = _ExportedVideo(
        frames_b64=frames_b64,
        meta=export_meta,
        export_duration=export_duration,
        prepare_duration=time.monotonic() - t_start,
        transcript=transcript,
    )
    return partial(
        _label_and_write_video,
        item,
        video,
        video_frame_batch=video_frame_batch,
        video_tag=video_settings_tag(video_frames, video_frame_batch),
        write=write,
    )


# --- Adding transcripts to labeled videos ------------------------------------


def _current_labels(item: osxphotos.PhotoInfo) -> dict:
    keywords = item.keywords or []
    tag_prefixes = (*LABEL_TAG_PREFIXES, TRANSCRIPT_TAG_PREFIX)
    return {
        "keywords": [k for k in keywords if not k.startswith(tag_prefixes)],
        "title": item.title or "",
        "description": item.description or "",
        "ocr_text": next(
            (
                k.removeprefix(OCR_TAG_PREFIX)
                for k in keywords
                if k.startswith(OCR_TAG_PREFIX)
            ),
            "",
        ),
    }


def _add_transcript(
    item: osxphotos.PhotoInfo, server, whisper: Whisper, write: bool
) -> None:
    t_start = time.monotonic()
    with exported_video(item) as video_path:
        export_duration = time.monotonic() - t_start
        transcript = transcribe_video(video_path, item.original_filename, whisper)
    if not transcript.text:
        write_transcript(item.uuid, transcript.keyword, write=write)
        return

    logger.info(
        f"{_server_label(server)} Adding transcript to labels: {item.original_filename}"
    )
    client = create_client(server.base_url, api_key=server.api_key)
    t_llm = time.monotonic()
    labels, llm_retries, in_toks, out_toks = add_transcript_to_labels(
        client,
        server.model,
        _current_labels(item),
        transcript.text,
        reasoning_effort=server.reasoning_effort or None,
    )
    llm_duration = time.monotonic() - t_llm

    t_write = time.monotonic()
    write_labels_with_transcript(item.uuid, labels, transcript.keyword, write=write)
    write_duration = time.monotonic() - t_write

    metrics.record_item(
        uuid=item.uuid,
        filename=item.original_filename,
        media_type="transcript",
        is_icloud_only=item.ismissing,
        status="success",
        export_duration_s=export_duration,
        llm_duration_s=llm_duration,
        write_duration_s=write_duration,
        total_duration_s=time.monotonic() - t_start,
        llm_retries=llm_retries,
        keywords_count=len(labels.get("keywords", [])),
        model=server.model,
        server=_server_tag(server),
        input_tokens=in_toks,
        output_tokens=out_toks,
    )


# --- Batch state and helpers ------------------------------------------------


@dataclass
class _BatchState:
    """Mutable state for a batch processing run."""

    photos: list = field(default_factory=list)
    videos: list = field(default_factory=list)
    untranscribed: list = field(default_factory=list)
    seen_uuids: set = field(default_factory=set)
    total: int = 0
    processed: int = 0
    photos_ok: int = 0
    photos_fail: int = 0
    videos_ok: int = 0
    videos_fail: int = 0
    last_refresh: float = 0.0


def _init_batch(
    items: list[osxphotos.PhotoInfo], untranscribed: list[osxphotos.PhotoInfo]
) -> _BatchState:
    """Split items into photos/videos and create initial batch state."""
    photos = [p for p in items if p.isphoto]
    videos = [p for p in items if not p.isphoto]
    seen_uuids = {p.uuid for p in items + untranscribed}
    return _BatchState(
        photos=photos,
        videos=videos,
        untranscribed=list(untranscribed),
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


def _record_outcome(state: _BatchState, item: osxphotos.PhotoInfo, ok: bool) -> None:
    if item.isphoto and ok:
        state.photos_ok += 1
    elif item.isphoto:
        state.photos_fail += 1
    elif ok:
        state.videos_ok += 1
    else:
        state.videos_fail += 1


def _finish(fut, item, state: _BatchState, timeout: float | None = None) -> None:
    state.processed += 1
    try:
        fut.result(timeout=timeout)
    except MaxFailuresExceeded:
        raise
    except Exception as e:
        _record_outcome(state, item, ok=False)
        logger.error(
            f"[{state.processed}/{state.total}] Failed: {item.original_filename}: {e}"
        )
        return
    _record_outcome(state, item, ok=True)
    logger.info(
        f"[{state.processed}/{state.total}] Done: "
        f"{item.original_filename} (added {_format_date(item)})"
    )


def _collect_completed_futures(in_flight: dict, state: _BatchState) -> None:
    for fut in [f for f in in_flight if f.done()]:
        _finish(fut, in_flight.pop(fut), state)


def _drain_remaining_futures(in_flight: dict, state: _BatchState) -> None:
    if is_shutting_down():
        for fut in in_flight:
            fut.cancel()
    for fut, item in list(in_flight.items()):
        if not fut.cancelled():
            _finish(fut, item, state, timeout=_FUTURE_DRAIN_TIMEOUT)


def _export_or_fail(item, media_type: str, export, state: _BatchState, tracker):
    try:
        return export(item)
    except Exception as e:
        state.processed += 1
        _record_outcome(state, item, ok=False)
        _record_error(item, media_type, None, None, e)
        logger.error(
            f"[{state.processed}/{state.total}] Export failed: "
            f"{item.original_filename}: {e}"
        )
        tracker.record_failure(item.uuid, item.original_filename)
        return None


def _insert_positions(state: _BatchState, media_type: str, idx: int) -> dict:
    if media_type == "photo":
        return {"photo_insert_idx": idx, "video_insert_idx": 0}
    return {"photo_insert_idx": len(state.photos), "video_insert_idx": idx}


def _label_in_parallel(
    state: _BatchState,
    media_type: str,
    export,
    server_pool: ServerPool,
    tracker,
    discover_fn,
    refresh_interval,
):
    items = state.photos if media_type == "photo" else state.videos
    total_threads = server_pool.total_threads
    executor = ThreadPoolExecutor(max_workers=total_threads)
    in_flight: dict = {}
    idx = 0
    try:
        while (idx < len(items) or in_flight) and not is_shutting_down():
            _collect_completed_futures(in_flight, state)
            if idx >= len(items) or len(in_flight) >= total_threads:
                time.sleep(_POLL_INTERVAL)
                continue

            item = items[idx]
            idx += 1
            _maybe_refresh(
                state,
                discover_fn,
                refresh_interval,
                **_insert_positions(state, media_type, idx),
            )
            work = _export_or_fail(item, media_type, export, state, tracker)
            if work is not None:
                fut = executor.submit(
                    _run_with_retry, item, media_type, server_pool, tracker, work
                )
                in_flight[fut] = item

        _drain_remaining_futures(in_flight, state)
    finally:
        executor.shutdown(
            wait=not is_shutting_down(), cancel_futures=is_shutting_down()
        )


def _add_transcripts_sequential(
    state, server_pool: ServerPool, whisper, write, tracker
):
    if not server_answers(whisper):
        logger.warning(
            f"Whisper server {whisper.url} isn't answering; "
            "adding transcripts next cycle"
        )
        return
    total = len(state.untranscribed)
    for position, video in enumerate(state.untranscribed, start=1):
        if is_shutting_down():
            return
        progress = f"[transcript {position}/{total}]"
        try:
            _run_with_retry(
                video,
                "transcript",
                server_pool,
                tracker,
                partial(_add_transcript, video, whisper=whisper, write=write),
            )
            state.videos_ok += 1
            logger.info(f"{progress} Done: {video.original_filename}")
        except MaxFailuresExceeded:
            raise
        except Exception as e:
            state.videos_fail += 1
            logger.error(f"{progress} Failed: {video.original_filename}: {e}")


# --- Batch orchestration ---------------------------------------------------


def process_batch(
    items: list[osxphotos.PhotoInfo],
    server_pool: ServerPool,
    video_frames: int,
    video_frame_batch: int = 5,
    max_dimension: int = 1024,
    write: bool = True,
    discover_fn=None,
    refresh_interval: int = DEFAULT_REFRESH_INTERVAL,
    whisper: Whisper | None = None,
    untranscribed: list[osxphotos.PhotoInfo] | None = None,
) -> int:
    """Process a batch of media: photos, then videos.

    Exports happen one at a time on the main thread (osxphotos uses SQLite
    which is bound to the creating thread), then LLM + write run in worker
    threads, so the next item exports while earlier ones are labeled.

    With ``whisper`` set, videos are transcribed after export so the labels
    can use what is said. ``untranscribed`` are labeled videos with no
    transcript yet: they are transcribed and their labels updated with the
    transcript in a text-only request, after the other videos.

    If discover_fn is provided, the main thread will call it every
    refresh_interval seconds to pick up newly added items.

    LLM calls are distributed round-robin across ``server_pool``, with each
    server limited to its own ``threads`` slot count. On retry a fresh server
    is selected so a crashed backend rotates away.

    Returns the number of items labeled.
    """
    state = _init_batch(items, untranscribed or [])
    tracker = ItemFailureTracker()
    total_threads = server_pool.total_threads

    run_model = ",".join(server_pool.models())
    run_servers = ",".join(_server_tag(s) for s in server_pool.servers())
    run_id = metrics.start_run(
        model=run_model,
        servers=run_servers,
        threads=total_threads,
        dry_run=not write,
        photos_found=len(state.photos),
        videos_found=len(state.videos) + len(state.untranscribed),
    )
    state.last_refresh = time.monotonic()

    if state.photos:
        breakdown = ", ".join(
            f"{s.base_url}={s.threads}" for s in server_pool.servers()
        )
        logger.info(
            f"Processing {len(state.photos)} photos "
            f"(up to {total_threads} threads across {len(server_pool)} server(s): "
            f"{breakdown})..."
        )
        _label_in_parallel(
            state,
            "photo",
            partial(_export_photo, max_dimension=max_dimension, write=write),
            server_pool,
            tracker,
            discover_fn,
            refresh_interval,
        )

    if is_shutting_down():
        logger.info("Shutdown requested, stopping batch processing.")

    if state.videos:
        logger.info(
            f"Processing {len(state.videos)} videos "
            f"(up to {total_threads} at a time)..."
        )
        _label_in_parallel(
            state,
            "video",
            partial(
                _export_video,
                video_frames=video_frames,
                video_frame_batch=video_frame_batch,
                max_dimension=max_dimension,
                whisper=whisper,
                write=write,
            ),
            server_pool,
            tracker,
            discover_fn,
            refresh_interval,
        )

    if state.untranscribed and whisper and not is_shutting_down():
        logger.info(
            f"Adding transcripts to {len(state.untranscribed)} labeled videos..."
        )
        _add_transcripts_sequential(state, server_pool, whisper, write, tracker)

    metrics.finish_run(
        run_id=run_id,
        photos_processed=state.photos_ok,
        videos_processed=state.videos_ok,
        photos_failed=state.photos_fail,
        videos_failed=state.videos_fail,
    )
    return state.photos_ok + state.videos_ok
