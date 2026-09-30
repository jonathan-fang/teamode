"""Environment-variable loader for TeaMode."""

import logging
import os
from datetime import timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from app.constants import DEFAULT_TIMEZONE

load_dotenv()

logger = logging.getLogger(__name__)

_raw_token = os.environ.get("DISCORD_BOT_TOKEN", "")
if not _raw_token:
    raise RuntimeError("DISCORD_BOT_TOKEN is required")

DISCORD_BOT_TOKEN: str = _raw_token
TEAMODE_DB_PATH: str = os.environ.get("TEAMODE_DB_PATH", "./sessions.db")


def _load_timezone(raw_tz: str) -> tzinfo:
    """Resolve the configured timezone, falling back on invalid input.

    Unset/empty ``raw_tz`` falls back to ``DEFAULT_TIMEZONE``. An
    invalid IANA name logs a WARNING and falls back to
    ``DEFAULT_TIMEZONE``. If even the default is unavailable, falls
    back to UTC with a WARNING.
    """
    tz_name = raw_tz or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        if raw_tz:
            logger.warning(
                "Invalid TEAMODE_TIMEZONE %r — falling back to %s",
                raw_tz,
                DEFAULT_TIMEZONE,
            )
        try:
            return ZoneInfo(DEFAULT_TIMEZONE)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning(
                "Default timezone %r unavailable — falling back to UTC",
                DEFAULT_TIMEZONE,
            )
            return timezone.utc


TEAMODE_TIMEZONE: tzinfo = _load_timezone(os.environ.get("TEAMODE_TIMEZONE", ""))

# Comma-separated guild IDs for guild-scoped slash command registration
# (instant propagation during dev). When empty the bot logs a warning and
# skips command registration — global registration requires up to one hour to
# propagate and is not suitable for active development.
# Example: TEAMODE_DEV_GUILD_ID=111111111111111111,222222222222222222
_raw_guild_ids: str = os.environ.get("TEAMODE_DEV_GUILD_ID", "")
TEAMODE_DEV_GUILD_IDS: list[int] = [
    int(gid.strip()) for gid in _raw_guild_ids.split(",") if gid.strip()
]
