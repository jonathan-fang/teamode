"""SQLite schema and write/read helpers for TeaMode session state."""

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
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
    started_at           TEXT,
    duration_minutes     INTEGER,
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

_CREATE_SESSION_PARTICIPANTS = """
CREATE TABLE IF NOT EXISTS session_participants (
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    user_id     TEXT    NOT NULL,
    joined_late INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, user_id)
)
"""

_CREATE_IDX_PARTICIPANTS_USER = """
CREATE INDEX IF NOT EXISTS idx_session_participants_user
ON session_participants(user_id)
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
    conn.execute(_CREATE_SESSION_PARTICIPANTS)
    conn.execute(_CREATE_IDX_PARTICIPANTS_USER)
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

    started_at and duration_minutes are left NULL; they are populated by
    update_started_at_active (when the timer begins) and update_duration
    (when the facilitator picks a length) respectively.

    Returns the new row id.
    """
    cur = conn.execute(
        """
        INSERT INTO sessions (
            guild_id, text_channel_id, voice_channel_id, facilitator_id,
            status
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            guild_id,
            text_channel_id,
            voice_channel_id,
            facilitator_id,
            "pending",
        ),
    )
    conn.commit()
    if cur.lastrowid is None:
        # An INSERT that yields no rowid is a real failure — sqlite3 always
        # sets lastrowid for a successful single-row INSERT into a table
        # with a rowid (which `sessions` is), so this indicates the insert
        # did not happen as expected.
        raise RuntimeError("INSERT into sessions did not yield a rowid")
    return cur.lastrowid


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


def insert_session_participants(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    user_ids: Iterable[str],
    joined_late: bool,
) -> None:
    """INSERT OR IGNORE one row per user_id into session_participants.

    An existing (session_id, user_id) row is left untouched, so the first
    recorded joined_late value wins. No-op on empty input.
    """
    flag = 1 if joined_late else 0
    rows = [(session_id, user_id, flag) for user_id in user_ids]
    if not rows:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO session_participants"
        " (session_id, user_id, joined_late) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()


def fetch_session_participants(
    conn: sqlite3.Connection,
    *,
    session_id: int,
) -> list[tuple[str, bool]]:
    """SELECT (user_id, joined_late) for a session, ordered by user_id."""
    cur = conn.execute(
        "SELECT user_id, joined_late FROM session_participants"
        " WHERE session_id = ? ORDER BY user_id",
        (session_id,),
    )
    return [(user_id, bool(late)) for user_id, late in cur.fetchall()]


_QUALIFYING_STATUSES = ("completed", "followup_timeout")


@dataclass(frozen=True)
class StatsSessionRow:
    """One session row relevant to /stats aggregation."""

    started_at: str
    duration_minutes: int | None
    completed_intention: int | None


def _row_to_stats_row(row: tuple[str, int | None, int | None]) -> StatsSessionRow:
    started_at, duration_minutes, completed_intention = row
    return StatsSessionRow(
        started_at=started_at,
        duration_minutes=duration_minutes,
        completed_intention=completed_intention,
    )


def fetch_user_stats_rows(
    conn: sqlite3.Connection,
    *,
    user_id: str,
) -> list[StatsSessionRow]:
    """Return qualifying sessions *user_id* was in or originally facilitated.

    Qualifying means ``status`` reached follow-up
    (``'completed'`` or ``'followup_timeout'``). A session matches when
    the user has a ``session_participants`` row OR is the ORIGINAL
    ``facilitator_id``; the single WHERE dedupes (no UNION), so a user who
    is both gets one row.

    ``completed_intention`` is returned only for sessions the user
    originally facilitated and is NULL otherwise, so the completion rate
    covers facilitated sessions only while sessions and minutes cover
    everything. A handoff target counts as a participant, but their
    Reflect answer does not count toward their rate (original-facilitator
    rule, unchanged). Sessions from before participant tracking have no
    participant rows and so count only for their facilitator.
    """
    status_params = {f"s{i}": s for i, s in enumerate(_QUALIFYING_STATUSES)}
    placeholders = ",".join(f":{name}" for name in status_params)
    cur = conn.execute(
        f"""
        SELECT started_at, duration_minutes,
               CASE WHEN facilitator_id = :uid THEN completed_intention END
        FROM sessions
        WHERE status IN ({placeholders})
          AND (facilitator_id = :uid
               OR id IN (
                   SELECT session_id FROM session_participants
                   WHERE user_id = :uid
               ))
        """,  # noqa: S608
        {"uid": user_id, **status_params},
    )
    return [_row_to_stats_row(row) for row in cur.fetchall()]


def fetch_guild_stats_rows(
    conn: sqlite3.Connection,
    *,
    guild_id: str,
) -> list[StatsSessionRow]:
    """Return qualifying sessions started in *guild_id*.

    Qualifying means ``status`` reached follow-up
    (``'completed'`` or ``'followup_timeout'``).
    """
    placeholders = ",".join("?" * len(_QUALIFYING_STATUSES))
    cur = conn.execute(
        f"""
        SELECT started_at, duration_minutes, completed_intention
        FROM sessions
        WHERE guild_id = ? AND status IN ({placeholders})
        """,  # noqa: S608
        (guild_id, *_QUALIFYING_STATUSES),
    )
    return [_row_to_stats_row(row) for row in cur.fetchall()]


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
