"""HEIC-to-JPEG photo conversion and video frame extraction."""

import base64
import logging
import subprocess
import tempfile
from pathlib import Path

import osxphotos

logger = logging.getLogger(__name__)

PHOTO_EXPORT_TIMEOUT = 30  # seconds
VIDEO_EXPORT_TIMEOUT = 300  # seconds
JPEG_QUALITY = 85
FFMPEG_QUALITY = "2"  # -q:v value for ffmpeg frame extraction
# Below this duration the clip is essentially a single frame; evenly-spaced
# seek timestamps cluster too close to t=0 to land on a decodable keyframe.
SHORT_VIDEO_THRESHOLD_S = 0.5


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
    photo: osxphotos.PhotoInfo, max_dimension: int = 1024
) -> tuple[str, dict]:
    """Export photo as JPEG and return (base64_string, metadata_dict)."""
    logger.debug(f"Exporting photo (missing={photo.ismissing})...")
    with tempfile.TemporaryDirectory() as tmpdir:
        export_path = _resolve_export_path(photo, tmpdir)
        img = _open_or_fallback(photo, export_path, tmpdir)
        return _encode_as_jpeg(img, max_dimension, tmpdir)


def _has_video_stream(path: str) -> bool:
    """Return True if ffprobe finds at least one decodable video stream."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
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


def _resolve_video_path(photo, tmpdir):
    """Export video via Photos; fall back to the on-disk original.

    Photos.app's export pipeline sometimes returns a ~1 KB sidecar stub
    instead of the rendered video (observed for many iPhone HEVC .MOV files).
    Validate the export produced a real video stream, otherwise fall back
    to ``photo.path``.
    """
    exported = photo.export(
        tmpdir, use_photos_export=True, timeout=VIDEO_EXPORT_TIMEOUT
    )
    if exported and _has_video_stream(exported[0]):
        return exported[0]

    if exported:
        size = Path(exported[0]).stat().st_size
        logger.warning(
            f"Photos export for {photo.uuid} produced unusable file "
            f"({size} bytes, no video stream); falling back to original"
        )

    if photo.path and Path(photo.path).exists() and _has_video_stream(photo.path):
        return photo.path

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


def _run_ffmpeg_extract(video_path, timestamp, frame_path, max_dimension, *, input_seek):
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


def _extract_all_frames(video_path, num_frames, duration, max_dimension, tmpdir):
    """Extract evenly-spaced frames and return (base64_list, metadata_dict)."""
    frames = []
    total_frame_bytes = 0
    frame_width = None
    frame_height = None

    if duration < SHORT_VIDEO_THRESHOLD_S:
        timestamps = [0.0]
    else:
        timestamps = [duration * (i + 0.5) / num_frames for i in range(num_frames)]

    def _try_capture(ts, idx):
        nonlocal total_frame_bytes, frame_width, frame_height
        frame_path = str(Path(tmpdir) / f"frame_{idx:02d}.jpg")
        if not _extract_frame(video_path, ts, frame_path, max_dimension):
            return False
        frame_size = Path(frame_path).stat().st_size
        total_frame_bytes += frame_size
        if frame_width is None:
            from PIL import Image

            with Image.open(frame_path) as img:
                frame_width, frame_height = img.size
        with Path(frame_path).open("rb") as f:
            frames.append(base64.standard_b64encode(f.read()).decode("utf-8"))
        return True

    for i, timestamp in enumerate(timestamps):
        logger.debug(
            f"Extracting frame {i + 1}/{len(timestamps)} at {timestamp:.2f}s..."
        )
        if not _try_capture(timestamp, i):
            logger.warning(f"Failed to extract frame {i + 1}")

    # Last-resort: some legacy containers (e.g. old .3gp clips) only decode
    # frame zero. If every seeked attempt failed, grab the very first frame.
    if not frames and timestamps != [0.0]:
        logger.info("All seeked extractions failed; retrying at t=0")
        _try_capture(0.0, len(timestamps))

    logger.debug(f"Extracted {len(frames)} frames")
    meta = {
        "image_size_bytes": total_frame_bytes,
        "image_width": frame_width,
        "image_height": frame_height,
        "num_frames": len(frames),
    }
    return frames, meta


def export_video_frames_as_base64(
    photo: osxphotos.PhotoInfo, num_frames: int = 5, max_dimension: int = 1024
) -> tuple[list[str], dict]:
    """Export video, extract frames at equal intervals.

    Returns (base64_list, metadata_dict).
    """
    logger.debug(f"Exporting video (missing={photo.ismissing})...")
    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = _resolve_video_path(photo, tmpdir)
        size_mb = Path(video_path).stat().st_size / (1024 * 1024)
        logger.debug(f"Using {video_path} ({size_mb:.1f} MB)")
        duration = _get_video_duration(video_path, photo.original_filename)
        return _extract_all_frames(
            video_path, num_frames, duration, max_dimension, tmpdir
        )
