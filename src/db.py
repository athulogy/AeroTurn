import sqlite3
import uuid
from datetime import datetime, timezone
from src.config import DB_PATH


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def write_audit_log(
    conn: sqlite3.Connection,
    event_type: str,
    details: str,
    result: str,
    flight_no: str = None,
    actor: str = None,
    model_used: str = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_log
            (log_id, timestamp, event_type, flight_no, details, actor, model_used, result)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            datetime.now(timezone.utc).isoformat(),
            event_type,
            flight_no,
            details,
            actor,
            model_used,
            result,
        ),
    )


def fetch_all(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict]:
    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def fetch_one(conn: sqlite3.Connection, query: str, params: tuple = ()) -> dict | None:
    row = conn.execute(query, params).fetchone()
    return dict(row) if row else None
