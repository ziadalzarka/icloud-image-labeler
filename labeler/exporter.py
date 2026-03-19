import base64
import logging
import subprocess
import tempfile
from pathlib import Path

import osxphotos

logger = logging.getLogger(__name__)


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
    exported = photo.export(tmpdir, use_photos_export=True, timeout=30)
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
    img.save(jpeg_path, "JPEG", quality=85)
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


def _get_video_duration(video_path, filename):
    """Get video duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
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


def _extract_frame(video_path, timestamp, frame_path, max_dimension):
    """Extract a single video frame at the given timestamp."""
    logger.debug(f"Extracting frame at {timestamp:.1f}s...")
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "quiet",
            "-ss",
            str(timestamp),
            "-i",
            video_path,
            "-frames:v",
            "1",
            "-q:v",
            "2",
            "-vf",
            f"scale='min({max_dimension},iw)':'min({max_dimension},ih)'"
            f":force_original_aspect_ratio=decrease",
            frame_path,
        ],
        capture_output=True,
    )
    return Path(frame_path).exists()


def _extract_all_frames(video_path, num_frames, duration, max_dimension, tmpdir):
    """Extract evenly-spaced frames and return (base64_list, metadata_dict)."""
    frames = []
    total_frame_bytes = 0
    frame_width = None
    frame_height = None

    for i in range(num_frames):
        timestamp = duration * (i + 0.5) / num_frames
        frame_path = str(Path(tmpdir) / f"frame_{i:02d}.jpg")
        logger.debug(f"Extracting frame {i + 1}/{num_frames} at {timestamp:.1f}s...")

        if not _extract_frame(video_path, timestamp, frame_path, max_dimension):
            logger.warning(f"Failed to extract frame {i + 1}")
            continue

        frame_size = Path(frame_path).stat().st_size
        total_frame_bytes += frame_size
        if frame_width is None:
            from PIL import Image

            with Image.open(frame_path) as img:
                frame_width, frame_height = img.size
        with Path(frame_path).open("rb") as f:
            frames.append(base64.standard_b64encode(f.read()).decode("utf-8"))

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
        exported = photo.export(tmpdir, use_photos_export=True, timeout=300)
        if not exported:
            raise RuntimeError(f"Failed to export video {photo.uuid}")
        video_path = exported[0]
        size_mb = Path(video_path).stat().st_size / (1024 * 1024)
        logger.debug(f"Exported {video_path} ({size_mb:.1f} MB)")
        duration = _get_video_duration(video_path, photo.original_filename)
        return _extract_all_frames(
            video_path, num_frames, duration, max_dimension, tmpdir
        )
