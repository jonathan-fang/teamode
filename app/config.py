"""Environment-variable loader for TeaMode."""

import os

from dotenv import load_dotenv

load_dotenv()

_raw_token = os.environ.get("DISCORD_BOT_TOKEN", "")
if not _raw_token:
    raise RuntimeError("DISCORD_BOT_TOKEN is required")

DISCORD_BOT_TOKEN: str = _raw_token
TEAMODE_DB_PATH: str = os.environ.get("TEAMODE_DB_PATH", "./sessions.db")

# Comma-separated guild IDs for guild-scoped slash command registration
# (instant propagation during dev). When empty the bot logs a warning and
# skips command registration — global registration requires up to one hour to
# propagate and is not suitable for active development.
# Example: TEAMODE_DEV_GUILD_ID=111111111111111111,222222222222222222
_raw_guild_ids: str = os.environ.get("TEAMODE_DEV_GUILD_ID", "")
TEAMODE_DEV_GUILD_IDS: list[int] = [
    int(gid.strip()) for gid in _raw_guild_ids.split(",") if gid.strip()
]
