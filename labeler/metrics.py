"""SQLite metrics database for tracking processing runs and items."""

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = str(Path.home() / ".image-labeler" / "metrics.db")

# Error-message substrings that indicate an item will fail again on every
# subsequent run (no video stream, corrupt MP4 atoms, etc.). Discovery uses
# this list to skip known-unrecoverable items. To force a retry, delete the
# offending row from item_metrics.
PERMANENT_FAILURE_PATTERNS: tuple[str, ...] = ("No usable video source",)

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
            server TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
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
            servers TEXT,
            threads INTEGER,
            dry_run INTEGER DEFAULT 0,
            avg_llm_duration_s REAL
        );

        CREATE TABLE IF NOT EXISTS model_pricing (
            model TEXT PRIMARY KEY,
            input_per_1m REAL NOT NULL,
            output_per_1m REAL NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_item_timestamp ON item_metrics(timestamp);
        CREATE INDEX IF NOT EXISTS idx_item_status ON item_metrics(status);
        CREATE INDEX IF NOT EXISTS idx_run_started ON run_metrics(started_at);
    """)
    _ensure_column(conn, "item_metrics", "server", "TEXT")
    _ensure_column(conn, "item_metrics", "input_tokens", "INTEGER")
    _ensure_column(conn, "item_metrics", "output_tokens", "INTEGER")
    _ensure_column(conn, "run_metrics", "servers", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_item_server ON item_metrics(server)")
    conn.commit()
    logger.debug(f"Metrics database initialized at {DB_PATH}")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, col_type: str):
    """Add a column to an existing table if missing (SQLite migration helper)."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def get_permanent_failure_uuids() -> set[str]:
    """Return UUIDs whose last attempt hit a known-unrecoverable error.

    See ``PERMANENT_FAILURE_PATTERNS`` for the allowlist of substrings.
    """
    conn = _get_conn()
    clauses = " OR ".join("error_message LIKE ?" for _ in PERMANENT_FAILURE_PATTERNS)
    sql = f"SELECT uuid FROM item_metrics WHERE status='error' AND ({clauses})"
    params = [f"%{p}%" for p in PERMANENT_FAILURE_PATTERNS]
    return {row[0] for row in conn.execute(sql, params)}


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
    server: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
):
    """Record metrics for a single processed item (upserts by uuid)."""
    conn = _get_conn()
    conn.execute(
        """INSERT INTO item_metrics (
            uuid, filename, media_type, is_icloud_only, status, error_message,
            export_duration_s, llm_duration_s, write_duration_s, total_duration_s,
            image_size_bytes, image_width, image_height, num_frames,
            llm_retries, keywords_count, has_ocr, model, server,
            input_tokens, output_tokens, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(uuid) DO UPDATE SET
            filename=excluded.filename,
            media_type=excluded.media_type,
            is_icloud_only=excluded.is_icloud_only,
            status=excluded.status,
            error_message=excluded.error_message,
            export_duration_s=excluded.export_duration_s,
            llm_duration_s=excluded.llm_duration_s,
            write_duration_s=excluded.write_duration_s,
            total_duration_s=excluded.total_duration_s,
            image_size_bytes=excluded.image_size_bytes,
            image_width=excluded.image_width,
            image_height=excluded.image_height,
            num_frames=excluded.num_frames,
            llm_retries=excluded.llm_retries,
            keywords_count=excluded.keywords_count,
            has_ocr=excluded.has_ocr,
            model=excluded.model,
            server=excluded.server,
            input_tokens=excluded.input_tokens,
            output_tokens=excluded.output_tokens,
            timestamp=excluded.timestamp""",
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
            server,
            input_tokens,
            output_tokens,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def start_run(
    model: str,
    threads: int,
    dry_run: bool,
    photos_found: int,
    videos_found: int,
    servers: str | None = None,
) -> int:
    """Record the start of a batch run. Returns the run ID."""
    conn = _get_conn()
    cursor = conn.execute(
        """INSERT INTO run_metrics (
            started_at, model, servers, threads,
            dry_run, photos_found, videos_found
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            model,
            servers,
            threads,
            int(dry_run),
            photos_found,
            videos_found,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def set_pricing(model: str, input_per_1m: float, output_per_1m: float):
    """Upsert pricing (USD per 1M tokens) for a model."""
    conn = _get_conn()
    conn.execute(
        """INSERT INTO model_pricing (model, input_per_1m, output_per_1m, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(model) DO UPDATE SET
            input_per_1m=excluded.input_per_1m,
            output_per_1m=excluded.output_per_1m,
            updated_at=excluded.updated_at""",
        (model, input_per_1m, output_per_1m, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def list_pricing() -> list[dict]:
    """Return all model pricing rows."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT model, input_per_1m, output_per_1m, updated_at "
        "FROM model_pricing ORDER BY model"
    ).fetchall()
    return [
        {
            "model": r[0],
            "input_per_1m": r[1],
            "output_per_1m": r[2],
            "updated_at": r[3],
        }
        for r in rows
    ]


def delete_pricing(model: str) -> int:
    """Remove pricing for a model. Returns the number of rows deleted."""
    conn = _get_conn()
    cur = conn.execute("DELETE FROM model_pricing WHERE model = ?", (model,))
    conn.commit()
    return cur.rowcount


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
