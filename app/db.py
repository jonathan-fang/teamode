"""SQLite schema and write helpers for TeaMode session state."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config import TEAMODE_DB_PATH

DB_PATH: str = TEAMODE_DB_PATH

_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id             TEXT    NOT NULL,
    text_channel_id      TEXT    NOT NULL,
    voice_channel_id     TEXT    NOT NULL,
    facilitator_id       TEXT    NOT NULL,
    started_at           TEXT    NOT NULL,
    duration_minutes     INTEGER NOT NULL,
    intention            TEXT,
    ended_at             TEXT,
    completed_intention  INTEGER,
    followup_note        TEXT,
    status               TEXT    NOT NULL,
    handoff_facilitator_id TEXT
)
"""

_CREATE_IDX_FACILITATOR = """
CREATE INDEX IF NOT EXISTS idx_sessions_facilitator ON sessions(facilitator_id)
"""

_CREATE_IDX_STARTED_AT = """
CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at)
"""

_NON_TERMINAL_STATUSES = ("pending", "intention_set", "active", "followup")


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(path: str | Path) -> sqlite3.Connection:
    """Open (or create) the database at *path* and apply the schema.

    Safe to call repeatedly — uses CREATE TABLE IF NOT EXISTS and
    CREATE INDEX IF NOT EXISTS. Returns the open connection.
    """
    conn = sqlite3.connect(str(path))
    conn.execute(_CREATE_SESSIONS)
    conn.execute(_CREATE_IDX_FACILITATOR)
    conn.execute(_CREATE_IDX_STARTED_AT)
    conn.commit()
    return conn


def insert_pending_session(
    conn: sqlite3.Connection,
    *,
    guild_id: str,
    text_channel_id: str,
    voice_channel_id: str,
    facilitator_id: str,
) -> int:
    """INSERT a row with status='pending' at /teamode invocation.

    started_at is set to the current UTC time as an invocation timestamp;
    it will be overwritten by update_started_at_active once the timer begins.
    duration_minutes is set to 0 as a placeholder until the facilitator picks.

    Returns the new row id.
    """
    cur = conn.execute(
        """
        INSERT INTO sessions (
            guild_id, text_channel_id, voice_channel_id, facilitator_id,
            started_at, duration_minutes, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            guild_id,
            text_channel_id,
            voice_channel_id,
            facilitator_id,
            _now_utc(),
            0,
            "pending",
        ),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def update_duration(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    duration_minutes: int,
) -> None:
    """UPDATE duration_minutes after the facilitator picks a timer length."""
    conn.execute(
        "UPDATE sessions SET duration_minutes = ? WHERE id = ?",
        (duration_minutes, session_id),
    )
    conn.commit()


def update_intention_and_status(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    intention: str,
) -> None:
    """UPDATE intention and set status='intention_set' after modal submit."""
    conn.execute(
        "UPDATE sessions SET intention = ?, status = 'intention_set' WHERE id = ?",
        (intention, session_id),
    )
    conn.commit()


def update_started_at_active(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    started_at: str | None = None,
) -> None:
    """UPDATE started_at and set status='active' once the timer starts.

    If *started_at* is omitted the current UTC time is used.
    """
    ts = started_at if started_at is not None else _now_utc()
    conn.execute(
        "UPDATE sessions SET started_at = ?, status = 'active' WHERE id = ?",
        (ts, session_id),
    )
    conn.commit()


def update_to_followup(
    conn: sqlite3.Connection,
    *,
    session_id: int,
) -> None:
    """Set status='followup' when the timer reaches zero."""
    conn.execute(
        "UPDATE sessions SET status = 'followup' WHERE id = ?",
        (session_id,),
    )
    conn.commit()


def update_completed(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    completed_intention: int,
    followup_note: str | None,
    ended_at: str | None = None,
) -> None:
    """UPDATE completed_intention, followup_note, ended_at, status='completed'."""
    ts = ended_at if ended_at is not None else _now_utc()
    conn.execute(
        """
        UPDATE sessions
        SET completed_intention = ?,
            followup_note = ?,
            ended_at = ?,
            status = 'completed'
        WHERE id = ?
        """,
        (completed_intention, followup_note, ts, session_id),
    )
    conn.commit()


def update_followup_timeout(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    ended_at: str | None = None,
) -> None:
    """UPDATE ended_at, status='followup_timeout' after 3-min no-answer."""
    ts = ended_at if ended_at is not None else _now_utc()
    conn.execute(
        "UPDATE sessions SET ended_at = ?, status = 'followup_timeout' WHERE id = ?",
        (ts, session_id),
    )
    conn.commit()


def update_handoff_facilitator(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    handoff_facilitator_id: str,
) -> None:
    """UPDATE handoff_facilitator_id when a facilitator handoff fires."""
    conn.execute(
        "UPDATE sessions SET handoff_facilitator_id = ? WHERE id = ?",
        (handoff_facilitator_id, session_id),
    )
    conn.commit()


def update_cancelled(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    ended_at: str | None = None,
) -> None:
    """UPDATE ended_at, status='cancelled' after grace expiry or voice failure."""
    ts = ended_at if ended_at is not None else _now_utc()
    conn.execute(
        "UPDATE sessions SET ended_at = ?, status = 'cancelled' WHERE id = ?",
        (ts, session_id),
    )
    conn.commit()


def reconcile_crashed_sessions(conn: sqlite3.Connection) -> int:
    """On startup, mark any non-terminal sessions as 'crashed'.

    Sets status='crashed' and ended_at=now() for any row whose status is in
    ('pending', 'intention_set', 'active', 'followup').

    Returns the number of rows reconciled.
    """
    ts = _now_utc()
    placeholders = ",".join("?" * len(_NON_TERMINAL_STATUSES))
    cur = conn.execute(
        f"UPDATE sessions SET status = 'crashed', ended_at = ? WHERE status IN ({placeholders})",  # noqa: S608
        (ts, *_NON_TERMINAL_STATUSES),
    )
    conn.commit()
    return cur.rowcount
