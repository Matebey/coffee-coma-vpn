import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.contrib.middlewares.logging import LoggingMiddleware

from bot.utils.config import Config
from bot.database.db import init_db, close_db
from bot.handlers import register_handlers

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def on_startup(dp):
    await init_db()
    logger.info("Bot started")

async def on_shutdown(dp):
    await close_db()
    logger.info("Bot stopped")

def main():
    bot = Bot(token=Config.BOT_TOKEN, parse_mode=types.ParseMode.HTML)
    storage = MemoryStorage()
    dp = Dispatcher(bot, storage=storage)
    
    dp.middleware.setup(LoggingMiddleware())
    
    register_handlers(dp)
    
    dp.register_startup_handler(on_startup)
    dp.register_shutdown_handler(on_shutdown)
    
    try:
        asyncio.run(dp.start_polling())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")

if __name__ == '__main__':
    main()
