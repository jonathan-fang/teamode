"""Tests for app.db.reconcile_crashed_sessions."""

import sqlite3

from app.db import reconcile_crashed_sessions

# ---------------------------------------------------------------------------
# reconcile_crashed_sessions
# ---------------------------------------------------------------------------

_NON_TERMINAL = ("pending", "intention_set", "active", "followup")
_TERMINAL = ("completed", "followup_timeout", "cancelled", "crashed")


def _insert_with_status(conn: sqlite3.Connection, status: str) -> int:
    """Insert a row with an explicit status, bypassing the normal helper."""
    cur = conn.execute(
        """
        INSERT INTO sessions (
            guild_id, text_channel_id, voice_channel_id, facilitator_id,
            started_at, duration_minutes, status
        ) VALUES ('g', 'tc', 'vc', 'f', '2026-01-01T00:00:00+00:00', 25, ?)
        """,
        (status,),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def _fetch(conn: sqlite3.Connection, session_id: int) -> dict:
    cur = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cur.fetchone()
    assert row is not None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def test_reconcile_marks_non_terminal_crashed(conn: sqlite3.Connection) -> None:
    """reconcile_crashed_sessions marks all non-terminal rows as 'crashed'."""
    ids = [_insert_with_status(conn, s) for s in _NON_TERMINAL]
    count = reconcile_crashed_sessions(conn)

    assert count == len(_NON_TERMINAL)
    for session_id in ids:
        row = _fetch(conn, session_id)
        assert row["status"] == "crashed", f"Expected crashed for id={session_id}"
        assert row["ended_at"] is not None


def test_reconcile_does_not_touch_terminal(conn: sqlite3.Connection) -> None:
    """reconcile_crashed_sessions leaves terminal rows unchanged."""
    ids_and_statuses = [(s, _insert_with_status(conn, s)) for s in _TERMINAL]
    reconcile_crashed_sessions(conn)

    for original_status, session_id in ids_and_statuses:
        row = _fetch(conn, session_id)
        assert row["status"] == original_status, (
            f"Terminal row id={session_id} status changed from {original_status!r}"
        )


def test_reconcile_return_count_matches_rows_changed(conn: sqlite3.Connection) -> None:
    """Return value of reconcile_crashed_sessions equals the number reconciled."""
    # Insert two non-terminal and two terminal rows.
    _insert_with_status(conn, "active")
    _insert_with_status(conn, "followup")
    _insert_with_status(conn, "completed")
    _insert_with_status(conn, "cancelled")

    count = reconcile_crashed_sessions(conn)
    assert count == 2


def test_reconcile_no_rows(conn: sqlite3.Connection) -> None:
    """reconcile_crashed_sessions returns 0 when no non-terminal rows exist."""
    count = reconcile_crashed_sessions(conn)
    assert count == 0


def test_reconcile_already_crashed_not_double_counted(conn: sqlite3.Connection) -> None:
    """A row already 'crashed' is not re-reconciled (it is terminal)."""
    _insert_with_status(conn, "crashed")
    count = reconcile_crashed_sessions(conn)
    assert count == 0
