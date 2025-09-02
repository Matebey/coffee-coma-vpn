import os
import sqlite3
import subprocess
import qrcode
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from cryptography.fernet import Fernet
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация (ЗАМЕНИТЕ ЭТИ ЗНАЧЕНИЯ НА СВОИ!)
BOT_TOKEN = "7953514140:AAGg-AgyL6Y2mvzfyKesnpouJkU6p_B8Zeo"
ADMIN_IDS = [5631675412]  # ID администраторов
PRICE = 100  # Цена в рублях
SERVER_IP = "YOUR_SERVER_IP"  # IP вашего сервера
SERVER_PUBLIC_KEY = "YOUR_SERVER_PUBLIC_KEY"  # Публичный ключ сервера

# Шифрование ключей
KEY = Fernet.generate_key()
cipher_suite = Fernet(KEY)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('wireguard.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            config_name TEXT,
            private_key TEXT,
            public_key TEXT,
            address TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            amount INTEGER,
            status TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# Генерация конфигурации клиента
def generate_client_config(client_private_key, client_public_key, address):
    config = f"""[Interface]
PrivateKey = {client_private_key}
Address = {address}
DNS = 8.8.8.8

[Peer]
PublicKey = {SERVER_PUBLIC_KEY}
Endpoint = {SERVER_IP}:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
"""
    return config

# Добавление клиента в WireGuard
def add_client_to_wg(public_key, address):
    try:
        subprocess.run(['wg', 'set', 'wg0', 'peer', public_key, 'allowed-ips', address], check=True)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Error adding client to WG: {e}")
        return False

# Генерация QR кода
def generate_qr_code(config, config_name):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(config)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    img_path = f"{config_name}.png"
    img.save(img_path)
    return img_path

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [
        [InlineKeyboardButton("💰 Купить доступ", callback_data='buy')],
        [InlineKeyboardButton("📱 Мои конфиги", callback_data='my_configs')],
        [InlineKeyboardButton("❓ Помощь", callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Добро пожаловать! Этот бот предоставляет доступ к VPN через WireGuard.\n\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )

# Обработка callback запросов
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'buy':
        await buy_access(query, context)
    elif query.data == 'my_configs':
        await show_my_configs(query, context)
    elif query.data == 'help':
        await help_command(query, context)

# Покупка доступа
async def buy_access(query, context):
    user_id = query.from_user.id
    
    # Генерация ключей
    private_key = subprocess.run(['wg', 'genkey'], capture_output=True, text=True).stdout.strip()
    public_key = subprocess.run(['wg', 'pubkey'], input=private_key, capture_output=True, text=True).stdout.strip()
    
    # Генерация адреса
    conn = sqlite3.connect('wireguard.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]
    address = f"10.0.0.{user_count + 2}/32"
    
    # Шифрование приватного ключа
    encrypted_private_key = cipher_suite.encrypt(private_key.encode())
    
    # Сохранение в базу данных
    config_name = f"client{user_count + 1}"
    cursor.execute(
        "INSERT INTO users (user_id, config_name, private_key, public_key, address) VALUES (?, ?, ?, ?, ?)",
        (user_id, config_name, encrypted_private_key, public_key, address)
    )
    conn.commit()
    conn.close()
    
    # Добавление клиента в WG
    if add_client_to_wg(public_key, address):
        # Генерация конфига
        config = generate_client_config(private_key, public_key, address)
        
        # Генерация QR кода
        qr_path = generate_qr_code(config, config_name)
        
        # Отправка пользователю
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Ваш конфиг создан!\n\nИмя конфига: {config_name}\nАдрес: {address}"
        )
        
        await context.bot.send_document(
            chat_id=user_id,
            document=open(f"{config_name}.png", 'rb'),
            caption="QR код для импорта в WireGuard"
        )
        
        await context.bot.send_document(
            chat_id=user_id,
            document=config.encode('utf-8'),
            filename=f"{config_name}.conf",
            caption="Конфигурационный файл WireGuard"
        )
        
        # Очистка временных файлов
        os.remove(f"{config_name}.png")
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Ошибка при создании конфига. Свяжитесь с администратором."
        )

# Показать мои конфиги
async def show_my_configs(query, context):
    user_id = query.from_user.id
    conn = sqlite3.connect('wireguard.db')
    cursor = conn.cursor()
    cursor.execute("SELECT config_name, address FROM users WHERE user_id = ?", (user_id,))
    configs = cursor.fetchall()
    conn.close()
    
    if configs:
        text = "📱 Ваши конфигурации:\n\n"
        for config in configs:
            text += f"🔹 {config[0]} - {config[1]}\n"
    else:
        text = "У вас пока нет конфигураций."
    
    await context.bot.send_message(chat_id=user_id, text=text)

# Команда помощи
async def help_command(query, context):
    help_text = """
🤖 **WireGuard VPN Bot**

📋 **Доступные команды:**
/start - Начать работу с ботом
/myconfigs - Показать мои конфиги
/buy - Купить доступ

💡 **Как использовать:**
1. Нажмите "Купить доступ"
2. Оплатите услугу
3. Получите конфиг и QR код
4. Импортируйте в WireGuard клиент

📱 **Поддерживаемые клиенты:**
- Android: WireGuard app
- iOS: WireGuard app
- Windows: WireGuard client
- macOS: WireGuard client

❓ **Проблемы?** Свяжитесь с администратором.
"""
    await context.bot.send_message(chat_id=query.from_user.id, text=help_text, parse_mode='Markdown')

# Команда для администратора
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Доступ запрещен")
        return
    
    conn = sqlite3.connect('wireguard.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT user_id) FROM users")
    unique_users = cursor.fetchone()[0]
    conn.close()
    
    stats_text = f"""
📊 **Статистика бота**

👥 Всего конфигов: {total_users}
👤 Уникальных пользователей: {unique_users}
💰 Цена подписки: {PRICE} руб.
"""
    await update.message.reply_text(stats_text, parse_mode='Markdown')

def main():
    # Инициализация базы данных
    init_db()
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавление обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(CommandHandler("myconfigs", show_my_configs))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Запуск бота
    application.run_polling()
    logger.info("Бот запущен!")

if __name__ == '__main__':
    main()
