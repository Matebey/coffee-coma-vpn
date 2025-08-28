from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import yaml
import redis

# Загрузка конфига
with open('config.yaml') as f:
    config = yaml.safe_load(f)

# Подключение к Redis
r = redis.Redis(
    host=config['redis']['host'],
    port=config['redis']['port'],
    decode_responses=True
)

def admin_start(update: Update, context: CallbackContext):
    """Команда /admin для админ-панели"""
    if update.message.from_user.id != config['admin_id']:
        update.message.reply_text("❌ Доступ запрещен!")
        return
    
    keyboard = [
        ["📊 Статистика", "👥 Пользователи"],
        ["🔄 Перезапустить", "🧹 Очистка"]
    ]
    
    update.message.reply_text(
        "⚙️ *Админ-панель Coffee Coma VPN*",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode='Markdown'
    )

def handle_admin_command(update: Update, context: CallbackContext):
    """Обработчик команд админ-панели"""
    if update.message.from_user.id != config['admin_id']:
        return
    
    text = update.message.text
    
    if text == "📊 Статистика":
        total_users = len(r.keys("user:*"))
        active_users = len([key for key in r.keys("user:*") if r.hget(key, 'active') == 'true'])
        
        update.message.reply_text(
            f"📊 *Статистика системы*\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"✅ Активных подписок: {active_users}\n"
            f"🎁 Пробных периодов: {len([key for key in r.keys('user:*') if r.hget(key, 'is_trial') == 'True'])}",
            parse_mode='Markdown'
        )
    
    elif text == "👥 Пользователи":
        users = []
        for key in r.keys("user:*"):
            user_data = r.hgetall(key)
            user_id = key.split(':')[1]
            users.append(f"ID: {user_id}, Активен: {user_data.get('active', 'нет данных')}")
        
        update.message.reply_text(f"Пользователи:\n" + "\n".join(users[:10]))

def main():
    updater = Updater(config['tokens']['admin'])
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler('admin', admin_start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_admin_command))
    
    print("Админ-бот запущен!")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()