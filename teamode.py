"""TeaMode entry point — orchestration only, no business logic."""

import logging
import shutil
import sys

import app.db as db
from app.constants import PID_FILE_PATH
from app.discord_bot import TeaModeBot
from app.config import DISCORD_BOT_TOKEN, TEAMODE_DB_PATH
from app.pidlock import acquire_pid_lock
from app.session import SessionRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

FFMPEG_MISSING_WARNING = (
    "ffmpeg not found on PATH — reverie playback will fail."
    " Install ffmpeg before starting a session."
)


def check_ffmpeg() -> None:
    """Log a WARNING if ffmpeg is not on PATH. Non-fatal."""
    if shutil.which("ffmpeg") is None:
        logger.warning(FFMPEG_MISSING_WARNING)


def main() -> None:
    sys.stdout.write("\x1b]0;TeaMode\x07")
    sys.stdout.flush()

    acquire_pid_lock(PID_FILE_PATH)
    check_ffmpeg()

    # Redact token to last-four characters for startup log.
    last_four = DISCORD_BOT_TOKEN[-4:]
    logger.info("Starting TeaMode (Ocha) — token: ****%s", last_four)

    conn = db.init_db(TEAMODE_DB_PATH)

    # Reconciliation must run after init_db (table must exist) and before the
    # gateway starts (avoid racing a fresh /teamode invocation).
    reconciled = db.reconcile_crashed_sessions(conn)
    logger.info("Reconciled %d crashed session(s) on startup", reconciled)

    registry = SessionRegistry(conn)
    bot = TeaModeBot(conn=conn, registry=registry)
    bot.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()
