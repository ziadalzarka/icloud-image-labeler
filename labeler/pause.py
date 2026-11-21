import logging
import threading
import time
from datetime import datetime

from labeler.config import CONFIG_DIR
from labeler.shutdown import is_shutting_down
from labeler.shutdown import wait as shutdown_wait

logger = logging.getLogger(__name__)

PAUSE_PATH = CONFIG_DIR / "paused"
PAUSE_LIMIT_S = 3600
WAIT_INTERVAL_S = 1


class StoppedWhilePausedError(RuntimeError):
    def __init__(self):
        super().__init__("Stopped while paused, nothing was written")


def pause():
    PAUSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PAUSE_PATH.touch()


def resume():
    PAUSE_PATH.unlink(missing_ok=True)


def paused_since() -> float | None:
    try:
        return PAUSE_PATH.stat().st_mtime
    except FileNotFoundError:
        return None


def is_paused() -> bool:
    return PAUSE_PATH.exists()


def stops_at(since: float) -> float:
    return since + PAUSE_LIMIT_S


def has_expired() -> bool:
    since = paused_since()
    return since is not None and time.time() >= stops_at(since)


def clock_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%H:%M")


def clear_if_expired():
    if has_expired():
        logger.info("Clearing a pause that ran past its hour")
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


def _watch(stop):
    was_paused = False
    while not shutdown_wait(WAIT_INTERVAL_S):
        since = paused_since()
        if since is None:
            if was_paused:
                logger.info("Resumed")
            was_paused = False
            continue
        if not was_paused:
            logger.info(
                "Paused: nothing is exported or written to Photos until "
                f"'daemon resume'. Stopping for good at {clock_time(stops_at(since))}"
            )
        was_paused = True
        if time.time() >= stops_at(since):
            logger.info("Paused for an hour without a resume, stopping for good")
            stop()
            return
