import logging
import asyncio
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from config import BOT_TOKEN
from handlers import (
    start, signal_command, help_command, status_command,
    build_setbalance_handler,
)
from scheduler import start_scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Conversation handler MUST be registered before plain command handlers
    app.add_handler(build_setbalance_handler())

    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("signal", signal_command))
    app.add_handler(CommandHandler("help",   help_command))
    app.add_handler(CommandHandler("status", status_command))

    await start_scheduler(app)

    logger.info("🤖 Forex Signal Bot started!")
    await app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    asyncio.run(main())
