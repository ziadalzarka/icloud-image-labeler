import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from labeler import config, library, metrics

TAIL_BYTES = 2_000_000
STALE_IN_FLIGHT_S = 3600
SPARK = "▁▂▃▄▅▆▇█"
BAR_WIDTH = 24
SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24
MEDIA_TYPES = ("photo", "video", "transcript")

LOG_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) \w+\s+\[[^\]]+\] (.*)$")
LABELING = re.compile(
    r"^\[(?P<server>[^\]]+)\] (?P<action>Labeling|Adding transcript to labels)"
    r"(?: (?P<kind>photo|video))?: (?P<name>.+?)(?: \(\d+ frames[^)]*\))?$"
)
FINISHED = re.compile(
    r"^\[(?P<done>\d+)/(?P<total>\d+)\] (?:Done|Failed|Export failed): "
    r"(?P<name>.+?)(?: \(added \S+\)|: .*)?$"
)
TRANSCRIPT_FINISHED = re.compile(
    r"^\[transcript \d+/\d+\] (?:Done|Failed): (?P<name>.+?)(?:: .*)?$"
)
PROCESSING = re.compile(r"^Processing \d+ (photos|videos)")


@dataclass
class InFlight:
    name: str
    kind: str
    server: str
    since: float


@dataclass
class LogState:
    in_flight: dict[str, InFlight] = field(default_factory=dict)
    done: int | None = None
    total: int | None = None
    phase: str | None = None
    last_finished: tuple[str, float] | None = None
    last_line_at: float | None = None


def _read_tail(path: Path) -> list[str]:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    return lines[1:] if size > TAIL_BYTES else lines


def _epoch(stamp: str) -> float:
    return datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").timestamp()


def _start_of(state: LogState, match: re.Match, at: float) -> None:
    kind = match["kind"] or "transcript"
    state.in_flight[match["name"]] = InFlight(match["name"], kind, match["server"], at)
    state.phase = {"photo": "photos", "video": "videos"}.get(kind, "transcripts")


def _finish_of(state: LogState, name: str, at: float) -> None:
    state.in_flight.pop(name, None)
    state.last_finished = (name, at)


def parse_log(lines: list[str]) -> LogState:
    state = LogState()
    for line in lines:
        parsed = LOG_LINE.match(line)
        if not parsed:
            continue
        at = _epoch(parsed[1])
        message = parsed[2]
        state.last_line_at = at
        if message.startswith("Server: "):
            state = LogState()
        elif message.startswith(("Sleeping ", "No unprocessed")):
            state.phase = None
            state.in_flight.clear()
        elif match := PROCESSING.match(message):
            state.phase = match[1]
        elif match := LABELING.match(message):
            _start_of(state, match, at)
        elif match := FINISHED.match(message):
            state.done, state.total = int(match["done"]), int(match["total"])
            _finish_of(state, match["name"], at)
        elif match := TRANSCRIPT_FINISHED.match(message):
            _finish_of(state, match["name"], at)
    now = time.time()
    state.in_flight = {
        name: item
        for name, item in state.in_flight.items()
        if now - item.since < STALE_IN_FLIGHT_S
    }
    return state


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    minutes, secs = divmod(round(seconds), SECONDS_PER_MINUTE)
    if not minutes:
        return f"{secs}s"
    hours, minutes = divmod(minutes, MINUTES_PER_HOUR)
    if not hours:
        return f"{minutes}m{secs:02d}s"
    days, hours = divmod(hours, HOURS_PER_DAY)
    if not days:
        return f"{hours}h{minutes:02d}m"
    return f"{days}d{hours:02d}h"


def ago(timestamp: float) -> str:
    return f"{duration(time.time() - timestamp)} ago"


def seconds_value(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}s"


def sparkline(values: list[int]) -> str:
    peak = max(values, default=0)
    if peak == 0:
        return "·" * len(values)
    return "".join(
        "·" if v == 0 else SPARK[min(len(SPARK) - 1, v * len(SPARK) // (peak + 1))]
        for v in values
    )


def bar(share: float) -> str:
    filled = round(share * BAR_WIDTH)
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "-"


def _since(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) - delta).isoformat()


def _count_since(delta: timedelta) -> dict[str, int]:
    rows = metrics.read(
        "SELECT media_type, COUNT(*) FROM item_metrics "
        "WHERE status='success' AND timestamp >= ? GROUP BY media_type",
        (_since(delta),),
    )
    return dict(rows)


def _average_since(delta: timedelta) -> dict[str, tuple]:
    rows = metrics.read(
        "SELECT media_type, AVG(export_duration_s), AVG(llm_duration_s), "
        "AVG(write_duration_s), AVG(total_duration_s), AVG(keywords_count), "
        "AVG(input_tokens), AVG(output_tokens), AVG(llm_retries) "
        "FROM item_metrics WHERE status='success' AND timestamp >= ? "
        "GROUP BY media_type",
        (_since(delta),),
    )
    return {row[0]: row[1:] for row in rows}


def _buckets(delta: timedelta, unit: str) -> dict[str, dict[str, int]]:
    rows = metrics.read(
        f"SELECT strftime('{unit}', substr(timestamp, 1, 19), 'localtime'), "
        "media_type, COUNT(*) FROM item_metrics "
        "WHERE status='success' AND timestamp >= ? GROUP BY 1, 2",
        (_since(delta),),
    )
    buckets: dict[str, dict[str, int]] = {}
    for bucket, media_type, count in rows:
        buckets.setdefault(bucket, {})[media_type] = count
    return buckets


def _series(
    buckets: dict[str, dict[str, int]], keys: list[str], media_types: tuple[str, ...]
) -> list[int]:
    return [sum(buckets.get(k, {}).get(m, 0) for m in media_types) for k in keys]


def _hour_keys(hours: int) -> list[datetime]:
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    return [now - timedelta(hours=h) for h in range(hours - 1, -1, -1)]


def _day_keys(days: int) -> list[datetime]:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return [today - timedelta(days=d) for d in range(days - 1, -1, -1)]


def rate_per_hour(count: int, delta: timedelta) -> float:
    return count / (delta.total_seconds() / 3600)


def _model_names() -> dict[str, str]:
    names = {
        row[0]
        for row in metrics.read(
            "SELECT DISTINCT model FROM item_metrics WHERE model IS NOT NULL"
        )
    }
    names |= {s["model"] for s in config.resolve_servers(config.load_config())}
    return library.remember_models(names)


def now_section(state: LogState, run: tuple | None) -> list[str]:
    lines = ["NOW"]
    if state.phase is None and not state.in_flight:
        lines.append("  Idle, waiting for the next cycle")
    else:
        phase = state.phase or "starting"
        progress = ""
        if state.done is not None and state.total:
            progress = (
                f", {state.done}/{state.total} ({percent(state.done, state.total)})"
            )
        lines.append(f"  Phase       {phase}{progress}")
    if run:
        lines.append(
            f"  Cycle       started {ago(run[0])}, {run[1]} photos, {run[2]} videos"
        )
    if state.last_finished:
        name, at = state.last_finished
        lines.append(f"  Last done   {name} ({ago(at)})")
    if state.in_flight:
        lines.append(f"  Labeling    {len(state.in_flight)} at the moment:")
        for item in sorted(state.in_flight.values(), key=lambda i: i.since):
            lines.append(
                f"    {item.name:<24} {item.kind:<10} {item.server:<32} "
                f"{duration(time.time() - item.since)}"
            )
    return lines


def _current_run() -> tuple | None:
    rows = metrics.read(
        "SELECT started_at, photos_found, videos_found FROM run_metrics "
        "WHERE finished_at IS NULL ORDER BY id DESC LIMIT 1"
    )
    if not rows:
        return None
    started = datetime.fromisoformat(rows[0][0]).timestamp()
    return started, rows[0][1], rows[0][2]


def speed_section() -> list[str]:
    lines = ["SPEED (finished items)"]
    lines.append(
        f"  {'window':<10} {'photos':>8} {'videos':>8} "
        f"{'transcripts':>12} {'per hour':>10}"
    )
    for label, delta in (
        ("last 10m", timedelta(minutes=10)),
        ("last 1h", timedelta(hours=1)),
        ("last 24h", timedelta(hours=24)),
        ("last 7d", timedelta(days=7)),
    ):
        counts = _count_since(delta)
        total = sum(counts.values())
        lines.append(
            f"  {label:<10} {counts.get('photo', 0):>8} {counts.get('video', 0):>8} "
            f"{counts.get('transcript', 0):>12} {rate_per_hour(total, delta):>10.0f}"
        )
    return lines


def averages_section() -> list[str]:
    averages = _average_since(timedelta(hours=24))
    lines = ["AVERAGES (last 24h, per item)"]
    if not averages:
        return [*lines, "  Nothing finished in the last 24h"]
    kinds = [m for m in MEDIA_TYPES if m in averages]
    lines.append("  " + " " * 14 + "".join(f"{k:>12}" for k in kinds))
    rows = (
        ("export", 0, seconds_value),
        ("LLM", 1, seconds_value),
        ("write", 2, seconds_value),
        ("total", 3, seconds_value),
        ("keywords", 4, lambda v: "-" if v is None else f"{v:.1f}"),
        ("tokens in", 5, lambda v: "-" if v is None else f"{v:,.0f}"),
        ("tokens out", 6, lambda v: "-" if v is None else f"{v:,.0f}"),
        ("retries", 7, lambda v: "-" if v is None else f"{v:.2f}"),
    )
    for label, index, show in rows:
        lines.append(
            f"  {label:<14}" + "".join(f"{show(averages[k][index]):>12}" for k in kinds)
        )
    return lines


def _peak_label(values: list[int], labels: list[str], unit: str) -> str:
    peak = max(values, default=0)
    if not peak:
        return ""
    return f"peak {peak}/{unit} at {labels[values.index(peak)]}"


def curve_section() -> list[str]:
    hours = _hour_keys(24)
    hour_keys = [h.strftime("%Y-%m-%d %H") for h in hours]
    hour_labels = [h.strftime("%H:00") for h in hours]
    hourly = _buckets(timedelta(hours=24), "%Y-%m-%d %H")
    days = _day_keys(7)
    day_keys = [d.strftime("%Y-%m-%d") for d in days]
    day_labels = [d.strftime("%a") for d in days]
    daily = _buckets(timedelta(days=8), "%Y-%m-%d")
    lines = [
        f"CURVE (oldest to newest; hours {hour_labels[0]} to now, "
        f"days {day_labels[0]} to today)"
    ]
    for label, kinds in (("photos", ("photo",)), ("videos", ("video",))):
        values = _series(hourly, hour_keys, kinds)
        lines.append(
            f"  {label:<7} per hour  {sparkline(values)}  "
            f"{_peak_label(values, hour_labels, 'h')}".rstrip()
        )
    for label, kinds in (("photos", ("photo",)), ("videos", ("video",))):
        values = _series(daily, day_keys, kinds)
        lines.append(
            f"  {label:<7} per day   {sparkline(values)}  "
            f"{_peak_label(values, day_labels, 'day')}".rstrip()
        )
    return lines


def models_section() -> list[str]:
    cutoff = _since(timedelta(hours=24))
    rows = metrics.read(
        "SELECT COALESCE(model, '?'), COALESCE(server, '?'), "
        "SUM(timestamp >= ?), AVG(CASE WHEN timestamp >= ? THEN llm_duration_s END), "
        "COUNT(*), MAX(timestamp) "
        "FROM item_metrics WHERE status='success' "
        "GROUP BY 1, 2 ORDER BY 3 DESC, 5 DESC",
        (cutoff, cutoff),
    )
    lines = ["MODELS (by server)"]
    total_day = sum(r[2] or 0 for r in rows)
    lines.append(
        f"  {'model':<26} {'server':<30} {'24h':>7} {'share':>7} {'avg LLM':>8} "
        f"{'all time':>9}  last used"
    )
    for model, server, day, avg_llm, everything, last in rows:
        used = ago(datetime.fromisoformat(last).timestamp()) if last else "-"
        lines.append(
            f"  {model[:26]:<26} {server[:30]:<30} {day or 0:>7} "
            f"{percent(day or 0, total_day):>7} {seconds_value(avg_llm):>8} "
            f"{everything:>9,}  {used}"
        )
    return lines


def _content_filter_line() -> list[str]:
    labeled, blocked = metrics.read(
        "SELECT COALESCE(SUM(status='success'), 0), COALESCE(SUM(status='error'), 0) "
        "FROM item_metrics WHERE content_filtered=1"
    )[0]
    if not labeled and not blocked:
        return []
    return [
        f"  Content filter: {labeled:,} labeled without copied text, "
        f"{blocked:,} blocked and not retried"
    ]


def errors_section() -> list[str]:
    day = _since(timedelta(hours=24))
    count = metrics.read(
        "SELECT COUNT(*) FROM item_metrics WHERE status='error' AND timestamp >= ?",
        (day,),
    )[0][0]
    lines = ["ERRORS", *_content_filter_line()]
    if not count:
        return [*lines, "  None in the last 24h"]
    lines.append(f"  {count} in the last 24h. Latest:")
    latest = metrics.read(
        "SELECT filename, media_type, error_message, timestamp FROM item_metrics "
        "WHERE status='error' ORDER BY timestamp DESC LIMIT 3"
    )
    for filename, media_type, message, stamp in latest:
        when = ago(datetime.fromisoformat(stamp).timestamp())
        lines.append(f"    {filename} ({media_type}, {when}): {(message or '')[:80]}")
    return lines


def _library_kind(
    label: str, counts: dict, names: dict[str, str], current: set[str]
) -> list[str]:
    total = counts["total"]
    lines = [f"  {label}: {total:,}"]
    entries = sorted(counts["models"].items(), key=lambda kv: -kv[1])
    for tag, count in entries:
        name = names.get(tag, f"unknown model ({tag})")
        mark = " (current)" if tag in current else ""
        lines.append(
            f"    {bar(count / total if total else 0)} {percent(count, total):>6} "
            f"{count:>8,}  {name}{mark}"
        )
    lines.append(
        f"    {bar(counts['unlabeled'] / total if total else 0)} "
        f"{percent(counts['unlabeled'], total):>6} {counts['unlabeled']:>8,}  unlabeled"
    )
    if counts.get("settings_outdated"):
        lines.append(
            f"    {counts['settings_outdated']:,} videos on the current model have "
            "other frame settings and will be relabeled"
        )
    return lines


def remaining(counts: dict, current: set[str]) -> int:
    on_current = sum(n for tag, n in counts["models"].items() if tag in current)
    return counts["total"] - on_current + counts.get("settings_outdated", 0)


def _eta(snapshot: dict, current: set[str]) -> str:
    delta = timedelta(hours=24)
    done = _count_since(delta)
    photos_left = remaining(snapshot["photos"], current)
    videos_left = remaining(snapshot["videos"], current)
    photo_rate = rate_per_hour(done.get("photo", 0), delta)
    video_rate = rate_per_hour(done.get("video", 0), delta)
    if (photos_left and not photo_rate) or (videos_left and not video_rate):
        return f"{photos_left:,} photos and {videos_left:,} videos left, no pace yet"
    hours = (photos_left / photo_rate if photos_left else 0) + (
        videos_left / video_rate if videos_left else 0
    )
    finish = datetime.now() + timedelta(hours=hours)
    return (
        f"{photos_left:,} photos and {videos_left:,} videos left. At the last 24h "
        f"pace that's about {duration(hours * 3600)}, around "
        f"{finish.strftime('%a %d %b')}"
    )


def library_section() -> list[str]:
    snapshot = library.load()
    if snapshot is None:
        return [
            "LIBRARY",
            "  No summary yet. The daemon saves one at the start of its next cycle",
        ]
    names = _model_names()
    current = set(snapshot["current_tags"])
    lines = [f"LIBRARY (as of {ago(snapshot['updated_at'])}, hidden items left out)"]
    lines += _library_kind("Photos", snapshot["photos"], names, current)
    lines += _library_kind("Videos", snapshot["videos"], names, current)
    lines.append(f"  Left: {_eta(snapshot, current)}")
    return lines


def build(log_path: Path) -> str:
    state = parse_log(_read_tail(log_path))
    sections = [
        now_section(state, _current_run()),
        speed_section(),
        averages_section(),
        curve_section(),
        models_section(),
        library_section(),
        errors_section(),
    ]
    return "\n\n".join("\n".join(section) for section in sections)
