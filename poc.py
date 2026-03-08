"""
POC: iCloud Photos Auto-Labeler
Reads photos from Photos.app, sends to LM Studio for labeling, writes keywords back.
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta

import osxphotos
import photoscript
from openai import OpenAI

LM_STUDIO_BASE_URL = "http://devbox.local:1234/v1"
LM_STUDIO_MODEL = "qwen/qwen3.5-9b"

PHOTO_SYSTEM_PROMPT = """You are a photo labeling assistant. Given a photo, generate:
1. **keywords**: A list of descriptive keywords/tags (objects, scenes, activities, colors, mood). 10-20 keywords.
2. **title**: A short descriptive title (5-10 words).
3. **description**: A one-sentence description of the photo.
4. **ocr_text**: Any visible text in the photo (empty string if none).

Respond ONLY with valid JSON in this exact format:
{
  "keywords": ["keyword1", "keyword2", ...],
  "title": "Short descriptive title",
  "description": "One sentence describing the photo.",
  "ocr_text": "any visible text"
}"""

VIDEO_SYSTEM_PROMPT = """You are a video labeling assistant. You will be given frames extracted at equal intervals from a video. Analyze all frames together to understand the video content, then generate:
1. **keywords**: A list of descriptive keywords/tags (objects, scenes, activities, colors, mood, actions). 10-20 keywords.
2. **title**: A short descriptive title (5-10 words).
3. **description**: A one-sentence description of what happens in the video.
4. **ocr_text**: Any visible text in the video frames (empty string if none).

Respond ONLY with valid JSON in this exact format:
{
  "keywords": ["keyword1", "keyword2", ...],
  "title": "Short descriptive title",
  "description": "One sentence describing the video.",
  "ocr_text": "any visible text"
}"""


def get_unprocessed_photos(limit: int = 1, days_back: int = 7, media_type: str = "all") -> list[osxphotos.PhotoInfo]:
    """Find recent photos/videos that don't have keywords yet."""
    print("Loading Photos library...")
    photosdb = osxphotos.PhotosDB()
    from_date = datetime.now() - timedelta(days=days_back)
    print(f"Querying photos from the last {days_back} days (since {from_date.strftime('%Y-%m-%d')})...")
    recent = photosdb.photos(from_date=from_date)
    print(f"Found {len(recent)} photos in date range")
    print("Filtering for unprocessed media (no keywords, not hidden)...")
    photos = [p for p in recent if not p.keywords and not p.hidden]
    if media_type == "photo":
        print("Filtering for photos only...")
        photos = [p for p in photos if p.isphoto]
    elif media_type == "video":
        print("Filtering for videos only...")
        photos = [p for p in photos if not p.isphoto]
    missing_count = sum(1 for p in photos if p.ismissing)
    photo_count = sum(1 for p in photos if p.isphoto)
    video_count = sum(1 for p in photos if not p.isphoto)
    print(f"Found {len(photos)} unprocessed items ({photo_count} photos, {video_count} videos, {missing_count} not yet downloaded from iCloud)")
    photos.sort(key=lambda p: p.date_added or p.date, reverse=True)
    selected = photos[:limit]
    if selected:
        print(f"Selected {len(selected)} most recent photo(s): {selected[0].original_filename} (added: {selected[0].date_added})")
    return selected


MAX_DIMENSION = 1024


def resize_if_needed(img, max_dim: int = 1024):
    """Resize image so the longest side is at most max_dim pixels."""
    w, h = img.size
    if max(w, h) <= max_dim:
        return img
    scale = max_dim / max(w, h)
    new_w, new_h = int(w * scale), int(h * scale)
    print(f"  Resizing {w}x{h} -> {new_w}x{new_h}")
    return img.resize((new_w, new_h), img.Resampling.LANCZOS if hasattr(img, 'Resampling') else 1)


def photo_to_base64(photo: osxphotos.PhotoInfo, max_dim: int = MAX_DIMENSION) -> str:
    """Export photo as JPEG and encode as base64."""
    from PIL import Image
    import pillow_heif
    pillow_heif.register_heif_opener()

    print(f"  Exporting photo to temp directory (missing={photo.ismissing})...")
    with tempfile.TemporaryDirectory() as tmpdir:
        if photo.ismissing:
            print(f"  Photo not downloaded locally, requesting from Photos.app...")
        exported = photo.export(tmpdir, use_photos_export=True, timeout=120)
        if not exported:
            raise RuntimeError(f"Failed to export photo {photo.uuid} — file may not be synced to iCloud yet")
        export_path = exported[0]
        size_mb = os.path.getsize(export_path) / (1024 * 1024)
        print(f"  Exported to {export_path} ({size_mb:.1f} MB)")

        # Convert to JPEG if not already
        jpeg_path = os.path.join(tmpdir, "photo.jpg")
        print(f"  Converting to JPEG...")
        img = Image.open(export_path)
        img = img.convert("RGB")
        img = resize_if_needed(img, max_dim=max_dim)
        img.save(jpeg_path, "JPEG", quality=85)
        jpeg_mb = os.path.getsize(jpeg_path) / (1024 * 1024)
        print(f"  JPEG: {img.size[0]}x{img.size[1]} ({jpeg_mb:.1f} MB)")

        print(f"  Encoding to base64...")
        with open(jpeg_path, "rb") as f:
            b64 = base64.standard_b64encode(f.read()).decode("utf-8")
        print(f"  Base64 encoded ({len(b64)} chars)")
        return b64


def video_to_base64_frames(photo: osxphotos.PhotoInfo, num_frames: int = 5, max_dim: int = MAX_DIMENSION) -> list[str]:
    """Export video, extract frames at equal intervals, return as base64 JPEGs."""
    print(f"  Exporting video to temp directory (missing={photo.ismissing})...")
    with tempfile.TemporaryDirectory() as tmpdir:
        if photo.ismissing:
            print(f"  Video not downloaded locally, requesting from Photos.app...")
        exported = photo.export(tmpdir, use_photos_export=True, timeout=300)
        if not exported:
            raise RuntimeError(f"Failed to export video {photo.uuid} — file may not be synced to iCloud yet")
        video_path = exported[0]
        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        print(f"  Exported to {video_path} ({size_mb:.1f} MB)")

        # Get video duration
        print(f"  Getting video duration...")
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True
        )
        duration = float(result.stdout.strip())
        print(f"  Video duration: {duration:.1f}s")

        # Extract frames at equal intervals
        frames = []
        for i in range(num_frames):
            timestamp = duration * (i + 0.5) / num_frames
            frame_path = os.path.join(tmpdir, f"frame_{i:02d}.jpg")
            print(f"  Extracting frame {i+1}/{num_frames} at {timestamp:.1f}s...")
            subprocess.run(
                ["ffmpeg", "-v", "quiet", "-ss", str(timestamp), "-i", video_path,
                 "-frames:v", "1", "-q:v", "2",
                 "-vf", f"scale='min({max_dim},iw)':'min({max_dim},ih)':force_original_aspect_ratio=decrease",
                 frame_path],
                capture_output=True
            )
            if os.path.exists(frame_path):
                with open(frame_path, "rb") as f:
                    frames.append(base64.standard_b64encode(f.read()).decode("utf-8"))
            else:
                print(f"  WARNING: Failed to extract frame {i+1}")

        print(f"  Extracted {len(frames)} frames")
        return frames


def label_photo(client: OpenAI, image_b64: str, filename: str) -> dict:
    """Send photo to LM Studio for labeling."""
    print(f"  Sending {filename} to LM Studio ({LM_STUDIO_MODEL})...")
    print(f"  Waiting for LLM response...")
    response = client.chat.completions.create(
        model=LM_STUDIO_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Label this photo:"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                ],
            },
        ],
        temperature=0.3,
    )
    raw = response.choices[0].message.content.strip()
    print(f"  Received response ({len(raw)} chars)")
    # Strip <think>...</think> blocks (Qwen thinking mode)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    print(f"  Raw response: {raw[:200]}{'...' if len(raw) > 200 else ''}")
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]
    print(f"  Parsing JSON response...")
    labels = json.loads(raw)
    print(f"  Parsed successfully: {len(labels.get('keywords', []))} keywords")
    return labels


def label_video(client: OpenAI, frames_b64: list[str], filename: str) -> dict:
    """Send video frames to LM Studio for labeling."""
    print(f"  Sending {len(frames_b64)} frames of {filename} to LM Studio ({LM_STUDIO_MODEL})...")
    print(f"  Waiting for LLM response...")

    image_content = [{"type": "text", "text": f"These are {len(frames_b64)} frames extracted at equal intervals from a video. Label this video:"}]
    for i, frame_b64 in enumerate(frames_b64):
        image_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{frame_b64}"},
        })

    response = client.chat.completions.create(
        model=LM_STUDIO_MODEL,
        messages=[
            {"role": "system", "content": VIDEO_SYSTEM_PROMPT},
            {"role": "user", "content": image_content},
        ],
        temperature=0.3,
    )
    raw = response.choices[0].message.content.strip()
    print(f"  Received response ({len(raw)} chars)")
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    print(f"  Raw response: {raw[:200]}{'...' if len(raw) > 200 else ''}")
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]
    print(f"  Parsing JSON response...")
    labels = json.loads(raw)
    print(f"  Parsed successfully: {len(labels.get('keywords', []))} keywords")
    return labels


def write_metadata(photo_uuid: str, labels: dict, dry_run: bool = True):
    """Write keywords, title, and description back to Photos.app."""
    if dry_run:
        description = labels.get("description", "")
        if labels.get("ocr_text"):
            description = f"{description}\n\nOCR: {labels['ocr_text']}"
        print(f"  [DRY RUN] Would write:")
        print(f"    Title: {labels.get('title', '')}")
        print(f"    Description: {description}")
        print(f"    Keywords: {', '.join(labels.get('keywords', []))}")
        return

    print(f"  Opening photo in Photos.app via PhotoScript...")
    photo = photoscript.Photo(photo_uuid)
    keywords = labels.get("keywords", [])

    description = labels.get("description", "")
    if labels.get("ocr_text"):
        description = f"{description}\n\nOCR: {labels['ocr_text']}"

    print(f"  Writing {len(keywords)} keywords...")
    photo.keywords = keywords
    print(f"  Writing title: {labels.get('title', '')}")
    photo.title = labels.get("title", "")
    print(f"  Writing description: {description[:100]}{'...' if len(description) > 100 else ''}")
    photo.description = description
    print(f"  Done writing metadata to Photos.app")


def main():
    parser = argparse.ArgumentParser(description="POC: Auto-label iCloud Photos with local LLM")
    parser.add_argument("--limit", type=int, default=1, help="Number of photos to process")
    parser.add_argument("--days", type=int, default=7, help="Look back N days for photos (default: 7)")
    parser.add_argument("--video", action="store_true", help="Process videos only")
    parser.add_argument("--photo", action="store_true", help="Process photos only")
    parser.add_argument("--write", action="store_true", help="Actually write to Photos (default: dry run)")
    parser.add_argument("--base-url", default=LM_STUDIO_BASE_URL, help="LM Studio API base URL")
    parser.add_argument("--model", default=LM_STUDIO_MODEL, help="Model name in LM Studio")
    parser.add_argument("--max-dim", type=int, default=MAX_DIMENSION, help="Max image dimension in pixels (default: 1024)")
    args = parser.parse_args()

    max_dim = args.max_dim

    dry_run = not args.write
    if dry_run:
        print("Running in DRY RUN mode (use --write to actually write metadata)\n")

    print(f"Connecting to LM Studio at {args.base_url} (model: {args.model})")
    client = OpenAI(base_url=args.base_url, api_key="not-needed")

    media_type = "video" if args.video else ("photo" if args.photo else "all")
    photos = get_unprocessed_photos(limit=args.limit, days_back=args.days, media_type=media_type)
    if not photos:
        print("No unprocessed photos found.")
        return

    for i, photo in enumerate(photos, 1):
        media_type = "photo" if photo.isphoto else "video"
        print(f"\n[{i}/{len(photos)}] Processing {media_type}: {photo.original_filename} ({photo.uuid[:8]}...) taken={photo.date} added={photo.date_added}")
        try:
            if photo.isphoto:
                image_b64 = photo_to_base64(photo, max_dim=max_dim)
                labels = label_photo(client, image_b64, photo.original_filename)
            else:
                frames_b64 = video_to_base64_frames(photo, max_dim=max_dim)
                labels = label_video(client, frames_b64, photo.original_filename)
            write_metadata(photo.uuid, labels, dry_run=dry_run)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

    print(f"\nDone! Processed {len(photos)} photos.")


if __name__ == "__main__":
    main()
