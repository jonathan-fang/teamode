"""Logged background-task spawning.

Every ``asyncio.create_task`` call in the Discord layer that isn't awaited
by its caller goes through :func:`spawn_logged` instead, so a failure
inside a background task (post-countdown follow-up, the follow-up
watchdog, solo grace, pending expiry) is always logged rather than
silently dropped.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)


def spawn_logged(coro: Coroutine[Any, Any, None], *, name: str) -> asyncio.Task[None]:
    """Schedule *coro* as a task that logs unexpected exceptions.

    ``asyncio.CancelledError`` is expected whenever the task is cancelled
    (e.g. a watchdog superseded by an earlier event) and is re-raised
    untouched. Any other exception is caught and logged via
    ``logger.exception`` so it is never silently dropped.
    """

    async def _runner() -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Background task %r failed", name)

    return asyncio.create_task(_runner(), name=name)
