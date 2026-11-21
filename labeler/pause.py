import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime

from labeler.config import CONFIG_DIR
from labeler.shutdown import is_shutting_down
from labeler.shutdown import wait as shutdown_wait

logger = logging.getLogger(__name__)

PAUSE_PATH = CONFIG_DIR / "paused"
PAUSE_LIMIT_S = 3600
MAX_PAUSE_MINUTES = 60
WAIT_INTERVAL_S = 1


class StoppedWhilePausedError(RuntimeError):
    def __init__(self):
        super().__init__("Stopped while paused, nothing was written")


@dataclass(frozen=True)
class Pause:
    since: float
    resumes_at: float | None

    @property
    def stops_at(self) -> float:
        return self.since + PAUSE_LIMIT_S

    def is_over(self) -> bool:
        return self.resumes_at is not None and time.time() >= self.resumes_at

    def has_expired(self) -> bool:
        return self.resumes_at is None and time.time() >= self.stops_at


def pause(minutes: int | None = None):
    PAUSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    resumes_at = "" if minutes is None else str(time.time() + minutes * 60)
    written = PAUSE_PATH.with_name(f"{PAUSE_PATH.name}.new")
    written.write_text(resumes_at)
    written.replace(PAUSE_PATH)


def resume():
    PAUSE_PATH.unlink(missing_ok=True)


def current() -> Pause | None:
    try:
        since = PAUSE_PATH.stat().st_mtime
        text = PAUSE_PATH.read_text().strip()
    except FileNotFoundError:
        return None
    try:
        resumes_at = float(text) if text else None
    except ValueError:
        resumes_at = None
    return Pause(since=since, resumes_at=resumes_at)


def active() -> Pause | None:
    found = current()
    return None if found is None or found.is_over() else found


def is_paused() -> bool:
    return active() is not None


def clock_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%H:%M")


def clear_if_over():
    found = current()
    if found is not None and (found.is_over() or found.has_expired()):
        logger.info("Clearing an old pause")
        resume()


def wait_while_paused():
    while is_paused() and not is_shutting_down():
        shutdown_wait(WAIT_INTERVAL_S)


def wait_until_photos_can_be_used():
    wait_while_paused()
    if is_paused():
        raise StoppedWhilePausedError


def watch(stop):
    threading.Thread(
        target=_watch, args=(stop,), name="pause-watcher", daemon=True
    ).start()


def _describe(found: Pause) -> str:
    if found.resumes_at is not None:
        return (
            f"Paused until {clock_time(found.resumes_at)}: nothing is exported "
            "or written to Photos"
        )
    return (
        "Paused: nothing is exported or written to Photos until 'daemon resume'. "
        f"Stopping for good at {clock_time(found.stops_at)}"
    )


def _watch(stop):
    seen = None
    while not shutdown_wait(WAIT_INTERVAL_S):
        found = active()
        if found is None:
            if seen is not None:
                logger.info("Resumed")
            seen = None
            continue
        if found != seen:
            logger.info(_describe(found))
        seen = found
        if found.has_expired():
            logger.info("Paused for an hour without a resume, stopping for good")
            stop()
            return
