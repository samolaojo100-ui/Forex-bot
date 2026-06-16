import logging
from telegram.ext import Application, CommandHandler
from config import BOT_TOKEN
from handlers import (
    start, signal_command, crypto_command,
    help_command, status_command, build_setbalance_handler,
)
from scheduler import start_scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()],
)

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(build_setbalance_handler())
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("signal",  signal_command))
    app.add_handler(CommandHandler("crypto",  crypto_command))
    app.add_handler(CommandHandler("help",    help_command))
    app.add_handler(CommandHandler("status",  status_command))

    app.post_init = start_scheduler
    app.run_polling(allowed_updates=["message"])

if __name__ == "__main__":
    main()
