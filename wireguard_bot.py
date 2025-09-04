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
import re
import tempfile
import io

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # ЗАМЕНИТЕ НА РЕАЛЬНЫЙ ТОКЕН
CONFIG_FILE = "config.json"
DB_FILE = "wireguard.db"

# Состояния для обработки скриншотов оплаты
PAYMENT_VERIFICATION = {}

# Инициализация конфига
def init_config():
    if not os.path.exists(CONFIG_FILE):
        config = {
            "server_ip": "YOUR_SERVER_IP",  # ЗАМЕНИТЕ НА РЕАЛЬНЫЙ IP
            "server_public_key": "YOUR_SERVER_PUBLIC_KEY",  # ЗАМЕНИТЕ НА РЕАЛЬНЫЙ КЛЮЧ
            "admin_ids": [123456789],  # ЗАМЕНИТЕ НА РЕАЛЬНЫЕ ID АДМИНОВ
            "price": 100,
            "trial_days": 7,
            "sbp_link": "https://t.me/c/1234567890/1",
            "wallet_number": "1234567890"
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
            is_paid INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            amount INTEGER,
            payment_method TEXT,
            status TEXT DEFAULT 'pending',
            screenshot_path TEXT,
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
            'sudo', 'wg', 'set', 'wg0', 
            'peer', public_key, 
            'allowed-ips', address
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logger.error(f"WG error: {result.stderr}")
            return False
            
        # Сохраняем конфигурацию
        subprocess.run(['sudo', 'wg-quick', 'save', 'wg0'], check=True)
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
        
        # Сохраняем в память вместо файла
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        
        return img_buffer
    except Exception as e:
        logger.error(f"QR generation error: {e}")
        return None

# Проверка прав администратора
def is_admin(user_id):
    config = load_config()
    return user_id in config['admin_ids']

# Создание конфига для пользователя
async def create_user_config(user_id, username, is_trial=False):
    try:
        config = load_config()
        
        # Генерация ключей
        private_key, public_key = generate_wireguard_keys()
        if not private_key or not public_key:
            return {'success': False, 'error': 'Key generation failed'}
        
        # Генерация адреса
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        address = f"10.0.0.{user_count + 2}/32"
        
        # Расчет даты окончания
        if is_trial:
            expires_at = (datetime.datetime.now() + datetime.timedelta(days=config['trial_days'])).strftime('%Y-%m-%d %H:%M:%S')
            config_name = f"trial_{user_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
            is_trial_val = 1
            is_paid_val = 0
        else:
            expires_at = (datetime.datetime.now() + datetime.timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
            config_name = f"paid_{user_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
            is_trial_val = 0
            is_paid_val = 1
        
        # Шифрование приватного ключа
        encrypted_private_key = cipher_suite.encrypt(private_key.encode())
        
        # Сохранение в базу
        cursor.execute(
            """INSERT INTO users (user_id, username, config_name, private_key, public_key, address, 
               is_trial, is_paid, expires_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
            (user_id, username, config_name, encrypted_private_key, public_key, address, is_trial_val, is_paid_val, expires_at)
        )
        
        # Добавляем запись о платеже если это оплата
        if not is_trial:
            cursor.execute(
                """INSERT INTO payments (user_id, amount, payment_method, status) 
                   VALUES (?, ?, 'sbp', 'completed')""",
                (user_id, config['price'])
            )
        
        conn.commit()
        conn.close()
        
        # Добавление в WG
        if add_client_to_wg(public_key, address):
            # Генерация конфига
            client_config = generate_client_config(private_key, address)
            qr_buffer = generate_qr_code(client_config, config_name)
            
            return {
                'success': True,
                'config': client_config,
                'qr_buffer': qr_buffer,
                'config_name': config_name,
                'address': address,
                'expires_at': expires_at
            }
        else:
            return {'success': False, 'error': 'WireGuard error'}
            
    except Exception as e:
        logger.error(f"Create config error: {e}")
        return {'success': False, 'error': str(e)}

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
            [InlineKeyboardButton("💰 Купить доступ (100 руб.)", callback_data='buy')],
            [InlineKeyboardButton("🎁 Бесплатный пробный период (7 дней)", callback_data='trial')],
            [InlineKeyboardButton("📱 Мои конфиги", callback_data='my_configs')],
            [InlineKeyboardButton("❓ Помощь", callback_data='help')]
        ]
        
        if is_admin(user_id):
            keyboard.append([InlineKeyboardButton("👑 Админ панель", callback_data='admin')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🔒 Добро пожаловать в VPN сервис!\n\n"
            "✅ Защита вашего соединения\n"
            "🌍 Доступ к любым ресурсам\n"
            "⚡ Высокая скорость\n\n"
            "Выберите действие:",
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
        cursor.execute("""
            SELECT config_name, address, status, expires_at, is_trial, is_paid 
            FROM users WHERE user_id = ? ORDER BY created_at DESC
        """, (user_id,))
        configs = cursor.fetchall()
        conn.close()
        
        if configs:
            text = "📱 Ваши конфигурации:\n\n"
            for config in configs:
                status_emoji = "✅" if config[2] == 'active' else "❌"
                config_type = "🎁 Пробный" if config[4] == 1 else "💳 Платный"
                text += f"{status_emoji} {config_type} - {config[0]}\n"
                text += f"📍 Адрес: {config[1]}\n"
                if config[3]:
                    text += f"⏰ До: {config[3]}\n"
                text += "\n"
        else:
            text = "У вас пока нет конфигураций.\n\nИспользуйте пробный период или купите доступ!"
        
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"My configs error: {e}")
        await update.message.reply_text("❌ Ошибка при загрузке конфигураций")

# Показать методы оплаты
async def show_payment_methods(query, context):
    try:
        config = load_config()
        user_id = query.from_user.id
        
        # Сохраняем что пользователь начал процесс оплаты
        PAYMENT_VERIFICATION[user_id] = {'status': 'waiting_screenshot'}
        
        payment_text = f"""
💳 Оплата доступа

Стоимость: {config['price']} руб.
Срок действия: 30 дней

📲 Оплата по СБП:
1. Переведите {config['price']} руб. на наш счет
2. Сделайте скриншот перевода
3. Отправьте скриншот в этот чат

💳 Реквизиты для перевода:
{config['wallet_number']}

После проверки оплаты вы получите конфиг файл.
        """
        
        await context.bot.send_message(
            chat_id=user_id,
            text=payment_text
        )
        
    except Exception as e:
        logger.error(f"Payment methods error: {e}")

# Обработка скриншотов оплаты
async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "Unknown"
        
        # Проверяем ожидает ли пользователь проверки скриншота
        if user_id not in PAYMENT_VERIFICATION or PAYMENT_VERIFICATION[user_id]['status'] != 'waiting_screenshot':
            return
        
        if update.message.photo:
            # Сохраняем информацию о скриншоте
            photo = update.message.photo[-1]
            file_id = photo.file_id
            
            # Скачиваем файл
            file = await context.bot.get_file(file_id)
            screenshot_path = f"payment_{user_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            await file.download_to_drive(screenshot_path)
            
            # Обновляем статус
            PAYMENT_VERIFICATION[user_id] = {
                'status': 'verifying',
                'screenshot_path': screenshot_path,
                'timestamp': datetime.datetime.now()
            }
            
            # Создаем конфиг для пользователя
            result = await create_user_config(user_id, username, is_trial=False)
            
            if result['success']:
                # Отправляем конфиг пользователю
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"✅ Оплата подтверждена! Доступ активирован на 30 дней.\n\n"
                         f"🔧 Имя конфига: {result['config_name']}\n"
                         f"📍 Адрес: {result['address']}\n"
                         f"⏰ Действует до: {result['expires_at']}"
                )
                
                # Отправляем QR код
                if result['qr_buffer']:
                    await context.bot.send_photo(
                        chat_id=user_id,
                        photo=result['qr_buffer'],
                        caption="QR код для импорта в WireGuard"
                    )
                
                # Отправляем конфиг файл
                with tempfile.NamedTemporaryFile(mode='w+', suffix='.conf', delete=False) as temp_file:
                    temp_file.write(result['config'])
                    temp_file.flush()
                    
                    with open(temp_file.name, 'rb') as config_file:
                        await context.bot.send_document(
                            chat_id=user_id,
                            document=config_file,
                            filename=f"{result['config_name']}.conf",
                            caption="Конфигурационный файл WireGuard"
                        )
                
                # Уведомляем админов
                config = load_config()
                for admin_id in config['admin_ids']:
                    try:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=f"💰 Новый платеж!\n\n"
                                 f"👤 User ID: {user_id}\n"
                                 f"👤 Username: @{username}\n"
                                 f"💳 Сумма: {config['price']} руб.\n"
                                 f"📅 Время: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        )
                    except Exception as admin_error:
                        logger.error(f"Admin notification error: {admin_error}")
                
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="❌ Ошибка при создании конфига. Свяжитесь с администратором."
                )
            
            # Удаляем из ожидания проверки
            if user_id in PAYMENT_VERIFICATION:
                del PAYMENT_VERIFICATION[user_id]
                
    except Exception as e:
        logger.error(f"Screenshot handler error: {e}")

# Создание пробного конфига
async def create_trial_config(query, context):
    try:
        user_id = query.from_user.id
        username = query.from_user.username or "Unknown"
        
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
        conn.close()
        
        # Создаем конфиг
        result = await create_user_config(user_id, username, is_trial=True)
        
        if result['success']:
            # Отправляем конфиг пользователю
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎁 Пробный период активирован на 7 дней!\n\n"
                     f"🔧 Имя конфига: {result['config_name']}\n"
                     f"📍 Адрес: {result['address']}\n"
                     f"⏰ Действует до: {result['expires_at']}"
            )
            
            # Отправляем QR код
            if result['qr_buffer']:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=result['qr_buffer'],
                    caption="QR код для импорта в WireGuard"
                )
            
            # Отправляем конфиг файл
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.conf', delete=False) as temp_file:
                temp_file.write(result['config'])
                temp_file.flush()
                
                with open(temp_file.name, 'rb') as config_file:
                    await context.bot.send_document(
                        chat_id=user_id,
                        document=config_file,
                        filename=f"{result['config_name']}.conf",
                        caption="Конфигурационный файл WireGuard"
                    )
                    
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Ошибка при создании пробного конфига"
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
🤖 **VPN Bot - Помощь**

📋 **Доступные команды:**
/start - Главное меню
/myconfigs - Мои конфигурации

💡 **Как использовать:**
1. Нажмите «Бесплатный пробный период»
2. Получите конфиг и QR код
3. Импортируйте в приложение WireGuard

💳 **Оплата:**
- Оплата по СБП
- Отправьте скриншот перевода
- Получите конфиг после проверки

❓ **Проблемы?** Свяжитесь с администратором
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
        [InlineKeyboardButton("⚙️ Настройки", callback_data='admin_settings')],
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👑 Админ панель\n\n"
        f"🌐 Сервер: {config['server_ip']}\n"
        f"💰 Цена: {config['price']} руб.\n"
        f"🎁 Пробный: {config['trial_days']} дней",
        reply_markup=reply_markup
    )

# Обработка callback запросов
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        if query.data == 'buy':
            await show_payment_methods(query, context)
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
    try:
        user_id = query.from_user.id
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT config_name, address, status, expires_at, is_trial, is_paid 
            FROM users WHERE user_id = ? ORDER BY created_at DESC
        """, (user_id,))
        configs = cursor.fetchall()
        conn.close()
        
        if configs:
            text = "📱 Ваши конфигурации:\n\n"
            for config in configs:
                status_emoji = "✅" if config[2] == 'active' else "❌"
                config_type = "🎁 Пробный" if config[4] == 1 else "💳 Платный"
                text += f"{status_emoji} {config_type} - {config[0]}\n"
                text += f"📍 Адрес: {config[1]}\n"
                if config[3]:
                    text += f"⏰ До: {config[3]}\n"
                text += "\n"
        else:
            text = "У вас пока нет конфигураций.\n\nИспользуйте пробный период или купите доступ!"
        
        await context.bot.send_message(chat_id=user_id, text=text)
    except Exception as e:
        logger.error(f"My configs callback error: {e}")

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
    
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_trial = 1")
        trial_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_paid = 1")
        paid_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE status = 'active'")
        active_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(amount) FROM payments WHERE status = 'completed'")
        total_revenue = cursor.fetchone()[0] or 0
        
        conn.close()
        
        config = load_config()
        
        stats_text = f"""
📊 Статистика бота:

👥 Всего пользователей: {total_users}
🎁 Пробных: {trial_users}
💳 Платных: {paid_users}
✅ Активных: {active_users}
💰 Общая выручка: {total_revenue} руб.

⚙️ Настройки:
💰 Цена: {config['price']} руб.
⏰ Пробный период: {config['trial_days']} дней
🌐 Сервер: {config['server_ip']}
        """
        
        await context.bot.send_message(chat_id=query.from_user.id, text=stats_text)
    except Exception as e:
        logger.error(f"Admin stats error: {e}")

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
        application.add_handler(MessageHandler(filters.PHOTO, handle_screenshot))
        
        # Запуск бота
        logger.info("Запуск бота...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise

if __name__ == '__main__':
    main()
