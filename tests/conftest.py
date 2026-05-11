"""Pytest session fixtures shared across all test modules.

Sets a stub DISCORD_BOT_TOKEN in the process environment before any
app.* import occurs. app.config raises RuntimeError at import time if
the var is absent; tests must never require a live token.
"""

import os
import sqlite3

import pytest

# Must be set before any app.* import — conftest.py is loaded first.
os.environ.setdefault("DISCORD_BOT_TOKEN", "test-stub-token")

from app.db import init_db  # noqa: E402 — must come after env setup


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """Fresh in-memory DB with schema applied."""
    return init_db(":memory:")
