import logging
from telegram.ext import Application, CommandHandler

from config import BOT_TOKEN
from handlers import (
    start, signal_command, crypto_command,
    help_command, status_command, build_setbalance_handler,
    approve_command, remove_command, ban_command, members_command,
)
from scheduler import start_scheduler

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()],
)


async def post_init(app):
    await start_scheduler(app)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set.")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(build_setbalance_handler())
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("signal",  signal_command))
    app.add_handler(CommandHandler("crypto",  crypto_command))
    app.add_handler(CommandHandler("help",    help_command))
    app.add_handler(CommandHandler("status",  status_command))
    app.add_handler(CommandHandler("approve", approve_command))
    app.add_handler(CommandHandler("remove",  remove_command))
    app.add_handler(CommandHandler("ban",     ban_command))
    app.add_handler(CommandHandler("members", members_command))

    logging.info("🤖 SamSignals Bot starting…")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()