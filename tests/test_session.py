"""Tests for app.session — SessionState, Session, and SessionRegistry."""

import sqlite3

import pytest

from app.db import init_db
from app.session import InvalidTransition, Session, SessionRegistry, SessionState


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """Fresh in-memory DB with schema applied."""
    return init_db(":memory:")


@pytest.fixture()
def registry(conn: sqlite3.Connection) -> SessionRegistry:
    """SessionRegistry backed by a fresh in-memory DB."""
    return SessionRegistry(conn)


def _fetch(conn: sqlite3.Connection, session_id: int) -> dict:
    cur = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cur.fetchone()
    assert row is not None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def _make_session(registry: SessionRegistry, text_channel_id: str = "222") -> Session:
    """Create a minimal pending session and return it."""
    return registry.create_pending_session(
        guild_id="111",
        text_channel_id=text_channel_id,
        voice_channel_id="333",
        facilitator_id="444",
    )


# ---------------------------------------------------------------------------
# Happy-path: full lifecycle walk
# ---------------------------------------------------------------------------


def test_happy_path_full_lifecycle(
    conn: sqlite3.Connection, registry: SessionRegistry
) -> None:
    """Walk a session through the full happy-path lifecycle.

    After each transition, assert both in-memory Session.state and the
    SQLite row status column.
    """
    # Step 1: create pending
    session = _make_session(registry)
    assert session.state == SessionState.PENDING
    assert _fetch(conn, session.session_id)["status"] == "pending"

    sid = session.session_id

    # Step 2: set duration (state stays PENDING)
    registry.set_duration(session_id=sid, duration_minutes=25)
    assert session.state == SessionState.PENDING
    assert session.duration_minutes == 25
    row = _fetch(conn, sid)
    assert row["status"] == "pending"
    assert row["duration_minutes"] == 25

    # Step 3: set intention → INTENTION_SET
    registry.set_intention(session_id=sid, intention="Finish the PR")
    assert session.state == SessionState.INTENTION_SET
    assert session.intention == "Finish the PR"
    row = _fetch(conn, sid)
    assert row["status"] == "intention_set"
    assert row["intention"] == "Finish the PR"

    # Step 4: mark active → ACTIVE
    registry.mark_active(session_id=sid, started_at="2026-05-10T12:00:00+00:00")
    assert session.state == SessionState.ACTIVE
    row = _fetch(conn, sid)
    assert row["status"] == "active"
    assert row["started_at"] == "2026-05-10T12:00:00+00:00"

    # Step 5: mark followup → FOLLOWUP
    registry.mark_followup(session_id=sid)
    assert session.state == SessionState.FOLLOWUP
    assert _fetch(conn, sid)["status"] == "followup"

    # Step 6: mark completed → COMPLETED (terminal)
    registry.mark_completed(
        session_id=sid,
        completed_intention=1,
        followup_note=None,
        ended_at="2026-05-10T13:00:00+00:00",
    )
    assert session.state == SessionState.COMPLETED
    row = _fetch(conn, sid)
    assert row["status"] == "completed"
    assert row["completed_intention"] == 1
    assert row["followup_note"] is None
    assert row["ended_at"] == "2026-05-10T13:00:00+00:00"


# ---------------------------------------------------------------------------
# Refusal paths — invalid prior states
# ---------------------------------------------------------------------------


def test_mark_active_from_pending_raises(registry: SessionRegistry) -> None:
    """mark_active requires INTENTION_SET; PENDING should raise."""
    session = _make_session(registry)
    with pytest.raises(InvalidTransition):
        registry.mark_active(session_id=session.session_id)


def test_mark_followup_from_pending_raises(registry: SessionRegistry) -> None:
    """mark_followup requires ACTIVE; PENDING should raise."""
    session = _make_session(registry)
    with pytest.raises(InvalidTransition):
        registry.mark_followup(session_id=session.session_id)


def test_mark_completed_from_active_raises(registry: SessionRegistry) -> None:
    """mark_completed requires FOLLOWUP; ACTIVE should raise."""
    session = _make_session(registry)
    sid = session.session_id
    registry.set_duration(session_id=sid, duration_minutes=25)
    registry.set_intention(session_id=sid, intention="Do work")
    registry.mark_active(session_id=sid)
    with pytest.raises(InvalidTransition):
        registry.mark_completed(
            session_id=sid, completed_intention=1, followup_note=None
        )


def test_set_intention_from_intention_set_raises(registry: SessionRegistry) -> None:
    """set_intention requires PENDING; INTENTION_SET should raise."""
    session = _make_session(registry)
    sid = session.session_id
    registry.set_intention(session_id=sid, intention="First")
    with pytest.raises(InvalidTransition):
        registry.set_intention(session_id=sid, intention="Second")


def test_transition_from_terminal_raises(registry: SessionRegistry) -> None:
    """Any transition on a terminal session should raise InvalidTransition."""
    session = _make_session(registry)
    sid = session.session_id
    registry.mark_cancelled(session_id=sid)
    assert session.state == SessionState.CANCELLED

    with pytest.raises(InvalidTransition):
        registry.set_duration(session_id=sid, duration_minutes=25)

    with pytest.raises(InvalidTransition):
        registry.set_intention(session_id=sid, intention="x")

    with pytest.raises(InvalidTransition):
        registry.mark_cancelled(session_id=sid)


def test_mark_handoff_from_pending_raises(registry: SessionRegistry) -> None:
    """mark_handoff is not valid from PENDING."""
    session = _make_session(registry)
    with pytest.raises(InvalidTransition):
        registry.mark_handoff(
            session_id=session.session_id, handoff_facilitator_id="999"
        )


# ---------------------------------------------------------------------------
# Parallel-channel safety
# ---------------------------------------------------------------------------


def test_parallel_channels_independent(
    conn: sqlite3.Connection, registry: SessionRegistry
) -> None:
    """Two sessions in different text channels advance without interfering."""
    s1 = registry.create_pending_session(
        guild_id="111",
        text_channel_id="ch-A",
        voice_channel_id="333",
        facilitator_id="u1",
    )
    s2 = registry.create_pending_session(
        guild_id="111",
        text_channel_id="ch-B",
        voice_channel_id="334",
        facilitator_id="u2",
    )

    # Advance s1 further than s2.
    registry.set_duration(session_id=s1.session_id, duration_minutes=25)
    registry.set_intention(session_id=s1.session_id, intention="s1 work")
    registry.mark_active(session_id=s1.session_id)

    registry.set_duration(session_id=s2.session_id, duration_minutes=10)

    # Assert independent in-memory states.
    assert s1.state == SessionState.ACTIVE
    assert s2.state == SessionState.PENDING

    # Assert independent SQLite rows.
    row1 = _fetch(conn, s1.session_id)
    row2 = _fetch(conn, s2.session_id)
    assert row1["status"] == "active"
    assert row2["status"] == "pending"
    assert row1["facilitator_id"] == "u1"
    assert row2["facilitator_id"] == "u2"

    # Registry lookups do not collide.
    assert registry.find_active_in_text_channel("ch-A") is s1
    assert registry.find_active_in_text_channel("ch-B") is s2


# ---------------------------------------------------------------------------
# Channel exclusivity
# ---------------------------------------------------------------------------


def test_channel_exclusivity_blocks_second_pending(registry: SessionRegistry) -> None:
    """Creating a second session in the same channel raises while first is active."""
    _make_session(registry, text_channel_id="ch-X")
    with pytest.raises(InvalidTransition):
        _make_session(registry, text_channel_id="ch-X")


def test_channel_exclusivity_allows_after_terminal(registry: SessionRegistry) -> None:
    """After the first session reaches a terminal state, a new one can be created."""
    s1 = _make_session(registry, text_channel_id="ch-Y")
    registry.mark_cancelled(session_id=s1.session_id)
    assert s1.state == SessionState.CANCELLED

    # The channel should now be free.
    s2 = registry.create_pending_session(
        guild_id="111",
        text_channel_id="ch-Y",
        voice_channel_id="333",
        facilitator_id="u2",
    )
    assert s2.state == SessionState.PENDING
    assert s2.session_id != s1.session_id


def test_channel_exclusivity_followup_timeout_frees_channel(
    registry: SessionRegistry,
) -> None:
    """FOLLOWUP_TIMEOUT (terminal) also frees the channel."""
    session = _make_session(registry)
    sid = session.session_id
    registry.set_duration(session_id=sid, duration_minutes=25)
    registry.set_intention(session_id=sid, intention="Work")
    registry.mark_active(session_id=sid)
    registry.mark_followup(session_id=sid)
    registry.mark_followup_timeout(session_id=sid)

    assert session.state == SessionState.FOLLOWUP_TIMEOUT
    assert registry.find_active_in_text_channel("222") is None

    # New session in same channel succeeds.
    s2 = _make_session(registry, text_channel_id="222")
    assert s2.state == SessionState.PENDING


# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------


def test_handoff_from_active(
    conn: sqlite3.Connection, registry: SessionRegistry
) -> None:
    """mark_handoff from ACTIVE updates facilitator and handoff fields without advancing state."""
    session = _make_session(registry)
    sid = session.session_id
    registry.set_duration(session_id=sid, duration_minutes=25)
    registry.set_intention(session_id=sid, intention="Work")
    registry.mark_active(session_id=sid)

    assert session.state == SessionState.ACTIVE
    assert session.facilitator_id == "444"

    registry.mark_handoff(session_id=sid, handoff_facilitator_id="999")

    # State must not advance.
    assert session.state == SessionState.ACTIVE
    # In-memory facilitator fields updated.
    assert session.handoff_facilitator_id == "999"
    assert session.facilitator_id == "999"

    # SQLite row updated.
    row = _fetch(conn, sid)
    assert row["handoff_facilitator_id"] == "999"
    assert row["status"] == "active"

    # Subsequent transitions still work.
    registry.mark_followup(session_id=sid)
    assert session.state == SessionState.FOLLOWUP


def test_handoff_from_intention_set(registry: SessionRegistry) -> None:
    """mark_handoff is valid from INTENTION_SET."""
    session = _make_session(registry)
    sid = session.session_id
    registry.set_intention(session_id=sid, intention="Work")
    assert session.state == SessionState.INTENTION_SET

    registry.mark_handoff(session_id=sid, handoff_facilitator_id="888")
    assert session.state == SessionState.INTENTION_SET
    assert session.handoff_facilitator_id == "888"


def test_handoff_from_followup(registry: SessionRegistry) -> None:
    """mark_handoff is valid from FOLLOWUP."""
    session = _make_session(registry)
    sid = session.session_id
    registry.set_duration(session_id=sid, duration_minutes=25)
    registry.set_intention(session_id=sid, intention="Work")
    registry.mark_active(session_id=sid)
    registry.mark_followup(session_id=sid)

    registry.mark_handoff(session_id=sid, handoff_facilitator_id="777")
    assert session.state == SessionState.FOLLOWUP
    assert session.facilitator_id == "777"


# ---------------------------------------------------------------------------
# get / find_active_in_text_channel lookups
# ---------------------------------------------------------------------------


def test_get_returns_session(registry: SessionRegistry) -> None:
    """get() returns the session by id."""
    session = _make_session(registry)
    assert registry.get(session.session_id) is session


def test_get_unknown_id_returns_none(registry: SessionRegistry) -> None:
    """get() returns None for an unknown id."""
    assert registry.get(9999) is None


def test_find_active_unknown_channel_returns_none(registry: SessionRegistry) -> None:
    """find_active_in_text_channel returns None for a channel with no session."""
    assert registry.find_active_in_text_channel("ch-unknown") is None


def test_find_active_after_cancel_returns_none(registry: SessionRegistry) -> None:
    """find_active_in_text_channel returns None once the session is cancelled."""
    session = _make_session(registry)
    assert registry.find_active_in_text_channel("222") is session
    registry.mark_cancelled(session_id=session.session_id)
    assert registry.find_active_in_text_channel("222") is None


# ---------------------------------------------------------------------------
# Unknown session_id on transitions
# ---------------------------------------------------------------------------


def test_set_duration_unknown_id_raises(registry: SessionRegistry) -> None:
    """Transitions on an unknown session_id raise ValueError."""
    with pytest.raises(ValueError, match="No session with id="):
        registry.set_duration(session_id=9999, duration_minutes=25)
