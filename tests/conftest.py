"""Pytest session fixtures shared across all test modules.

Sets a stub DISCORD_BOT_TOKEN in the process environment before any
app.* import occurs. app.config raises RuntimeError at import time if
the var is absent; tests must never require a live token.
"""

import os

# Must be set before any app.* import — conftest.py is loaded first.
os.environ.setdefault("DISCORD_BOT_TOKEN", "test-stub-token")
