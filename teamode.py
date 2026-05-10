"""TeaMode entry point — orchestration only, no business logic."""

import logging

import app.db as db
from app.bot import TeaModeBot
from app.config import DISCORD_BOT_TOKEN, TEAMODE_DB_PATH
from app.session import SessionRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    # Redact token to last-four characters for startup log.
    last_four = DISCORD_BOT_TOKEN[-4:]
    logger.info("Starting TeaMode (Ocha) — token: ****%s", last_four)

    conn = db.init_db(TEAMODE_DB_PATH)

    reconciled = db.reconcile_crashed_sessions(conn)
    logger.info("Reconciled %d crashed session(s) on startup", reconciled)

    registry = SessionRegistry(conn)
    bot = TeaModeBot(conn=conn, registry=registry)
    bot.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()
