"""Environment-variable loader for TeaMode."""

import os

from dotenv import load_dotenv

load_dotenv()

_raw_token = os.environ.get("DISCORD_BOT_TOKEN", "")
if not _raw_token:
    raise RuntimeError("DISCORD_BOT_TOKEN is required")

DISCORD_BOT_TOKEN: str = _raw_token
TEAMODE_DB_PATH: str = os.environ.get("TEAMODE_DB_PATH", "./sessions.db")
