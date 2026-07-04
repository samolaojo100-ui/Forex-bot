import logging
from telegram.ext import Application, CommandHandler

from config import BOT_TOKEN
from handlers import (
    start, signal_command, crypto_command, stocks_command,
    help_command, status_command,
    build_setbalance_handler,
    approve_command,
    debug_command,
)
from scheduler import start_scheduler
from db import init_db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(app: Application):
    await start_scheduler(app)
    logger.info("✅ TrendGuard AI bot started")


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("signal",   signal_command))
    app.add_handler(CommandHandler("crypto",   crypto_command))
    app.add_handler(CommandHandler("stocks",   stocks_command))
    app.add_handler(CommandHandler("help",     help_command))
    app.add_handler(CommandHandler("status",   status_command))
    app.add_handler(CommandHandler("approve",  approve_command))
    app.add_handler(CommandHandler("debug",    debug_command))
    app.add_handler(build_setbalance_handler())

    logger.info("🚀 Starting TrendGuard AI...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
