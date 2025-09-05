import logging
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from config import load_config
from database import init_db
from handlers import (
    start, show_my_configs, handle_screenshot, 
    admin_command, button_handler
)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    try:
        # Инициализация
        config = load_config()
        init_db()
        
        # Создание приложения
        application = Application.builder().token(config['bot_token']).build()
        
        # Добавление обработчиков
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("admin", admin_command))
        application.add_handler(CommandHandler("myconfigs", show_my_configs))
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(MessageHandler(filters.PHOTO, handle_screenshot))
        
        # Запуск бота
        logger.info("Запуск OpenVPN бота...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise

if __name__ == '__main__':
    main()
