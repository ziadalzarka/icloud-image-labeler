"""Graceful shutdown handling via SIGINT/SIGTERM."""

import logging
import signal
import threading

logger = logging.getLogger(__name__)

_shutdown_event = threading.Event()


def request_shutdown(signum=None, frame=None):
    """Signal handler that sets the shutdown flag."""
    name = signal.Signals(signum).name if signum else "unknown"
    logger.info(f"Received {name}, shutting down gracefully...")
    _shutdown_event.set()


def is_shutting_down() -> bool:
    return _shutdown_event.is_set()


def wait(timeout: float) -> bool:
    """Sleep for up to `timeout` seconds, returning True if shutdown was requested."""
    return _shutdown_event.wait(timeout)


def install_handlers():
    """Install SIGINT and SIGTERM handlers. Call once from the main thread."""
    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)
