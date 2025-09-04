import os
import sqlite3
import subprocess
import qrcode
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from cryptography.fernet import Fernet
import logging
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Конфигурация (замените на свои данные)
BOT_TOKEN = "7953514140:AAGg-AgyL6Y2mvzfyKesnpouJkU6p_B8Zeo"
ADMIN_IDS = [123456789]  # Ваш Telegram ID
PRICE = 50  # Цена в рублях
TRIAL_DAYS = 7  # Пробный период

# Пути к файлам
CONFIG_FILE = "config.json"
DB_FILE = "wireguard.db"

# Инициализация конфига
def init_config():
    if not os.path.exists(CONFIG_FILE):
        config = {
            "server_ip": "YOUR_SERVER_IP",
            "server_public_key": "YOUR_SERVER_PUBLIC_KEY",
            "yoo_kassa_token": "YOUR_YOOKASSA_TOKEN",
            "cloud_payments_secret": "YOUR_CLOUD_PAYMENTS_SECRET",
            "admin_ids": ADMIN_IDS,
            "price": PRICE,
            "trial_days": TRIAL_DAYS
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    return load_config()

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

# Шифрование ключей
KEY = Fernet.generate_key()
cipher_suite = Fernet(KEY)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            username TEXT,
            config_name TEXT,
            private_key TEXT,
            public_key TEXT,
            address TEXT,
            status TEXT DEFAULT 'active',
            is_trial INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME,
            last_payment DATETIME
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            amount INTEGER,
            payment_method TEXT,
            status TEXT DEFAULT 'pending',
            payment_id TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_settings (
            id INTEGER PRIMARY KEY,
            setting_key TEXT UNIQUE,
            setting_value TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

# Генерация конфигурации клиента
def generate_client_config(client_private_key, address, config):
    client_config = f"""[Interface]
PrivateKey = {client_private_key}
Address = {address}
DNS = 8.8.8.8, 1.1.1.1

[Peer]
PublicKey = {config['server_public_key']}
Endpoint = {config['server_ip']}:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""
    return client_config

# Добавление клиента в WireGuard
def add_client_to_wg(public_key, address):
    try:
        result = subprocess.run([
            'wg', 'set', 'wg0', 
            'peer', public_key, 
            'allowed-ips', address
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"WG error: {result.stderr}")
            return False
            
        # Сохраняем конфигурацию
        subprocess.run(['wg', 'quicksave', 'wg0'], check=True)
        return True
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Error adding client: {e}")
        return False

# Генерация QR кода
def generate_qr_code(config_text, config_name):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(config_text)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    img_path = f"{config_name}.png"
    img.save(img_path)
    return img_path

# Проверка прав администратора
def is_admin(user_id):
    config = load_config()
    return user_id in config['admin_ids']

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    
    # Добавляем пользователя в базу если его нет
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username)
        )
        conn.commit()
    conn.close()
    
    keyboard = [
        [InlineKeyboardButton("💰 Купить доступ", callback_data='buy')],
        [InlineKeyboardButton("🎁 Бесплатный пробный период", callback_data='trial')],
        [InlineKeyboardButton("📱 Мои конфиги", callback_data='my_configs')],
        [InlineKeyboardButton("❓ Помощь", callback_data='help')]
    ]
    
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("👑 Админ панель", callback_data='admin')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🔒 Добро пожаловать в VPN сервис!\n\n"
        "✅ Защитите свое соединение\n"
        "🌍 Доступ к любым ресурсам\n"
        "⚡ Высокая скорость\n\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )

# Админ панель
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Доступ запрещен")
        return
    
    config = load_config()
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("⚙️ Настройки сервера", callback_data='admin_server')],
        [InlineKeyboardButton("💳 Настройки платежей", callback_data='admin_payments')],
        [InlineKeyboardButton("👥 Управление пользователями", callback_data='admin_users')],
        [InlineKeyboardButton("🔄 Обновить конфиг", callback_data='admin_reload')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👑 Админ панель\n\n"
        f"Сервер: {config['server_ip']}\n"
        f"Цена: {config['price']} руб.\n"
        f"Пробный период: {config['trial_days']} дней\n"
        f"Админов: {len(config['admin_ids'])}",
        reply_markup=reply_markup
    )

# Обработка callback запросов
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == 'buy':
        await show_payment_methods(query, context)
    elif query.data == 'trial':
        await create_trial_config(query, context)
    elif query.data == 'my_configs':
        await show_my_configs(query, context)
    elif query.data == 'help':
        await help_command(query, context)
    elif query.data == 'admin':
        await admin_menu(query, context)
    elif query.data.startswith('admin_'):
        await handle_admin_actions(query, context)
    elif query.data.startswith('pay_'):
        await handle_payment_method(query, context)

# Показать методы оплаты
async def show_payment_methods(query, context):
    keyboard = [
        [InlineKeyboardButton("💳 ЮMoney", callback_data='pay_yoomoney')],
        [InlineKeyboardButton("☁️ Cloud Payments", callback_data='pay_cloud')],
        [InlineKeyboardButton("🔙 Назад", callback_data='back_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    config = load_config()
    
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=f"💳 Выберите способ оплаты\n\n"
             f"Стоимость: {config['price']} руб.\n"
             f"Срок действия: 30 дней\n\n"
             "После оплаты вы получите конфиг файл и QR код",
        reply_markup=reply_markup
    )

# Создание пробного конфига
async def create_trial_config(query, context):
    user_id = query.from_user.id
    config = load_config()
    
    # Проверяем не использовал ли уже пробный период
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE user_id = ? AND is_trial = 1", (user_id,))
    if cursor.fetchone():
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Вы уже использовали пробный период"
        )
        conn.close()
        return
    
    # Генерация ключей
    private_key = subprocess.run(['wg', 'genkey'], capture_output=True, text=True).stdout.strip()
    public_key = subprocess.run(['wg', 'pubkey'], input=private_key, capture_output=True, text=True).stdout.strip()
    
    # Генерация адреса
    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]
    address = f"10.0.0.{user_count + 2}/32"
    
    # Расчет даты окончания
    expires_at = (datetime.datetime.now() + datetime.timedelta(days=config['trial_days'])).strftime('%Y-%m-%d %H:%M:%S')
    
    # Сохранение в базу
    config_name = f"trial_{user_id}"
    cursor.execute(
        """INSERT INTO users (user_id, config_name, private_key, public_key, address, 
           is_trial, expires_at, status) VALUES (?, ?, ?, ?, ?, 1, ?, 'active')""",
        (user_id, config_name, private_key, public_key, address, expires_at)
    )
    conn.commit()
    conn.close()
    
    # Добавление в WG
    if add_client_to_wg(public_key, address):
        # Генерация конфига
        client_config = generate_client_config(private_key, address, config)
        qr_path = generate_qr_code(client_config, config_name)
        
        # Отправка пользователю
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🎁 Пробный период активирован!\n\n"
                 f"⏰ Срок действия: {config['trial_days']} дней\n"
                 f"📅 До: {expires_at}\n"
                 f"🔧 Имя конфига: {config_name}\n"
                 f"📍 Адрес: {address}"
        )
        
        await context.bot.send_document(
            chat_id=user_id,
            document=open(qr_path, 'rb'),
            caption="QR код для импорта"
        )
        
        await context.bot.send_document(
            chat_id=user_id,
            document=client_config.encode('utf-8'),
            filename=f"{config_name}.conf",
            caption="Конфигурационный файл"
        )
        
        os.remove(qr_path)
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Ошибка при создании конфига"
        )

# Админ меню
async def admin_menu(query, context):
    if not is_admin(query.from_user.id):
        await context.bot.send_message(chat_id=query.from_user.id, text="❌ Доступ запрещен")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("🔧 Настройки сервера", callback_data='admin_settings')],
        [InlineKeyboardButton("👥 Пользователи", callback_data='admin_users')],
        [InlineKeyboardButton("💳 Платежи", callback_data='admin_payments')],
        [InlineKeyboardButton("⚙️ Конфигурация", callback_data='admin_config')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text="👑 Админ панель - Выберите действие:",
        reply_markup=reply_markup
    )

# Обработка админ действий
async def handle_admin_actions(query, context):
    user_id = query.from_user.id
    if not is_admin(user_id):
        return
    
    if query.data == 'admin_stats':
        await show_admin_stats(query, context)
    elif query.data == 'admin_settings':
        await admin_server_settings(query, context)
    elif query.data == 'admin_config':
        await admin_config_management(query, context)

# Показать статистику админу
async def show_admin_stats(query, context):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_trial = 1")
    trial_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM payments WHERE status = 'completed'")
    paid_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE status = 'active'")
    active_users = cursor.fetchone()[0]
    
    conn.close()
    
    config = load_config()
    
    stats_text = f"""
📊 Статистика бота:

👥 Всего пользователей: {total_users}
🎁 Пробных: {trial_users}
💳 Платных: {paid_users}
✅ Активных: {active_users}

⚙️ Настройки:
💰 Цена: {config['price']} руб.
⏰ Пробный период: {config['trial_days']} дней
🌐 Сервер: {config['server_ip']}
    """
    
    await context.bot.send_message(chat_id=query.from_user.id, text=stats_text)

# Команда для админов
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Доступ запрещен")
        return
    await admin_panel(update, context)

def main():
    # Инициализация
    init_config()
    init_db()
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавление обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("myconfigs", show_my_configs))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Запуск бота
    application.run_polling()
    logger.info("Бот запущен!")

if __name__ == '__main__':
    main()
