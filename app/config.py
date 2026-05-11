"""Environment-variable loader for TeaMode."""

import os

from dotenv import load_dotenv

load_dotenv()

_raw_token = os.environ.get("DISCORD_BOT_TOKEN", "")
if not _raw_token:
    raise RuntimeError("DISCORD_BOT_TOKEN is required")

DISCORD_BOT_TOKEN: str = _raw_token
TEAMODE_DB_PATH: str = os.environ.get("TEAMODE_DB_PATH", "./sessions.db")

# Guild ID for guild-scoped slash command registration (instant propagation
# during dev). When None the bot logs a warning and skips command registration
# — global registration requires up to one hour to propagate and is not
# suitable for active development. Set this to your Discord dev server's guild
# ID while developing.
TEAMODE_DEV_GUILD_ID: str | None = os.environ.get("TEAMODE_DEV_GUILD_ID") or None
