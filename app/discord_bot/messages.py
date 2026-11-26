"""Best-effort Discord message calls (delete / edit) that log instead of raising."""

from __future__ import annotations

import logging
from collections.abc import Awaitable

import discord

# What a message delete/edit raises when the message is gone, the bot lacks
# permission, or Discord rejects the request.
MESSAGE_CALL_ERRORS = (discord.NotFound, discord.Forbidden, discord.HTTPException)


async def best_effort(
    call: Awaitable[object], log: logging.Logger, msg: str, *args: object
) -> bool:
    """Await *call*; on a Discord message error log WARNING and return ``False``.

    *log* is the caller's module logger, so records keep their usual logger
    name. *msg* and *args* are passed to ``log.warning`` unchanged (lazy
    ``%``-formatting). Returns ``True`` when the call succeeded.
    """
    try:
        await call
    except MESSAGE_CALL_ERRORS:
        log.warning(msg, *args)
        return False
    return True
