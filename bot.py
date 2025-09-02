import logging
import sqlite3
import os
import subprocess
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext, MessageHandler, Filters
import config

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        username TEXT,
        full_name TEXT,
        balance INTEGER DEFAULT 0,
        trial_used INTEGER DEFAULT 0,
        referral_code TEXT,
        referred_by INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица ключей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS keys (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        key_name TEXT,
        key_data TEXT,
        expires_at DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        is_active INTEGER DEFAULT 1
    )
    ''')
    
    # Таблица платежей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        amount INTEGER,
        status TEXT,
        payment_method TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    conn.commit()
    conn.close()

# Генерация конфига OpenVPN
def generate_ovpn_config(client_name):
    try:
        # Генерируем ключи для клиента
        subprocess.run([
            'bash', '/etc/openvpn/easy-rsa/easyrsa',
            'build-client-full', client_name, 'nopass'
        ], check=True, cwd='/etc/openvpn/easy-rsa/')
        
        # Создаем конфиг файл
        with open(config.OVPN_CONFIG_TEMPLATE, 'r') as template_file:
            config_content = template_file.read()
        
        # Добавляем ключи
        with open(f"{config.OVPN_KEYS_DIR}{client_name}.crt", 'r') as cert_file:
            cert_data = cert_file.read()
        
        with open(f"{config.OVPN_KEYS_DIR}{client_name}.key", 'r') as key_file:
            key_data = key_file.read()
        
        with open(f"{config.OVPN_KEYS_DIR}ca.crt", 'r') as ca_file:
            ca_data = ca_file.read()
        
        # Заменяем плейсхолдеры в шаблоне
        config_content = config_content.replace('<ca>', ca_data)
        config_content = config_content.replace('<cert>', cert_data)
        config_content = config_content.replace('<key>', key_data)
        
        # Сохраняем конфиг
        config_path = f"{config.OVPN_DIR}client-configs/{client_name}.ovpn"
        with open(config_path, 'w') as config_file:
            config_file.write(config_content)
        
        return config_path
    except Exception as e:
        logger.error(f"Error generating OVPN config: {e}")
        return None

# Команда /start
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()
    
    # Проверяем, есть ли пользователь в базе
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user.id,))
    existing_user = cursor.fetchone()
    
    if not existing_user:
        # Создаем нового пользователя
        referral_code = str(user.id)[-6:]
        cursor.execute(
            'INSERT INTO users (user_id, username, full_name, referral_code) VALUES (?, ?, ?, ?)',
            (user.id, user.username, user.full_name, referral_code)
        )
        
        # Даем пробный период
        trial_expires = datetime.now() + timedelta(days=config.TRIAL_PERIOD_DAYS)
        key_name = f"trial_{user.id}"
        
        # Генерируем конфиг
        config_path = generate_ovpn_config(key_name)
        if config_path:
            with open(config_path, 'rb') as config_file:
                # Сохраняем ключ в базе
                cursor.execute(
                    'INSERT INTO keys (user_id, key_name, key_data, expires_at) VALUES (?, ?, ?, ?)',
                    (user.id, key_name, config_path, trial_expires)
                )
                
                # Отправляем конфиг пользователю
                context.bot.send_document(
                    chat_id=user.id,
                    document=config_file,
                    caption=f"Ваш пробный ключ на {config.TRIAL_PERIOD_DAYS} дней!"
                )
        
        # Проверяем реферальную систему
        if context.args:
            referrer_id = int(context.args[0])
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (referrer_id,))
            referrer = cursor.fetchone()
            
            if referrer:
                # Даем бонус рефереру
                bonus_expires = datetime.now() + timedelta(days=config.REFERRAL_BONUS_DAYS)
                bonus_key_name = f"ref_bonus_{referrer_id}"
                
                config_path = generate_ovpn_config(bonus_key_name)
                if config_path:
                    with open(config_path, 'rb') as config_file:
                        cursor.execute(
                            'INSERT INTO keys (user_id, key_name, key_data, expires_at) VALUES (?, ?, ?, ?)',
                            (referrer_id, bonus_key_name, config_path, bonus_expires)
                        )
                        
                        # Отправляем уведомление рефереру
                        context.bot.send_message(
                            chat_id=referrer_id,
                            text="Вы получили бонусный ключ за приглашение друга!"
                        )
        
        conn.commit()
    
    conn.close()
    
    # Показываем главное меню
    show_main_menu(update, context)

# Главное меню
def show_main_menu(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("🛒 Купить доступ", callback_data='buy')],
        [InlineKeyboardButton("🔑 Мои ключи", callback_data='my_keys')],
        [InlineKeyboardButton("👤 Мой профиль", callback_data='profile')],
        [InlineKeyboardButton("🎁 Бесплатный ключ", callback_data='free_key')]
    ]
    
    if update.effective_user.id == config.ADMIN_ID:
        keyboard.append([InlineKeyboardButton("⚙️ Админ панель", callback_data='admin')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        update.callback_query.edit_message_text(
            text=config.MESSAGES['menu'],
            reply_markup=reply_markup
        )
    else:
        update.message.reply_text(
            text=config.MESSAGES['menu'],
            reply_markup=reply_markup
        )

# Обработчик callback запросов
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    if query.data == 'buy':
        show_buy_options(update, context)
    elif query.data == 'my_keys':
        show_my_keys(update, context)
    elif query.data == 'profile':
        show_profile(update, context)
    elif query.data == 'free_key':
        get_free_key(update, context)
    elif query.data == 'admin':
        show_admin_panel(update, context)
    elif query.data == 'back_to_menu':
        show_main_menu(update, context)
    elif query.data.startswith('admin_'):
        handle_admin_actions(update, context, query.data)

# Показ вариантов покупки
def show_buy_options(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("1 месяц - 300 руб.", callback_data='buy_1')],
        [InlineKeyboardButton("3 месяца - 800 руб.", callback_data='buy_3')],
        [InlineKeyboardButton("6 месяцев - 1500 руб.", callback_data='buy_6')],
        [InlineKeyboardButton("Назад", callback_data='back_to_menu')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.callback_query.edit_message_text(
        text=config.MESSAGES['buy'],
        reply_markup=reply_markup
    )

# Показ профиля пользователя
def show_profile(update: Update, context: CallbackContext):
    user = update.effective_user
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        'SELECT balance, referral_code FROM users WHERE user_id = ?',
        (user.id,)
    )
    user_data = cursor.fetchone()
    
    if user_data:
        balance, referral_code = user_data
        referral_link = f"https://t.me/{context.bot.username}?start={user.id}"
        
        profile_text = f"""
👤 Ваш профиль:

💰 Баланс: {balance} руб.
🔗 Реферальная ссылка: {referral_link}
📊 Ваш реферальный код: {referral_code}

Приглашайте друзей и получайте бонусы!
        """
        
        keyboard = [[InlineKeyboardButton("Назад", callback_data='back_to_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.callback_query.edit_message_text(
            text=profile_text,
            reply_markup=reply_markup
        )
    
    conn.close()

# Админ панель
def show_admin_panel(update: Update, context: CallbackContext):
    if update.effective_user.id != config.ADMIN_ID:
        update.callback_query.edit_message_text("У вас нет доступа к админ панели!")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("🔑 Управление ключами", callback_data='admin_keys')],
        [InlineKeyboardButton("⚙️ Настройки сервера", callback_data='admin_settings')],
        [InlineKeyboardButton("💳 Настройки оплаты", callback_data='admin_payment')],
        [InlineKeyboardButton("🎁 Выдать бесплатный ключ", callback_data='admin_give_key')],
        [InlineKeyboardButton("Назад", callback_data='back_to_menu')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.callback_query.edit_message_text(
        text=config.MESSAGES['admin'],
        reply_markup=reply_markup
    )

# Обработка действий админа
def handle_admin_actions(update: Update, context: CallbackContext, action: str):
    if update.effective_user.id != config.ADMIN_ID:
        return
    
    if action == 'admin_stats':
        show_admin_stats(update, context)
    elif action == 'admin_keys':
        show_key_management(update, context)
    elif action == 'admin_settings':
        show_server_settings(update, context)
    elif action == 'admin_payment':
        show_payment_settings(update, context)
    elif action == 'admin_give_key':
        ask_for_user_to_give_key(update, context)

# Показать статистику админу
def show_admin_stats(update: Update, context: CallbackContext):
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()
    
    # Получаем статистику
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM keys WHERE is_active = 1')
    active_keys = cursor.fetchone()[0]
    
    cursor.execute('SELECT SUM(amount) FROM payments WHERE status = "completed"')
    total_revenue = cursor.fetchone()[0] or 0
    
    stats_text = f"""
📊 Статистика:

👥 Всего пользователей: {total_users}
🔑 Активных ключей: {active_keys}
💰 Общая выручка: {total_revenue} руб.
    """
    
    keyboard = [[InlineKeyboardButton("Назад", callback_data='admin')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.callback_query.edit_message_text(
        text=stats_text,
        reply_markup=reply_markup
    )
    
    conn.close()

# Основная функция
def main():
    # Инициализируем базу данных
    init_db()
    
    # Создаем updater и dispatcher
    updater = Updater(config.BOT_TOKEN)
    dispatcher = updater.dispatcher
    
    # Добавляем обработчики
    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))
    
    # Запускаем бота
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
