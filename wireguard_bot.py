import os
import sqlite3
import subprocess
import qrcode
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from cryptography.fernet import Fernet
import logging
import tempfile
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация (ЗАМЕНИТЕ ЭТИ ЗНАЧЕНИЯ НА СВОИ!)
BOT_TOKEN = "7953514140:AAGg-AgyL6Y2mvzfyKesnpouJkU6p_B8Zeo"
ADMIN_IDS = [5631675412]  # ID администраторов
PRICE = 100  # Цена в рублях
SERVER_IP = "77.239.105.17"  # IP вашего сервера
SERVER_PUBLIC_KEY = "AAAAC3NzaC1lZDI1NTE5AAAAIL6JznsxyInWPJLNcrClRTGzU6WwPeadiQS4uM1745UZ root@vm315155.hosted-by.u1host.com"  # Публичный ключ сервера

# Шифрование ключей (в продакшене храните ключ в безопасном месте)
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
            is_active INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            amount INTEGER,
            status TEXT,
            payment_data TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# Генерация ключей WireGuard
def generate_wireguard_keys():
    try:
        # Генерация приватного ключа
        private_key = subprocess.run(
            ['wg', 'genkey'], 
            capture_output=True, 
            text=True, 
            check=True
        ).stdout.strip()
        
        # Генерация публичного ключа из приватного
        public_key = subprocess.run(
            ['wg', 'pubkey'], 
            input=private_key, 
            capture_output=True, 
            text=True, 
            check=True
        ).stdout.strip()
        
        return private_key, public_key
    except subprocess.CalledProcessError as e:
        logger.error(f"Error generating keys: {e}")
        return None, None

# Генерация конфигурации клиента
def generate_client_config(client_private_key, address):
    config = f"""[Interface]
PrivateKey = {client_private_key}
Address = {address}
DNS = 8.8.8.8, 1.1.1.1

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
        subprocess.run([
            'wg', 'set', 'wg0', 'peer', 
            public_key, 'allowed-ips', address
        ], check=True)
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
    
    # Здесь должна быть интеграция с платежной системой
    # Временно создаем конфиг без оплаты для демонстрации
    
    # Генерация ключей
    private_key, public_key = generate_wireguard_keys()
    if not private_key or not public_key:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Ошибка при генерации ключей. Свяжитесь с администратором."
        )
        return

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
        "INSERT INTO users (user_id, config_name, private_key, public_key, address, is_active) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, config_name, encrypted_private_key, public_key, address, 1)
    )
    conn.commit()
    conn.close()
    
    # Добавление клиента в WG
    if add_client_to_wg(public_key, address):
        # Генерация конфига
        config = generate_client_config(private_key, address)
        
        # Генерация QR кода
        qr_path = generate_qr_code(config, config_name)
        
        # Отправка пользователю
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Ваш конфиг создан!\n\nИмя конфига: {config_name}\nАдрес: {address}"
        )
        
        # Отправка QR кода
        with open(qr_path, 'rb') as qr_file:
            await context.bot.send_photo(
                chat_id=user_id,
                photo=qr_file,
                caption="QR код для импорта в WireGuard"
            )
        
        # Отправка конфиг файла
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.conf', delete=False) as temp_file:
            temp_file.write(config)
            temp_file.flush()
            
            with open(temp_file.name, 'rb') as config_file:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=config_file,
                    filename=f"{config_name}.conf",
                    caption="Конфигурационный файл WireGuard"
                )
        
        # Очистка временных файлов
        os.remove(qr_path)
        os.remove(temp_file.name)
        
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
    cursor.execute("SELECT config_name, address, is_active FROM users WHERE user_id = ?", (user_id,))
    configs = cursor.fetchall()
    conn.close()
    
    if configs:
        text = "📱 Ваши конфигурации:\n\n"
        for config in configs:
            status = "✅ Активен" if config[2] else "❌ Неактивен"
            text += f"🔹 {config[0]} - {config[1]} - {status}\n"
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
/help - Помощь

💡 **Как использовать:**
1. Нажмите "Купить доступ"
2. Оплатите услугу
3. Получите конфиг и QR код
4. Импортируйте в WireGuard клиент

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
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
    active_users = cursor.fetchone()[0]
    conn.close()
    
    stats_text = f"""
📊 **Статистика бота**

👥 Всего конфигов: {total_users}
👤 Уникальных пользователей: {unique_users}
✅ Активных подключений: {active_users}
💰 Цена подписки: {PRICE} руб.
"""
    await update.message.reply_text(stats_text, parse_mode='Markdown')

# Команда для просмотра конфигов
async def myconfigs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_my_configs(update, context)

def main():
    # Инициализация базы данных
    init_db()
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавление обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(CommandHandler("myconfigs", myconfigs_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Запуск бота
    logger.info("Бот запущен!")
    application.run_polling()

if __name__ == '__main__':
    main()
