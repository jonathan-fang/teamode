"""Read helpers for the bot's in-memory runtime state in tests.

``sess`` / ``chan`` never create an entry: a session or channel with no
runtime reads as an empty one, so "was this cleared?" checks work both
while a session is live and after its runtime was dropped. Seed state with
``bot._rt.session(sid).<field> = ...`` / ``bot._rt.channel(cid)...``.
"""

from __future__ import annotations

from typing import Any

from app.discord_bot.runtime import ChannelRuntime, SessionRuntime


def sess(bot: Any, session_id: int) -> SessionRuntime:
    """Return *session_id*'s runtime, or an empty one if it has none."""
    return bot._rt.peek_session(session_id) or SessionRuntime()


def chan(bot: Any, channel_id: int) -> ChannelRuntime:
    """Return *channel_id*'s runtime, or an empty one if it has none."""
    return bot._rt.peek_channel(channel_id) or ChannelRuntime()


def must[T](value: T | None) -> T:
    """Return *value*, failing the test if it is ``None``."""
    assert value is not None
    return value
