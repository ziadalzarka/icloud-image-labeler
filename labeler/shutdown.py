"""Graceful shutdown handling via SIGINT/SIGTERM."""

import logging
import signal
import threading

logger = logging.getLogger(__name__)

_shutdown_event = threading.Event()


def request_shutdown(signum=None, frame=None):
    """Signal handler that sets the shutdown flag."""
    name = signal.Signals(signum).name if signum else "unknown"
    if _shutdown_event.is_set():
        # Second signal — exit immediately
        logger.info(f"Received {name} again, forcing exit...")
        raise SystemExit(1)
    logger.info(f"Received {name}, shutting down gracefully...")
    _shutdown_event.set()
    # Raise KeyboardInterrupt so blocking calls (input, library loading) unblock
    raise KeyboardInterrupt


def is_shutting_down() -> bool:
    return _shutdown_event.is_set()


def wait(timeout: float) -> bool:
    """Sleep for up to `timeout` seconds, returning True if shutdown was requested."""
    return _shutdown_event.wait(timeout)


def install_handlers():
    """Install SIGINT and SIGTERM handlers. Call once from the main thread."""
    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)
