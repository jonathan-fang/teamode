"""Tests for app/discord_bot/messages.py — the best-effort message-call helper."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from app.discord_bot.messages import best_effort

_LOG = logging.getLogger("tests.messages")


@pytest.mark.asyncio
async def test_best_effort_success_returns_true(
    caplog: pytest.LogCaptureFixture,
) -> None:
    call = AsyncMock(return_value=None)
    with caplog.at_level(logging.WARNING, logger="tests.messages"):
        assert await best_effort(call(), _LOG, "Failed %s", 1) is True
    assert caplog.records == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        discord.NotFound(MagicMock(status=404), "gone"),
        discord.Forbidden(MagicMock(status=403), "no perms"),
        discord.HTTPException(MagicMock(status=500), "boom"),
    ],
)
async def test_best_effort_discord_error_logs_on_caller_logger(
    exc: discord.HTTPException, caplog: pytest.LogCaptureFixture
) -> None:
    call = AsyncMock(side_effect=exc)
    with caplog.at_level(logging.WARNING, logger="tests.messages"):
        assert (
            await best_effort(call(), _LOG, "Failed to delete %s in %s", 7, 9) is False
        )
    [record] = caplog.records
    assert record.name == "tests.messages"
    assert record.levelno == logging.WARNING
    assert record.getMessage() == "Failed to delete 7 in 9"


@pytest.mark.asyncio
async def test_best_effort_unrelated_error_propagates() -> None:
    call = AsyncMock(side_effect=ValueError("bug"))
    with pytest.raises(ValueError, match="bug"):
        await best_effort(call(), _LOG, "Failed")
