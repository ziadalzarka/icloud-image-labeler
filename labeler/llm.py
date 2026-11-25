"""OpenAI-compatible LLM client for photo and video labeling."""

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import NamedTuple

from openai import BadRequestError, OpenAI

logger = logging.getLogger(__name__)

LLM_TIMEOUT = 90.0  # seconds
LLM_MERGE_TIMEOUT = 600.0  # seconds
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

VIDEO_MERGE_SYSTEM_PROMPT = """\
You are a video labeling assistant. You will be given labels made from the \
frames of one video, either one set for the whole video or one set for each \
consecutive segment of it, in order. You may also be given a transcript of \
what is said in the video. Combine them into one set of labels for the whole \
video:
1. **keywords**: A list of descriptive keywords/tags covering the whole video
   (objects, scenes, activities, colors, mood, actions, and the topics, names
   and places that are clearly said). Keep the most relevant ones and drop
   duplicates and near-duplicates. 10-20 keywords.
2. **title**: A short descriptive title (5-10 words) for the whole video.
3. **description**: A one-sentence description of what happens across the
   whole video, including what people talk about when the transcript makes
   it clear.
4. **ocr_text**: All distinct visible text from the frame labels, without
   repeats (empty string if none).

The transcript comes from automatic speech recognition and is often wrong: \
it can be in the wrong language, garbled, repeat itself, or contain phrases \
that were never said, such as "thank you for watching". Use only the parts \
that make sense with the frame labels and ignore the rest. Write all labels \
in English, even when the transcript is in another language.

Respond ONLY with valid JSON in this exact format:
{
  "keywords": ["keyword1", "keyword2", ...],
  "title": "Short descriptive title",
  "description": "One sentence describing the video.",
  "ocr_text": "any visible text"
}"""

MAX_TRANSCRIPT_CHARS = 3000

CONTENT_FILTER_FINISH_REASON = "content_filter"
CONTENT_FILTER_ERROR = (
    "Blocked by the server's content filter, even when asked again without copied text"
)
WITHOUT_COPIED_TEXT_PROMPT = (
    "Your last answer was cut off by a content filter, most likely because it "
    "copied text word for word, such as song lyrics or a page of a book. Answer "
    'again with "ocr_text" set to an empty string, and don\'t quote that text in '
    "the keywords, title or description either."
)


class ContentFilteredError(RuntimeError):
    pass


class LabelResult(NamedTuple):
    labels: dict
    retries: int
    input_tokens: int
    output_tokens: int
    content_filtered: bool


def model_tag(model: str) -> str:
    """Opaque keyword identifying the model that processed a photo.

    Uses a short sha256 prefix so it won't surface in user keyword searches
    but still lets discovery detect model changes for reindexing.
    """
    return f"m:{hashlib.sha256(model.encode()).hexdigest()[:8]}"


def video_settings_tag(video_frames: int, video_frame_batch: int) -> str:
    settings = f"frames={video_frames},batch={video_frame_batch}"
    return f"v:{hashlib.sha256(settings.encode()).hexdigest()[:8]}"


def create_client(base_url: str, api_key: str = "") -> OpenAI:
    """Create an OpenAI client configured for the given endpoint."""
    return OpenAI(
        base_url=base_url, api_key=api_key or "not-needed", timeout=LLM_TIMEOUT
    )


@dataclass(frozen=True)
class Server:
    """One LLM backend: endpoint URL, model id, optional API key, and slot count."""

    base_url: str
    model: str
    api_key: str = ""
    threads: int = 1
    reasoning_effort: str = ""


_ACQUIRE_POLL = 0.05


class ServerPool:
    """Round-robin LLM server pool with per-server concurrency limits.

    Each server has its own semaphore sized to ``server.threads``. ``acquire``
    hands out the next server with a free slot in round-robin order and blocks
    if every server is saturated. Callers must ``release`` when done so the
    slot is returned to the pool. On retry, callers should release first so a
    crashed backend rotates away.
    """

    def __init__(self, servers: list[Server]):
        if not servers:
            raise ValueError("ServerPool requires at least one server")
        for s in servers:
            if s.threads < 1:
                raise ValueError(
                    f"Server {s.base_url} has threads={s.threads}; must be >= 1"
                )
        self._servers = list(servers)
        self._slots = [threading.Semaphore(s.threads) for s in self._servers]
        self._idx = 0
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._servers)

    @property
    def total_threads(self) -> int:
        return sum(s.threads for s in self._servers)

    def acquire(self) -> Server:
        """Block until any server has a free slot, then return that server."""
        while True:
            with self._lock:
                n = len(self._servers)
                for i in range(n):
                    j = (self._idx + i) % n
                    if self._slots[j].acquire(blocking=False):
                        self._idx = (j + 1) % n
                        return self._servers[j]
            time.sleep(_ACQUIRE_POLL)

    def release(self, server: Server) -> None:
        for i, s in enumerate(self._servers):
            if s is server:
                self._slots[i].release()
                return
        raise ValueError(f"Unknown server {server.base_url!r}")

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


def _usage_tokens(response) -> tuple[int, int]:
    """Extract (input_tokens, output_tokens) from an OpenAI response."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0
    return getattr(usage, "prompt_tokens", 0) or 0, getattr(
        usage, "completion_tokens", 0
    ) or 0


def _create_completion(
    client: OpenAI,
    model: str,
    messages: list,
    timeout: float,
    reasoning_effort: str | None,
):
    kwargs = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
    try:
        return client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=LLM_TEMPERATURE,
            timeout=timeout,
            **kwargs,
        )
    except BadRequestError as e:
        if not kwargs or "reasoning" not in str(e).lower():
            raise
        logger.debug(f"Server rejected reasoning_effort, retrying without it: {e}")
        return client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=LLM_TEMPERATURE,
            timeout=timeout,
        )


def _was_filtered(response) -> bool:
    return response.choices[0].finish_reason == CONTENT_FILTER_FINISH_REASON


def _request_labels(
    client: OpenAI,
    model: str,
    messages: list,
    timeout: float = LLM_TIMEOUT,
    reasoning_effort: str | None = None,
) -> LabelResult:
    """Send request to LLM and parse response.

    An answer cut off by the server's content filter is asked for again without
    copied text, and one that isn't valid JSON is asked for once more. Token
    counts are summed across every call. Raises ContentFilteredError when the
    content filter also cuts off the answer that was asked for again.
    """
    logger.debug(f"Sending to LM Studio ({model})...")
    response = _create_completion(client, model, messages, timeout, reasoning_effort)
    in_toks, out_toks = _usage_tokens(response)
    content_filtered = _was_filtered(response)
    if content_filtered:
        logger.warning(
            "Answer cut off by the content filter, asking again without copied text..."
        )
        messages = [*messages, {"role": "user", "content": WITHOUT_COPIED_TEXT_PROMPT}]
        response = _create_completion(
            client, model, messages, timeout, reasoning_effort
        )
        retry_in, retry_out = _usage_tokens(response)
        in_toks, out_toks = in_toks + retry_in, out_toks + retry_out
        if _was_filtered(response):
            raise ContentFilteredError(CONTENT_FILTER_ERROR)
    retries = int(content_filtered)
    raw = response.choices[0].message.content.strip()
    logger.debug(f"Received response ({len(raw)} chars)")

    try:
        return LabelResult(
            _parse_response(raw), retries, in_toks, out_toks, content_filtered
        )
    except (json.JSONDecodeError, IndexError):
        logger.warning("JSON parse failed, retrying with correction prompt...")
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {"role": "user", "content": "Please respond with valid JSON only."}
        )
        response = _create_completion(
            client, model, messages, timeout, reasoning_effort
        )
        retry_in, retry_out = _usage_tokens(response)
        if _was_filtered(response):
            raise ContentFilteredError(CONTENT_FILTER_ERROR) from None
        raw = response.choices[0].message.content.strip()
        labels = _parse_response(raw)
        logger.debug(f"Retry succeeded: {len(labels.get('keywords', []))} keywords")
        return LabelResult(
            labels,
            retries + 1,
            in_toks + retry_in,
            out_toks + retry_out,
            content_filtered,
        )


def label_photo(
    client: OpenAI,
    model: str,
    image_b64: str,
    filename: str,
    reasoning_effort: str | None = None,
) -> LabelResult:
    """Send a photo to the LLM for labeling."""
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
    result = _request_labels(client, model, messages, reasoning_effort=reasoning_effort)
    logger.debug(f"Parsed: {len(result.labels.get('keywords', []))} keywords")
    return result


def _video_messages(frames_b64: list[str], text: str) -> list[dict]:
    image_content = [{"type": "text", "text": text}]
    for frame_b64 in frames_b64:
        image_content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{frame_b64}"},
            }
        )
    return [
        {"role": "system", "content": VIDEO_SYSTEM_PROMPT},
        {"role": "user", "content": image_content},
    ]


def _merge_messages(segment_labels: list[dict], transcript: str) -> list[dict]:
    if len(segment_labels) == 1:
        content = (
            "Labels for the whole video:\n"
            f"{json.dumps(segment_labels[0], ensure_ascii=False)}"
        )
    else:
        segments = "\n".join(
            f"Segment {i}: {json.dumps(labels, ensure_ascii=False)}"
            for i, labels in enumerate(segment_labels, start=1)
        )
        content = (
            f"Labels for {len(segment_labels)} consecutive segments"
            f" of one video, in order:\n{segments}"
        )
    if transcript:
        content += (
            "\n\nTranscript of what is said in the video:\n"
            f"{transcript[:MAX_TRANSCRIPT_CHARS]}"
        )
    return [
        {"role": "system", "content": VIDEO_MERGE_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def _merge_labels(
    client: OpenAI,
    model: str,
    segment_labels: list[dict],
    transcript: str,
    reasoning_effort: str | None = None,
) -> LabelResult:
    return _request_labels(
        client,
        model,
        _merge_messages(segment_labels, transcript),
        timeout=LLM_MERGE_TIMEOUT,
        reasoning_effort=reasoning_effort or "none",
    )


def label_video(
    client: OpenAI,
    model: str,
    frames_b64: list[str],
    filename: str,
    batch_size: int = 0,
    transcript: str = "",
    *,
    reasoning_effort: str | None = None,
) -> LabelResult:
    """Send video frames to the LLM for labeling."""
    total = len(frames_b64)
    size = batch_size if batch_size > 0 else total
    logger.debug(f"Labeling video: {filename} ({total} frames, batch size {size})")

    segment_labels = []
    retries = in_toks = out_toks = 0
    content_filtered = False
    for start in range(0, total, size):
        batch = frames_b64[start : start + size]
        if len(batch) == total:
            text = (
                f"These are {total} frames extracted"
                f" at equal intervals from a video."
                f" Label this video:"
            )
        else:
            end = start + len(batch)
            logger.debug(f"Labeling frames {start + 1}-{end} of {total}...")
            text = (
                f"These are frames {start + 1}-{end} of {total},"
                f" extracted at equal intervals from a video."
                f" Label this part of the video:"
            )
        labels, r, i, o, f = _request_labels(
            client,
            model,
            _video_messages(batch, text),
            reasoning_effort=reasoning_effort,
        )
        segment_labels.append(labels)
        retries, in_toks, out_toks = retries + r, in_toks + i, out_toks + o
        content_filtered = content_filtered or f

    if len(segment_labels) == 1 and not transcript:
        labels = segment_labels[0]
    else:
        logger.debug(f"Merging labels from {len(segment_labels)} batches...")
        labels, r, i, o, f = _merge_labels(
            client, model, segment_labels, transcript, reasoning_effort
        )
        retries, in_toks, out_toks = retries + r, in_toks + i, out_toks + o
        content_filtered = content_filtered or f

    logger.debug(f"Parsed: {len(labels.get('keywords', []))} keywords")
    return LabelResult(labels, retries, in_toks, out_toks, content_filtered)


def add_transcript_to_labels(
    client: OpenAI,
    model: str,
    labels: dict,
    transcript: str,
    reasoning_effort: str | None = None,
) -> LabelResult:
    return _merge_labels(client, model, [labels], transcript, reasoning_effort)
