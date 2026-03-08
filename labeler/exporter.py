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
    logger.info(f"  Resizing {w}x{h} -> {new_w}x{new_h}")
    return img.resize((new_w, new_h), img.Resampling.LANCZOS if hasattr(img, 'Resampling') else 1)


def export_photo_as_base64(photo: osxphotos.PhotoInfo, max_dimension: int = 1024) -> str:
    """Export photo as JPEG and return base64-encoded string."""
    from PIL import Image
    import pillow_heif
    pillow_heif.register_heif_opener()

    logger.info(f"  Exporting photo (missing={photo.ismissing})...")
    with tempfile.TemporaryDirectory() as tmpdir:
        exported = photo.export(tmpdir, use_photos_export=True, timeout=120)
        if not exported:
            raise RuntimeError(f"Failed to export photo {photo.uuid}")
        export_path = exported[0]
        size_mb = os.path.getsize(export_path) / (1024 * 1024)
        logger.info(f"  Exported {export_path} ({size_mb:.1f} MB)")

        jpeg_path = os.path.join(tmpdir, "photo.jpg")
        img = Image.open(export_path)
        img = img.convert("RGB")
        img = _resize_if_needed(img, max_dimension)
        img.save(jpeg_path, "JPEG", quality=85)
        jpeg_mb = os.path.getsize(jpeg_path) / (1024 * 1024)
        logger.info(f"  JPEG: {img.size[0]}x{img.size[1]} ({jpeg_mb:.1f} MB)")

        with open(jpeg_path, "rb") as f:
            b64 = base64.standard_b64encode(f.read()).decode("utf-8")
        logger.info(f"  Base64 encoded ({len(b64)} chars)")
        return b64


def export_video_frames_as_base64(
    photo: osxphotos.PhotoInfo, num_frames: int = 5, max_dimension: int = 1024
) -> list[str]:
    """Export video, extract frames at equal intervals, return as base64 JPEGs."""
    logger.info(f"  Exporting video (missing={photo.ismissing})...")
    with tempfile.TemporaryDirectory() as tmpdir:
        exported = photo.export(tmpdir, use_photos_export=True, timeout=300)
        if not exported:
            raise RuntimeError(f"Failed to export video {photo.uuid}")
        video_path = exported[0]
        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        logger.info(f"  Exported {video_path} ({size_mb:.1f} MB)")

        # Get duration
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True,
        )
        duration = float(result.stdout.strip())
        logger.info(f"  Video duration: {duration:.1f}s")

        frames = []
        for i in range(num_frames):
            timestamp = duration * (i + 0.5) / num_frames
            frame_path = os.path.join(tmpdir, f"frame_{i:02d}.jpg")
            logger.info(f"  Extracting frame {i+1}/{num_frames} at {timestamp:.1f}s...")
            subprocess.run(
                ["ffmpeg", "-v", "quiet", "-ss", str(timestamp), "-i", video_path,
                 "-frames:v", "1", "-q:v", "2",
                 "-vf", f"scale='min({max_dimension},iw)':'min({max_dimension},ih)':force_original_aspect_ratio=decrease",
                 frame_path],
                capture_output=True,
            )
            if os.path.exists(frame_path):
                with open(frame_path, "rb") as f:
                    frames.append(base64.standard_b64encode(f.read()).decode("utf-8"))
            else:
                logger.warning(f"  Failed to extract frame {i+1}")

        logger.info(f"  Extracted {len(frames)} frames")
        return frames
