"""OpenAI-compatible LLM client for photo and video labeling."""

import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass

from openai import OpenAI

logger = logging.getLogger(__name__)

LLM_TIMEOUT = 90.0  # seconds
LLM_TEMPERATURE = 0.3

PHOTO_SYSTEM_PROMPT = """\
You are a photo labeling assistant. Given a photo, generate:
1. **keywords**: A list of descriptive keywords/tags
   (objects, scenes, activities, colors, mood). 10-20 keywords.
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

VIDEO_SYSTEM_PROMPT = """\
You are a video labeling assistant. You will be given frames \
extracted at equal intervals from a video. Analyze all frames \
together to understand the video content, then generate:
1. **keywords**: A list of descriptive keywords/tags
   (objects, scenes, activities, colors, mood, actions). 10-20 keywords.
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


def model_tag(model: str) -> str:
    """Opaque keyword identifying the model that processed a photo.

    Uses a short sha256 prefix so it won't surface in user keyword searches
    but still lets discovery detect model changes for reindexing.
    """
    return f"m:{hashlib.sha256(model.encode()).hexdigest()[:8]}"


def create_client(base_url: str, api_key: str = "") -> OpenAI:
    """Create an OpenAI client configured for the given endpoint."""
    return OpenAI(
        base_url=base_url, api_key=api_key or "not-needed", timeout=LLM_TIMEOUT
    )


@dataclass(frozen=True)
class Server:
    """One LLM backend: endpoint URL, model id, and optional API key."""

    base_url: str
    model: str
    api_key: str = ""


class ServerPool:
    """Thread-safe round-robin pool of LLM servers.

    Each call to `next()` hands out the following server in round-robin
    order, so crashed servers get rotated away on retry.
    """

    def __init__(self, servers: list[Server]):
        if not servers:
            raise ValueError("ServerPool requires at least one server")
        self._servers = list(servers)
        self._idx = 0
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._servers)

    def next(self) -> Server:
        with self._lock:
            server = self._servers[self._idx % len(self._servers)]
            self._idx += 1
            return server

    def servers(self) -> list[Server]:
        return list(self._servers)

    def models(self) -> list[str]:
        """Distinct model ids across the pool, in first-seen order."""
        seen: dict[str, None] = {}
        for s in self._servers:
            seen.setdefault(s.model, None)
        return list(seen.keys())

    def model_tags(self) -> set[str]:
        """All model tags any server in the pool would stamp."""
        return {model_tag(m) for m in self.models()}


_THINK_TAG_RE = re.compile(
    r"<\|?channel\|?>.*?<\|?/?channel\|?>"
    r"|<think>.*?</think>"
    r"|<start_of_turn>.*?<end_of_turn>",
    re.DOTALL,
)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _parse_response(raw: str) -> dict:
    """Strip thinking blocks, code fences, and parse JSON."""
    cleaned = _THINK_TAG_RE.sub("", raw).strip()
    fence = _FENCE_RE.search(cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    return json.loads(cleaned)


def _request_labels(client: OpenAI, model: str, messages: list) -> tuple[dict, int]:
    """Send request to LLM and parse response, with one retry on JSON failure.

    Returns (labels_dict, retry_count).
    """
    logger.debug(f"Sending to LM Studio ({model})...")
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=LLM_TEMPERATURE,
    )
    raw = response.choices[0].message.content.strip()
    logger.debug(f"Received response ({len(raw)} chars)")

    try:
        return _parse_response(raw), 0
    except (json.JSONDecodeError, IndexError):
        logger.warning("JSON parse failed, retrying with correction prompt...")
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {"role": "user", "content": "Please respond with valid JSON only."}
        )
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=LLM_TEMPERATURE,
        )
        raw = response.choices[0].message.content.strip()
        labels = _parse_response(raw)
        logger.debug(f"Retry succeeded: {len(labels.get('keywords', []))} keywords")
        return labels, 1


def label_photo(
    client: OpenAI, model: str, image_b64: str, filename: str
) -> tuple[dict, int]:
    """Send a photo to the LLM for labeling. Returns (labels, retries)."""
    logger.debug(f"Labeling photo: {filename}")
    messages = [
        {"role": "system", "content": PHOTO_SYSTEM_PROMPT},
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
    ]
    labels, retries = _request_labels(client, model, messages)
    logger.debug(f"Parsed: {len(labels.get('keywords', []))} keywords")
    return labels, retries


def label_video(
    client: OpenAI, model: str, frames_b64: list[str], filename: str
) -> tuple[dict, int]:
    """Send video frames to the LLM for labeling. Returns (labels, retries)."""
    logger.debug(f"Labeling video: {filename} ({len(frames_b64)} frames)")
    image_content = [
        {
            "type": "text",
            "text": (
                f"These are {len(frames_b64)} frames extracted"
                f" at equal intervals from a video."
                f" Label this video:"
            ),
        }
    ]
    for frame_b64 in frames_b64:
        image_content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{frame_b64}"},
            }
        )

    messages = [
        {"role": "system", "content": VIDEO_SYSTEM_PROMPT},
        {"role": "user", "content": image_content},
    ]
    labels, retries = _request_labels(client, model, messages)
    logger.debug(f"Parsed: {len(labels.get('keywords', []))} keywords")
    return labels, retries
