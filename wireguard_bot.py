import os
import sqlite3
import subprocess
import qrcode
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from cryptography.fernet import Fernet
import logging
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
CONFIG_FILE = "config.json"
DB_FILE = "wireguard.db"

# Инициализация конфига
def init_config():
    if not os.path.exists(CONFIG_FILE):
        config = {
            "server_ip": "YOUR_SERVER_IP",
            "server_public_key": "YOUR_SERVER_PUBLIC_KEY",
            "admin_ids": [123456789],  # Ваш Telegram ID
            "price": 100,
            "trial_days": 7
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
            expires_at DATETIME
        )
    ''')
    
    conn.commit()
    conn.close()

# Генерация конфигурации клиента
def generate_client_config(client_private_key, address):
    config = load_config()
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
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logger.error(f"WG error: {result.stderr}")
            return False
            
        return True
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Error adding client: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return False

# Генерация QR кода
def generate_qr_code(config_text, config_name):
    try:
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
    except Exception as e:
        logger.error(f"QR generation error: {e}")
        return None

# Проверка прав администратора
def is_admin(user_id):
    config = load_config()
    return user_id in config['admin_ids']

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
            "🔒 Добро пожаловать в VPN сервис!\n\nВыберите действие:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Start command error: {e}")

# Показать мои конфиги
async def show_my_configs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT config_name, address, status, expires_at FROM users WHERE user_id = ?", (user_id,))
        configs = cursor.fetchall()
        conn.close()
        
        if configs:
            text = "📱 Ваши конфигурации:\n\n"
            for config in configs:
                status_emoji = "✅" if config[2] == 'active' else "❌"
                text += f"{status_emoji} {config[0]} - {config[1]}\n"
                if config[3]:
                    text += f"   ⏰ До: {config[3]}\n"
        else:
            text = "У вас пока нет конфигураций."
        
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"My configs error: {e}")

# Создание пробного конфига
async def create_trial_config(query, context):
    try:
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
            client_config = generate_client_config(private_key, address)
            qr_path = generate_qr_code(client_config, config_name)
            
            if qr_path:
                # Отправка пользователю
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🎁 Пробный период активирован!\n\n"
                         f"⏰ Срок действия: {config['trial_days']} дней\n"
                         f"🔧 Имя конфига: {config_name}\n"
                         f"📍 Адрес: {address}"
                )
                
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=open(qr_path, 'rb'),
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
                    text="❌ Ошибка генерации QR кода"
                )
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Ошибка при создании конфига в WireGuard"
            )
            
    except Exception as e:
        logger.error(f"Trial config error: {e}")
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="❌ Произошла ошибка при создании конфига"
        )

# Помощь
async def help_command(query, context):
    help_text = """
🤖 **WireGuard VPN Bot**

📋 **Доступные команды:**
/start - Начать работу с ботом
/myconfigs - Показать мои конфиги

💡 **Как использовать:**
1. Нажмите "Бесплатный пробный период"
2. Получите конфиг и QR код
3. Импортируйте в WireGuard клиент

❓ **Проблемы?** Свяжитесь с администратором.
"""
    await context.bot.send_message(chat_id=query.from_user.id, text=help_text)

# Админ команда
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Доступ запрещен")
        return
    
    config = load_config()
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("⚙️ Настройки", callback_data='admin_settings')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👑 Админ панель\n\n"
        f"Сервер: {config['server_ip']}\n"
        f"Цена: {config['price']} руб.\n"
        f"Пробный период: {config['trial_days']} дней",
        reply_markup=reply_markup
    )

# Обработка callback запросов
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        if query.data == 'buy':
            await context.bot.send_message(chat_id=user_id, text="💳 Функция оплаты в разработке")
        elif query.data == 'trial':
            await create_trial_config(query, context)
        elif query.data == 'my_configs':
            await show_my_configs_callback(query, context)
        elif query.data == 'help':
            await help_command(query, context)
        elif query.data == 'admin':
            await admin_command_callback(query, context)
        elif query.data == 'admin_stats':
            await admin_stats(query, context)
            
    except Exception as e:
        logger.error(f"Button handler error: {e}")

async def show_my_configs_callback(query, context):
    user_id = query.from_user.id
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT config_name, address, status, expires_at FROM users WHERE user_id = ?", (user_id,))
    configs = cursor.fetchall()
    conn.close()
    
    if configs:
        text = "📱 Ваши конфигурации:\n\n"
        for config in configs:
            status_emoji = "✅" if config[2] == 'active' else "❌"
            text += f"{status_emoji} {config[0]} - {config[1]}\n"
            if config[3]:
                text += f"   ⏰ До: {config[3]}\n"
    else:
        text = "У вас пока нет конфигураций."
    
    await context.bot.send_message(chat_id=user_id, text=text)

async def admin_command_callback(query, context):
    if not is_admin(query.from_user.id):
        await context.bot.send_message(chat_id=query.from_user.id, text="❌ Доступ запрещен")
        return
    
    config = load_config()
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("⚙️ Настройки", callback_data='admin_settings')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=f"👑 Админ панель\n\nСервер: {config['server_ip']}",
        reply_markup=reply_markup
    )

async def admin_stats(query, context):
    if not is_admin(query.from_user.id):
        return
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_trial = 1")
    trial_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE status = 'active'")
    active_users = cursor.fetchone()[0]
    
    conn.close()
    
    config = load_config()
    
    stats_text = f"""
📊 Статистика бота:

👥 Всего пользователей: {total_users}
🎁 Пробных: {trial_users}
✅ Активных: {active_users}

⚙️ Настройки:
💰 Цена: {config['price']} руб.
⏰ Пробный период: {config['trial_days']} дней
🌐 Сервер: {config['server_ip']}
    """
    
    await context.bot.send_message(chat_id=query.from_user.id, text=stats_text)

def main():
    try:
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
        logger.info("Запуск бота...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise

if __name__ == '__main__':
    main()
