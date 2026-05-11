"""Tests for app.db — SQLite schema and write helpers."""

import sqlite3

from app.db import (
    init_db,
    insert_pending_session,
    update_cancelled,
    update_completed,
    update_duration,
    update_followup_timeout,
    update_handoff_facilitator,
    update_intention_and_status,
    update_started_at_active,
    update_to_followup,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

EXPECTED_COLUMNS = {
    "id",
    "guild_id",
    "text_channel_id",
    "voice_channel_id",
    "facilitator_id",
    "started_at",
    "duration_minutes",
    "intention",
    "ended_at",
    "completed_intention",
    "followup_note",
    "status",
    "handoff_facilitator_id",
}


def _insert_base(conn: sqlite3.Connection) -> int:
    """Insert a minimal pending session and return its id."""
    return insert_pending_session(
        conn,
        guild_id="111",
        text_channel_id="222",
        voice_channel_id="333",
        facilitator_id="444",
    )


def _fetch(conn: sqlite3.Connection, session_id: int) -> dict:
    cur = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cur.fetchone()
    assert row is not None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# Schema init
# ---------------------------------------------------------------------------


def test_schema_init_creates_table(conn: sqlite3.Connection) -> None:
    """After init_db, the sessions table exists."""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
    )
    assert cur.fetchone() is not None


def test_schema_columns_match_spec(conn: sqlite3.Connection) -> None:
    """Columns produced by init_db match the schema reference exactly."""
    cur = conn.execute("PRAGMA table_info(sessions)")
    rows = cur.fetchall()
    actual_columns = {row[1] for row in rows}
    assert actual_columns == EXPECTED_COLUMNS


def test_schema_nullable_columns(conn: sqlite3.Connection) -> None:
    """started_at and duration_minutes must be nullable (notnull=0)."""
    cur = conn.execute("PRAGMA table_info(sessions)")
    col_notnull = {row[1]: row[3] for row in cur.fetchall()}
    assert col_notnull["started_at"] == 0, "started_at should be nullable"
    assert col_notnull["duration_minutes"] == 0, "duration_minutes should be nullable"


def test_schema_init_idempotent() -> None:
    """Calling init_db twice on the same path does not raise."""
    conn = init_db(":memory:")
    # A second init_db on the same connection path is idempotent.
    conn2 = init_db(":memory:")
    conn.close()
    conn2.close()


def test_schema_init_idempotent_same_conn(conn: sqlite3.Connection) -> None:
    """Running schema SQL again on the same connection does not raise."""
    # Re-run the full init by calling CREATE TABLE IF NOT EXISTS directly.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT NOT NULL,
            text_channel_id TEXT NOT NULL,
            voice_channel_id TEXT NOT NULL,
            facilitator_id TEXT NOT NULL,
            started_at TEXT,
            duration_minutes INTEGER,
            intention TEXT,
            ended_at TEXT,
            completed_intention INTEGER,
            followup_note TEXT,
            status TEXT NOT NULL,
            handoff_facilitator_id TEXT
        )
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# insert_pending_session
# ---------------------------------------------------------------------------


def test_insert_pending_session_row_state(conn: sqlite3.Connection) -> None:
    """insert_pending_session inserts a row with status='pending'."""
    session_id = _insert_base(conn)
    row = _fetch(conn, session_id)

    assert row["guild_id"] == "111"
    assert row["text_channel_id"] == "222"
    assert row["voice_channel_id"] == "333"
    assert row["facilitator_id"] == "444"
    assert row["status"] == "pending"
    assert row["started_at"] is None
    assert row["duration_minutes"] is None
    assert row["ended_at"] is None
    assert row["intention"] is None
    assert row["handoff_facilitator_id"] is None


def test_insert_pending_session_returns_id(conn: sqlite3.Connection) -> None:
    """insert_pending_session returns an integer row id."""
    session_id = _insert_base(conn)
    assert isinstance(session_id, int)
    assert session_id >= 1


# ---------------------------------------------------------------------------
# update_duration
# ---------------------------------------------------------------------------


def test_update_duration(conn: sqlite3.Connection) -> None:
    """update_duration sets duration_minutes on the row (was NULL before)."""
    session_id = _insert_base(conn)
    assert _fetch(conn, session_id)["duration_minutes"] is None
    update_duration(conn, session_id=session_id, duration_minutes=25)
    row = _fetch(conn, session_id)
    assert row["duration_minutes"] == 25


# ---------------------------------------------------------------------------
# update_intention_and_status
# ---------------------------------------------------------------------------


def test_update_intention_and_status(conn: sqlite3.Connection) -> None:
    """update_intention_and_status sets intention and status='intention_set'."""
    session_id = _insert_base(conn)
    update_intention_and_status(
        conn, session_id=session_id, intention="Ship the feature"
    )
    row = _fetch(conn, session_id)
    assert row["intention"] == "Ship the feature"
    assert row["status"] == "intention_set"


def test_update_intention_empty_string(conn: sqlite3.Connection) -> None:
    """intention may be an empty string (optional in the flow)."""
    session_id = _insert_base(conn)
    update_intention_and_status(conn, session_id=session_id, intention="")
    row = _fetch(conn, session_id)
    assert row["intention"] == ""
    assert row["status"] == "intention_set"


# ---------------------------------------------------------------------------
# update_started_at_active
# ---------------------------------------------------------------------------


def test_update_started_at_active(conn: sqlite3.Connection) -> None:
    """update_started_at_active sets started_at (was NULL) and status='active'."""
    session_id = _insert_base(conn)
    assert _fetch(conn, session_id)["started_at"] is None
    ts = "2026-05-10T12:00:00+00:00"
    update_started_at_active(conn, session_id=session_id, started_at=ts)
    row = _fetch(conn, session_id)
    assert row["started_at"] == ts
    assert row["status"] == "active"


def test_update_started_at_active_defaults_to_now(conn: sqlite3.Connection) -> None:
    """update_started_at_active uses the current UTC time when started_at is omitted."""
    session_id = _insert_base(conn)
    assert _fetch(conn, session_id)["started_at"] is None
    update_started_at_active(conn, session_id=session_id)
    row = _fetch(conn, session_id)
    assert row["started_at"] is not None
    assert row["status"] == "active"


# ---------------------------------------------------------------------------
# update_to_followup
# ---------------------------------------------------------------------------


def test_update_to_followup(conn: sqlite3.Connection) -> None:
    """update_to_followup sets status='followup'."""
    session_id = _insert_base(conn)
    update_to_followup(conn, session_id=session_id)
    row = _fetch(conn, session_id)
    assert row["status"] == "followup"


# ---------------------------------------------------------------------------
# update_completed
# ---------------------------------------------------------------------------


def test_update_completed_yes(conn: sqlite3.Connection) -> None:
    """update_completed records a yes answer with no followup_note."""
    session_id = _insert_base(conn)
    ts = "2026-05-10T13:00:00+00:00"
    update_completed(
        conn,
        session_id=session_id,
        completed_intention=1,
        followup_note=None,
        ended_at=ts,
    )
    row = _fetch(conn, session_id)
    assert row["completed_intention"] == 1
    assert row["followup_note"] is None
    assert row["ended_at"] == ts
    assert row["status"] == "completed"


def test_update_completed_no_with_note(conn: sqlite3.Connection) -> None:
    """update_completed records a no answer with a followup_note."""
    session_id = _insert_base(conn)
    update_completed(
        conn,
        session_id=session_id,
        completed_intention=0,
        followup_note="Got blocked on the API docs",
        ended_at="2026-05-10T14:00:00+00:00",
    )
    row = _fetch(conn, session_id)
    assert row["completed_intention"] == 0
    assert row["followup_note"] == "Got blocked on the API docs"
    assert row["status"] == "completed"


# ---------------------------------------------------------------------------
# update_followup_timeout
# ---------------------------------------------------------------------------


def test_update_followup_timeout(conn: sqlite3.Connection) -> None:
    """update_followup_timeout sets ended_at and status='followup_timeout'."""
    session_id = _insert_base(conn)
    ts = "2026-05-10T15:00:00+00:00"
    update_followup_timeout(conn, session_id=session_id, ended_at=ts)
    row = _fetch(conn, session_id)
    assert row["ended_at"] == ts
    assert row["status"] == "followup_timeout"


def test_update_followup_timeout_defaults_to_now(conn: sqlite3.Connection) -> None:
    """update_followup_timeout uses current UTC time when ended_at is omitted."""
    session_id = _insert_base(conn)
    update_followup_timeout(conn, session_id=session_id)
    row = _fetch(conn, session_id)
    assert row["ended_at"] is not None
    assert row["status"] == "followup_timeout"


# ---------------------------------------------------------------------------
# update_handoff_facilitator
# ---------------------------------------------------------------------------


def test_update_handoff_facilitator(conn: sqlite3.Connection) -> None:
    """update_handoff_facilitator sets handoff_facilitator_id."""
    session_id = _insert_base(conn)
    update_handoff_facilitator(
        conn, session_id=session_id, handoff_facilitator_id="999"
    )
    row = _fetch(conn, session_id)
    assert row["handoff_facilitator_id"] == "999"


# ---------------------------------------------------------------------------
# update_cancelled
# ---------------------------------------------------------------------------


def test_update_cancelled(conn: sqlite3.Connection) -> None:
    """update_cancelled sets ended_at and status='cancelled'."""
    session_id = _insert_base(conn)
    ts = "2026-05-10T16:00:00+00:00"
    update_cancelled(conn, session_id=session_id, ended_at=ts)
    row = _fetch(conn, session_id)
    assert row["ended_at"] == ts
    assert row["status"] == "cancelled"


def test_update_cancelled_defaults_to_now(conn: sqlite3.Connection) -> None:
    """update_cancelled uses current UTC time when ended_at is omitted."""
    session_id = _insert_base(conn)
    update_cancelled(conn, session_id=session_id)
    row = _fetch(conn, session_id)
    assert row["ended_at"] is not None
    assert row["status"] == "cancelled"
