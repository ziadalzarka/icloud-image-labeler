import base64
import logging
import os
import subprocess
import tempfile

import osxphotos

logger = logging.getLogger(__name__)

def _resize_if_needed(img, max_dim: int):
    """Resize image so the longest side is at most max_dim pixels, maintaining aspect ratio."""
    w, h = img.size
    if max(w, h) <= max_dim:
        return img
    scale = max_dim / max(w, h)
    new_w, new_h = int(w * scale), int(h * scale)
    logger.debug(f"Resizing {w}x{h} -> {new_w}x{new_h}")
    return img.resize((new_w, new_h), img.Resampling.LANCZOS if hasattr(img, 'Resampling') else 1)


def _open_image(path: str, tmpdir: str):
    """Open an image file with PIL, falling back to sips for unsupported formats."""
    from PIL import Image
    import pillow_heif
    pillow_heif.register_heif_opener()

    try:
        return Image.open(path)
    except Exception:
        logger.debug(f"PIL cannot open {path}, converting via sips...")
        sips_jpg = os.path.join(tmpdir, "sips_converted.jpg")
        result = subprocess.run(
            ["sips", "-s", "format", "jpeg", path, "--out", sips_jpg],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not os.path.exists(sips_jpg):
            raise RuntimeError(
                f"sips conversion failed for {os.path.basename(path)}: "
                f"{result.stderr.strip()}"
            )
        return Image.open(sips_jpg)


def export_photo_as_base64(photo: osxphotos.PhotoInfo, max_dimension: int = 1024) -> tuple[str, dict]:
    """Export photo as JPEG and return (base64_string, metadata_dict)."""
    logger.debug(f"Exporting photo (missing={photo.ismissing})...")
    with tempfile.TemporaryDirectory() as tmpdir:
        exported = photo.export(tmpdir, use_photos_export=True, timeout=30)
        if exported:
            export_path = exported[0]
        elif photo.path and os.path.exists(photo.path):
            logger.warning(f"Photos export failed for {photo.uuid}, falling back to original at {photo.path}")
            export_path = photo.path
        else:
            raise RuntimeError(f"Failed to export photo {photo.uuid}")
        size_mb = os.path.getsize(export_path) / (1024 * 1024)
        logger.debug(f"Exported {export_path} ({size_mb:.1f} MB)")

        img = _open_image(export_path, tmpdir)
        img = img.convert("RGB")
        img = _resize_if_needed(img, max_dimension)
        jpeg_path = os.path.join(tmpdir, "photo.jpg")
        img.save(jpeg_path, "JPEG", quality=85)
        jpeg_size = os.path.getsize(jpeg_path)
        jpeg_mb = jpeg_size / (1024 * 1024)
        logger.debug(f"JPEG: {img.size[0]}x{img.size[1]} ({jpeg_mb:.1f} MB)")

        with open(jpeg_path, "rb") as f:
            b64 = base64.standard_b64encode(f.read()).decode("utf-8")
        logger.debug(f"Base64 encoded ({len(b64)} chars)")
        meta = {
            "image_size_bytes": jpeg_size,
            "image_width": img.size[0],
            "image_height": img.size[1],
        }
        return b64, meta


def export_video_frames_as_base64(
    photo: osxphotos.PhotoInfo, num_frames: int = 5, max_dimension: int = 1024
) -> tuple[list[str], dict]:
    """Export video, extract frames at equal intervals, return (base64_list, metadata_dict)."""
    logger.debug(f"Exporting video (missing={photo.ismissing})...")
    with tempfile.TemporaryDirectory() as tmpdir:
        exported = photo.export(tmpdir, use_photos_export=True, timeout=300)
        if not exported:
            raise RuntimeError(f"Failed to export video {photo.uuid}")
        video_path = exported[0]
        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        logger.debug(f"Exported {video_path} ({size_mb:.1f} MB)")

        # Get duration
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(
                f"ffprobe failed for {photo.original_filename}: "
                f"{result.stderr.strip() or 'no duration output'}"
            )
        try:
            duration = float(result.stdout.strip())
        except ValueError:
            raise RuntimeError(
                f"ffprobe returned invalid duration for {photo.original_filename}: "
                f"{result.stdout.strip()!r}"
            )
        logger.debug(f"Video duration: {duration:.1f}s")

        frames = []
        total_frame_bytes = 0
        frame_width = None
        frame_height = None
        for i in range(num_frames):
            timestamp = duration * (i + 0.5) / num_frames
            frame_path = os.path.join(tmpdir, f"frame_{i:02d}.jpg")
            logger.debug(f"Extracting frame {i+1}/{num_frames} at {timestamp:.1f}s...")
            subprocess.run(
                ["ffmpeg", "-v", "quiet", "-ss", str(timestamp), "-i", video_path,
                 "-frames:v", "1", "-q:v", "2",
                 "-vf", f"scale='min({max_dimension},iw)':'min({max_dimension},ih)':force_original_aspect_ratio=decrease",
                 frame_path],
                capture_output=True,
            )
            if os.path.exists(frame_path):
                frame_size = os.path.getsize(frame_path)
                total_frame_bytes += frame_size
                if frame_width is None:
                    from PIL import Image
                    with Image.open(frame_path) as img:
                        frame_width, frame_height = img.size
                with open(frame_path, "rb") as f:
                    frames.append(base64.standard_b64encode(f.read()).decode("utf-8"))
            else:
                logger.warning(f"Failed to extract frame {i+1}")

        logger.debug(f"Extracted {len(frames)} frames")
        meta = {
            "image_size_bytes": total_frame_bytes,
            "image_width": frame_width,
            "image_height": frame_height,
            "num_frames": len(frames),
        }
        return frames, meta
