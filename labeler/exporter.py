"""HEIC-to-JPEG photo conversion and video frame extraction."""

import base64
import io
import logging
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import objc
import osxphotos
import Photos
from Foundation import NSDate, NSRunLoop

logger = logging.getLogger(__name__)

PHOTO_EXPORT_TIMEOUT = 30  # seconds
VIDEO_EXPORT_TIMEOUT = 300  # seconds
JPEG_QUALITY = 85
FFMPEG_QUALITY = "2"  # -q:v value for ffmpeg frame extraction
# Below this duration the clip is essentially a single frame; evenly-spaced
# seek timestamps cluster too close to t=0 to land on a decodable keyframe.
SHORT_VIDEO_THRESHOLD_S = 0.5
MIN_FRAME_SPACING_S = 0.5
PHOTOS_APP_QUIT_TIMEOUT_S = 20
PHOTOS_APP_STARTUP_WAIT_S = 10
AUDIO_SAMPLE_RATE = 16000
PHOTOKIT_POLL_S = 0.05
FRAME_WORKERS = 8

_photos_access_requested = threading.Event()


class DownloadTimedOut(Exception):
    pass


class VideoNotDownloaded(RuntimeError):
    pass


def _resize_if_needed(img, max_dim: int):
    """Resize image so the longest side is at most max_dim pixels.

    Maintains aspect ratio.
    """
    w, h = img.size
    if max(w, h) <= max_dim:
        return img
    scale = max_dim / max(w, h)
    new_w, new_h = int(w * scale), int(h * scale)
    logger.debug(f"Resizing {w}x{h} -> {new_w}x{new_h}")
    return img.resize(
        (new_w, new_h), img.Resampling.LANCZOS if hasattr(img, "Resampling") else 1
    )


def _open_image(path: str, tmpdir: str):
    """Open an image file with PIL, falling back to sips for unsupported formats."""
    import pillow_heif
    from PIL import Image

    pillow_heif.register_heif_opener()

    try:
        return Image.open(path)
    except Exception:
        logger.debug(f"PIL cannot open {path}, converting via sips...")
        sips_jpg = str(Path(tmpdir) / "sips_converted.jpg")
        result = subprocess.run(
            ["sips", "-s", "format", "jpeg", path, "--out", sips_jpg],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not Path(sips_jpg).exists():
            raise RuntimeError(
                f"sips conversion failed for {Path(path).name}: {result.stderr.strip()}"
            ) from None
        return Image.open(sips_jpg)


def _photos_access_allowed() -> bool:
    status = Photos.PHPhotoLibrary.authorizationStatusForAccessLevel_(
        Photos.PHAccessLevelReadWrite
    )
    if status == Photos.PHAuthorizationStatusNotDetermined:
        if not _photos_access_requested.is_set():
            _photos_access_requested.set()
            logger.info("Asking for access to Photos to read smaller versions")
            Photos.PHPhotoLibrary.requestAuthorizationForAccessLevel_handler_(
                Photos.PHAccessLevelReadWrite, lambda _status: None
            )
        return False
    return status == Photos.PHAuthorizationStatusAuthorized


def _photokit_asset(photo):
    if not _photos_access_allowed():
        return None
    return Photos.PHAsset.fetchAssetsWithLocalIdentifiers_options_(
        [f"{photo.uuid}/L0/001"], None
    ).firstObject()


def wait_for_photokit() -> None:
    NSRunLoop.currentRunLoop().runUntilDate_(
        NSDate.dateWithTimeIntervalSinceNow_(PHOTOKIT_POLL_S)
    )


class _PhotoKitRequest:
    def __init__(self, photo, start):
        self._uuid = photo.uuid
        self._done = threading.Event()
        self._result = None
        self._manager = Photos.PHImageManager.defaultManager()
        self._id = start(self._manager, self._finish)

    def _finish(self, value):
        self._result = value
        self._done.set()

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def wait(self, timeout: float, waited: float = 0.0):
        deadline = time.monotonic() + timeout
        while not self._done.is_set():
            wait_for_photokit()
            if not self._done.is_set() and time.monotonic() > deadline:
                self.cancel()
                logger.warning(
                    f"Photos didn't return {self._uuid} within {timeout + waited:.0f}s"
                )
                raise DownloadTimedOut(self._uuid)
        return self._result

    def cancel(self):
        self._manager.cancelImageRequest_(self._id)


RequestFn = Callable[[osxphotos.PhotoInfo], "_PhotoKitRequest | None"]


class PhotoKitPrefetch:
    def __init__(self, request: RequestFn, timeout: float):
        self._request = request
        self._timeout = timeout
        self._pending: dict[str, _PhotoKitRequest | None] = {}
        self._first_waited: dict[str, float] = {}

    def start(self, items: Iterable[osxphotos.PhotoInfo]) -> None:
        with objc.autorelease_pool():
            for item in items:
                if item.uuid not in self._pending:
                    self._pending[item.uuid] = self._request(item)

    def next_ready(self, window: list[osxphotos.PhotoInfo]) -> int | None:
        self.start(window)
        now = time.monotonic()
        self._first_waited.setdefault(window[0].uuid, now)
        for position, item in enumerate(window):
            request = self._pending.get(item.uuid)
            waited = now - self._first_waited.get(item.uuid, now)
            if request is None or request.done or waited >= self._timeout:
                return position
        return None

    def take(self, item: osxphotos.PhotoInfo):
        if item.uuid in self._pending:
            request = self._pending.pop(item.uuid)
        else:
            request = self._request(item)
        first = self._first_waited.pop(item.uuid, None)
        if request is None:
            return None
        waited = time.monotonic() - first if first is not None else 0.0
        return request.wait(max(self._timeout - waited, 0.0), waited)

    def cancel(self) -> None:
        for request in self._pending.values():
            if request is not None:
                request.cancel()
        self._pending.clear()
        self._first_waited.clear()


def _image_request(photo, max_dimension: int) -> _PhotoKitRequest | None:
    asset = _photokit_asset(photo)
    if asset is None:
        return None
    options = Photos.PHImageRequestOptions.alloc().init()
    options.setNetworkAccessAllowed_(True)
    options.setDeliveryMode_(Photos.PHImageRequestOptionsDeliveryModeHighQualityFormat)
    options.setResizeMode_(Photos.PHImageRequestOptionsResizeModeExact)

    def start(manager, finish):
        request_image = (
            manager.requestImageForAsset_targetSize_contentMode_options_resultHandler_
        )
        return request_image(
            asset,
            (max_dimension, max_dimension),
            Photos.PHImageContentModeAspectFit,
            options,
            lambda image, _info: finish(image),
        )

    return _PhotoKitRequest(photo, start)


def photo_prefetch(max_dimension: int) -> PhotoKitPrefetch:
    return PhotoKitPrefetch(
        lambda photo: _image_request(photo, max_dimension), PHOTO_EXPORT_TIMEOUT
    )


def _photokit_image(photo, max_dimension: int, prefetch: PhotoKitPrefetch | None):
    from PIL import Image

    prefetch = prefetch or photo_prefetch(max_dimension)
    try:
        image = prefetch.take(photo)
    except DownloadTimedOut:
        return None
    tiff = image.TIFFRepresentation() if image is not None else None
    if tiff is None:
        return None
    return Image.open(io.BytesIO(bytes(tiff)))


def _resolve_export_path(photo, tmpdir):
    """Export photo via osxphotos and return the export path, or None on failure."""
    exported = photo.export(
        tmpdir, use_photos_export=True, timeout=PHOTO_EXPORT_TIMEOUT
    )
    if exported:
        return exported[0]

    if photo.path and Path(photo.path).exists():
        logger.warning(
            f"Photos export failed for {photo.uuid}, "
            f"falling back to original at {photo.path}"
        )
        return photo.path

    return None


def _open_or_fallback(photo, export_path, tmpdir):
    """Open image from export path, falling back to derivatives if needed."""
    img = None
    if export_path is not None:
        try:
            size_mb = Path(export_path).stat().st_size / (1024 * 1024)
            logger.debug(f"Exported {export_path} ({size_mb:.1f} MB)")
            img = _open_image(export_path, tmpdir)
            img.load()  # Force full read to catch truncated files early
        except Exception as e:
            logger.warning(f"Failed to open {export_path}: {e}")
            img = None

    if img is not None:
        return img

    derivatives = photo.path_derivatives
    if not derivatives:
        raise RuntimeError(
            f"Failed to export photo {photo.uuid}: "
            f"no export, original, or derivative available"
        )
    logger.warning(f"Using derivative for {photo.uuid} at {derivatives[0]}")
    return _open_image(derivatives[0], tmpdir)


def _encode_as_jpeg(img, max_dimension, tmpdir):
    """Convert image to JPEG, resize, and return (base64_string, metadata_dict)."""
    img = img.convert("RGB")
    img = _resize_if_needed(img, max_dimension)
    jpeg_path = str(Path(tmpdir) / "photo.jpg")
    img.save(jpeg_path, "JPEG", quality=JPEG_QUALITY)
    jpeg_size = Path(jpeg_path).stat().st_size
    jpeg_mb = jpeg_size / (1024 * 1024)
    logger.debug(f"JPEG: {img.size[0]}x{img.size[1]} ({jpeg_mb:.1f} MB)")

    with Path(jpeg_path).open("rb") as f:
        b64 = base64.standard_b64encode(f.read()).decode("utf-8")
    logger.debug(f"Base64 encoded ({len(b64)} chars)")
    meta = {
        "image_size_bytes": jpeg_size,
        "image_width": img.size[0],
        "image_height": img.size[1],
    }
    return b64, meta


def export_photo_as_base64(
    photo: osxphotos.PhotoInfo,
    max_dimension: int = 1024,
    prefetch: PhotoKitPrefetch | None = None,
) -> tuple[str, dict]:
    """Export photo as JPEG and return (base64_string, metadata_dict)."""
    logger.debug(f"Exporting photo (missing={photo.ismissing})...")
    with tempfile.TemporaryDirectory() as tmpdir, objc.autorelease_pool():
        img = _photokit_image(photo, max_dimension, prefetch)
        if img is None:
            export_path = _resolve_export_path(photo, tmpdir)
            img = _open_or_fallback(photo, export_path, tmpdir)
        return _encode_as_jpeg(img, max_dimension, tmpdir)


def _has_stream(path: str, stream: str) -> bool:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            stream,
            "-show_entries",
            "stream=codec_name",
            "-of",
            "csv=p=0",
            path,
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _has_video_stream(path: str) -> bool:
    """Return True if ffprobe finds at least one decodable video stream."""
    return _has_stream(path, "v:0")


def _photos_app_running() -> bool:
    result = subprocess.run(["pgrep", "-x", "Photos"], capture_output=True)
    return result.returncode == 0


def _restart_photos_app():
    subprocess.run(["killall", "Photos"], capture_output=True)
    deadline = time.monotonic() + PHOTOS_APP_QUIT_TIMEOUT_S
    while _photos_app_running() and time.monotonic() < deadline:
        time.sleep(0.5)
    if _photos_app_running():
        subprocess.run(["killall", "-9", "Photos"], capture_output=True)
    subprocess.run(["open", "-a", "Photos"])
    time.sleep(PHOTOS_APP_STARTUP_WAIT_S)


def _video_request(photo) -> _PhotoKitRequest | None:
    asset = _photokit_asset(photo)
    if asset is None:
        return None
    options = Photos.PHVideoRequestOptions.alloc().init()
    options.setNetworkAccessAllowed_(True)
    options.setDeliveryMode_(
        Photos.PHVideoRequestOptionsDeliveryModeMediumQualityFormat
    )

    def start(manager, finish):
        return manager.requestAVAssetForVideo_options_resultHandler_(
            asset, options, lambda av_asset, _audio_mix, _info: finish(av_asset)
        )

    return _PhotoKitRequest(photo, start)


def video_prefetch() -> PhotoKitPrefetch:
    return PhotoKitPrefetch(_video_request, VIDEO_EXPORT_TIMEOUT)


def _medium_quality_video(photo, prefetch: PhotoKitPrefetch | None):
    try:
        av_asset = (prefetch or video_prefetch()).take(photo)
    except DownloadTimedOut:
        if photo.ismissing:
            raise VideoNotDownloaded(
                f"iCloud didn't send {photo.original_filename} within "
                f"{VIDEO_EXPORT_TIMEOUT}s; it is tried again next cycle"
            ) from None
        return None, None
    if av_asset is None or not hasattr(av_asset, "URL"):
        return None, None
    url = av_asset.URL()
    return (url.path() if url.isFileURL() else None), av_asset


def _is_file(path) -> bool:
    return bool(path) and Path(path).exists()


def _export_with_photos(photo, tmpdir) -> str | None:
    exported = photo.export(
        tmpdir, use_photos_export=True, timeout=VIDEO_EXPORT_TIMEOUT
    )
    if not exported and photo.ismissing:
        logger.warning(
            f"Photos export returned nothing for iCloud-only {photo.uuid}; "
            f"restarting Photos.app and retrying"
        )
        _restart_photos_app()
        exported = photo.export(
            tmpdir, use_photos_export=True, timeout=VIDEO_EXPORT_TIMEOUT
        )
    return exported[0] if exported else None


def _resolve_video_path(photo, tmpdir, prefetch: PhotoKitPrefetch | None = None):
    """Use Photos' 720p version of the video; otherwise export the original
    via Photos, falling back to the on-disk original.

    Photos.app's export pipeline sometimes returns a ~1 KB sidecar stub
    instead of the rendered video (observed for many iPhone HEVC .MOV files,
    and for every iCloud-only video whose original Photos didn't download).
    Validate the export produced a real video stream, otherwise fall back
    to ``photo.path``. The video only counts as having no video stream when
    the 720p version or the original was there and had none; when neither
    was there, it is tried again next cycle.
    """
    medium, av_asset = _medium_quality_video(photo, prefetch)
    if _is_file(medium) and _has_video_stream(medium):
        return medium, av_asset

    exported = _export_with_photos(photo, tmpdir)
    if exported and _has_video_stream(exported):
        return exported, None

    if exported:
        size = Path(exported).stat().st_size
        logger.warning(
            f"Photos export for {photo.uuid} produced unusable file "
            f"({size} bytes, no video stream); falling back to original"
        )

    if _is_file(photo.path) and _has_video_stream(photo.path):
        return photo.path, None

    if not _is_file(medium) and not _is_file(photo.path):
        raise VideoNotDownloaded(
            f"iCloud didn't send {photo.original_filename}: Photos gave no 720p "
            f"version and the original isn't on this Mac; it is tried again "
            f"next cycle"
        )
    raise RuntimeError(
        f"No usable video source for {photo.uuid} ({photo.original_filename}): "
        f"no video stream found in Photos export or original"
    )


def _get_video_duration(video_path, filename):
    """Get video duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            video_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            f"ffprobe failed for {filename}: "
            f"{result.stderr.strip() or 'no duration output'}"
        )
    try:
        duration = float(result.stdout.strip())
    except ValueError as err:
        raise RuntimeError(
            f"ffprobe returned invalid duration for {filename}: "
            f"{result.stdout.strip()!r}"
        ) from err
    logger.debug(f"Video duration: {duration:.1f}s")
    return duration


def _run_ffmpeg_extract(
    video_path, timestamp, frame_path, max_dimension, *, input_seek
):
    """Run a single ffmpeg frame-extraction attempt.

    ``input_seek=True`` places ``-ss`` before ``-i`` (fast, keyframe-only).
    ``input_seek=False`` places it after (decodes from start to timestamp;
    slower but works on short clips and legacy containers where input-seek
    skips past the only decodable keyframe).
    """
    args = ["ffmpeg", "-v", "error", "-y"]
    if timestamp > 0:
        if input_seek:
            args += ["-ss", str(timestamp), "-i", video_path]
        else:
            args += ["-i", video_path, "-ss", str(timestamp)]
    else:
        args += ["-i", video_path]
    args += [
        "-frames:v",
        "1",
        "-q:v",
        FFMPEG_QUALITY,
        # yuvj420p tags the output as full-range so the mjpeg encoder accepts
        # legacy sources (e.g. older Android .3gp) without -strict unofficial.
        "-pix_fmt",
        "yuvj420p",
        "-vf",
        f"scale='min({max_dimension},iw)':'min({max_dimension},ih)'"
        f":force_original_aspect_ratio=decrease",
        frame_path,
    ]
    result = subprocess.run(args, capture_output=True, text=True)
    return result, Path(frame_path).exists() and Path(frame_path).stat().st_size > 0


def _extract_frame(video_path, timestamp, frame_path, max_dimension):
    """Extract a single video frame at the given timestamp.

    Tries fast input-seek first, then falls back to output-seek for formats
    where input-seek lands past any decodable frame (legacy .3gp, very short
    clips).
    """
    logger.debug(f"Extracting frame at {timestamp:.2f}s...")
    result, ok = _run_ffmpeg_extract(
        video_path, timestamp, frame_path, max_dimension, input_seek=True
    )
    if ok:
        return True
    logger.debug(
        f"Input-seek failed at {timestamp:.2f}s "
        f"(rc={result.returncode}): {result.stderr.strip()[:200]}; "
        f"retrying with output-seek"
    )
    # Remove any zero-byte file the first attempt may have left behind.
    Path(frame_path).unlink(missing_ok=True)
    result, ok = _run_ffmpeg_extract(
        video_path, timestamp, frame_path, max_dimension, input_seek=False
    )
    if not ok and result.stderr.strip():
        logger.warning(
            f"Frame extraction failed at {timestamp:.2f}s "
            f"(rc={result.returncode}): {result.stderr.strip()[:200]}"
        )
    return ok


@dataclass(frozen=True)
class _Frame:
    b64: str
    size: int
    width: int
    height: int


def _capture_frame(video_path, ts, idx, max_dimension, tmpdir) -> _Frame | None:
    from PIL import Image

    frame_path = Path(tmpdir) / f"frame_{idx:02d}.jpg"
    if not _extract_frame(video_path, ts, str(frame_path), max_dimension):
        return None
    data = frame_path.read_bytes()
    with Image.open(frame_path) as img:
        width, height = img.size
    return _Frame(
        b64=base64.standard_b64encode(data).decode("utf-8"),
        size=len(data),
        width=width,
        height=height,
    )


def _extract_all_frames(video_path, num_frames, duration, max_dimension, tmpdir):
    """Extract evenly-spaced frames and return (base64_list, metadata_dict)."""
    if duration < SHORT_VIDEO_THRESHOLD_S:
        timestamps = [0.0]
    else:
        count = min(num_frames, int(duration / MIN_FRAME_SPACING_S))
        if count < num_frames:
            logger.debug(
                f"Capping to {count} frames for {duration:.1f}s video "
                f"(min spacing {MIN_FRAME_SPACING_S}s)"
            )
        timestamps = [duration * (i + 0.5) / count for i in range(count)]

    def capture(job):
        idx, ts = job
        frame = _capture_frame(video_path, ts, idx, max_dimension, tmpdir)
        if frame is None:
            logger.warning(f"Failed to extract frame {idx + 1}")
        return frame

    with ThreadPoolExecutor(max_workers=FRAME_WORKERS) as workers:
        captured = [f for f in workers.map(capture, enumerate(timestamps)) if f]

    # Last-resort: some legacy containers (e.g. old .3gp clips) only decode
    # frame zero. If every seeked attempt failed, grab the very first frame.
    if not captured and timestamps != [0.0]:
        logger.info("All seeked extractions failed; retrying at t=0")
        frame = _capture_frame(video_path, 0.0, len(timestamps), max_dimension, tmpdir)
        captured = [frame] if frame else []

    logger.debug(f"Extracted {len(captured)} frames")
    meta = {
        "image_size_bytes": sum(f.size for f in captured),
        "image_width": captured[0].width if captured else None,
        "image_height": captured[0].height if captured else None,
        "num_frames": len(captured),
    }
    return [f.b64 for f in captured], meta


@contextmanager
def exported_video(
    photo: osxphotos.PhotoInfo, prefetch: PhotoKitPrefetch | None = None
) -> Iterator[str]:
    logger.debug(f"Exporting video (missing={photo.ismissing})...")
    with objc.autorelease_pool(), tempfile.TemporaryDirectory() as tmpdir:
        video_path, _av_asset = _resolve_video_path(photo, tmpdir, prefetch)
        size_mb = Path(video_path).stat().st_size / (1024 * 1024)
        logger.debug(f"Using {video_path} ({size_mb:.1f} MB)")
        yield video_path


def video_frames_as_base64(
    video_path: str, filename: str, num_frames: int = 30, max_dimension: int = 1024
) -> tuple[list[str], dict]:
    """Extract frames at equal intervals.

    Returns (base64_list, metadata_dict).
    """
    duration = _get_video_duration(video_path, filename)
    with tempfile.TemporaryDirectory() as tmpdir:
        return _extract_all_frames(
            video_path, num_frames, duration, max_dimension, tmpdir
        )


def _decode_audio(video_path, filename) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            video_path,
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            str(AUDIO_SAMPLE_RATE),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-",
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        error = result.stderr.decode(errors="replace").strip()[:200]
        raise RuntimeError(f"Audio extraction failed for {filename}: {error}")
    return result.stdout


def video_audio(video_path: str, filename: str) -> bytes | None:
    if not _has_stream(video_path, "a:0"):
        return None
    return _decode_audio(video_path, filename)
