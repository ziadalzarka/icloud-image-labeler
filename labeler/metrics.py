import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = str(Path.home() / ".image-labeler" / "metrics.db")

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """Get a thread-local database connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS item_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid TEXT NOT NULL UNIQUE,
            filename TEXT NOT NULL,
            media_type TEXT NOT NULL,
            is_icloud_only INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            error_message TEXT,
            export_duration_s REAL,
            llm_duration_s REAL,
            write_duration_s REAL,
            total_duration_s REAL,
            image_size_bytes INTEGER,
            image_width INTEGER,
            image_height INTEGER,
            num_frames INTEGER,
            llm_retries INTEGER DEFAULT 0,
            keywords_count INTEGER,
            has_ocr INTEGER DEFAULT 0,
            model TEXT,
            timestamp TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS run_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            total_duration_s REAL,
            photos_found INTEGER DEFAULT 0,
            videos_found INTEGER DEFAULT 0,
            photos_processed INTEGER DEFAULT 0,
            videos_processed INTEGER DEFAULT 0,
            photos_failed INTEGER DEFAULT 0,
            videos_failed INTEGER DEFAULT 0,
            model TEXT,
            threads INTEGER,
            dry_run INTEGER DEFAULT 0,
            avg_llm_duration_s REAL
        );

        CREATE INDEX IF NOT EXISTS idx_item_timestamp ON item_metrics(timestamp);
        CREATE INDEX IF NOT EXISTS idx_item_status ON item_metrics(status);
        CREATE INDEX IF NOT EXISTS idx_run_started ON run_metrics(started_at);
    """)
    conn.commit()
    logger.debug(f"Metrics database initialized at {DB_PATH}")


def record_item(
    uuid: str,
    filename: str,
    media_type: str,
    is_icloud_only: bool,
    status: str,
    error_message: str | None = None,
    export_duration_s: float | None = None,
    llm_duration_s: float | None = None,
    write_duration_s: float | None = None,
    total_duration_s: float | None = None,
    image_size_bytes: int | None = None,
    image_width: int | None = None,
    image_height: int | None = None,
    num_frames: int | None = None,
    llm_retries: int = 0,
    keywords_count: int | None = None,
    has_ocr: bool = False,
    model: str | None = None,
):
    """Record metrics for a single processed item (upserts by uuid)."""
    conn = _get_conn()
    conn.execute(
        """INSERT INTO item_metrics (
            uuid, filename, media_type, is_icloud_only, status, error_message,
            export_duration_s, llm_duration_s, write_duration_s, total_duration_s,
            image_size_bytes, image_width, image_height, num_frames,
            llm_retries, keywords_count, has_ocr, model, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(uuid) DO UPDATE SET
            filename=excluded.filename, media_type=excluded.media_type,
            is_icloud_only=excluded.is_icloud_only, status=excluded.status,
            error_message=excluded.error_message, export_duration_s=excluded.export_duration_s,
            llm_duration_s=excluded.llm_duration_s, write_duration_s=excluded.write_duration_s,
            total_duration_s=excluded.total_duration_s, image_size_bytes=excluded.image_size_bytes,
            image_width=excluded.image_width, image_height=excluded.image_height,
            num_frames=excluded.num_frames, llm_retries=excluded.llm_retries,
            keywords_count=excluded.keywords_count, has_ocr=excluded.has_ocr,
            model=excluded.model, timestamp=excluded.timestamp""",
        (
            uuid,
            filename,
            media_type,
            int(is_icloud_only),
            status,
            error_message,
            export_duration_s,
            llm_duration_s,
            write_duration_s,
            total_duration_s,
            image_size_bytes,
            image_width,
            image_height,
            num_frames,
            llm_retries,
            keywords_count,
            int(has_ocr),
            model,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def start_run(
    model: str, threads: int, dry_run: bool, photos_found: int, videos_found: int
) -> int:
    """Record the start of a batch run. Returns the run ID."""
    conn = _get_conn()
    cursor = conn.execute(
        """INSERT INTO run_metrics (started_at, model, threads, dry_run, photos_found, videos_found)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            model,
            threads,
            int(dry_run),
            photos_found,
            videos_found,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def finish_run(
    run_id: int,
    photos_processed: int,
    videos_processed: int,
    photos_failed: int,
    videos_failed: int,
    avg_llm_duration_s: float | None = None,
):
    """Record the end of a batch run."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE run_metrics SET
            finished_at = ?,
            total_duration_s = (julianday(?) - julianday(started_at)) * 86400,
            photos_processed = ?,
            videos_processed = ?,
            photos_failed = ?,
            videos_failed = ?,
            avg_llm_duration_s = ?
        WHERE id = ?""",
        (
            now,
            now,
            photos_processed,
            videos_processed,
            photos_failed,
            videos_failed,
            avg_llm_duration_s,
            run_id,
        ),
    )
    conn.commit()
