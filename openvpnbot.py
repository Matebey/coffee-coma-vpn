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
import random
import string

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Константы
CONFIG_FILE = "config.json"

# Шифрование ключей
KEY = Fernet.generate_key()
cipher_suite = Fernet(KEY)

# Состояния для обработки скриншотов оплаты
PAYMENT_VERIFICATION = {}

# Инициализация конфига
def init_config():
    if not os.path.exists(CONFIG_FILE):
        default_config = {
            "bot_token": "8439963327:AAHDIJQuP611mfBtcFSZyDwO4-mBANPArAk",
            "admin_ids": [5631675412],
            "openvpn_dir": "/etc/openvpn",
            "easy_rsa_dir": "/etc/openvpn/easy-rsa",
            "pki_dir": "/etc/openvpn/easy-rsa/pki",
            "keys_dir": "/etc/openvpn/easy-rsa/pki/private",
            "issued_dir": "/etc/openvpn/easy-rsa/pki/issued",
            "server_config": "/etc/openvpn/server.conf",
            "db_path": "vpn_bot.db",
            "trial_days": 7,
            "max_configs_per_user": 3,
            "server_ip": "77.239.105.14",
            "server_port": 8443,
            "protocol": "udp",
            "price": 50,
            "sbp_link": "https://yoomoney.ru/to/4100119260614239/0",
            "wallet_number": "https://yoomoney.ru/to/4100119260614239/0",
            "dns_servers": "1.1.1.1,8.8.8.8",
            "ca_cert_path": "/etc/openvpn/easy-rsa/pki/ca.crt",
            "ta_key_path": "/etc/openvpn/easy-rsa/ta.key",
            "openvpn_management_ip": "127.0.0.1",
            "openvpn_management_port": 7505,
            "client_config_template": "/etc/openvpn/client-template.ovpn"
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(default_config, f, indent=4)
        print(f"Создан файл конфигурации по умолчанию: {CONFIG_FILE}")
        return default_config
    return load_config()

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            
            # Добавляем недостающие параметры или преобразуем названия
            config.setdefault('openvpn_dir', '/etc/openvpn')
            config.setdefault('easy_rsa_dir', '/etc/openvpn/easy-rsa')
            config.setdefault('pki_dir', '/etc/openvpn/easy-rsa/pki')
            config.setdefault('keys_dir', '/etc/openvpn/easy-rsa/pki/private')
            config.setdefault('issued_dir', '/etc/openvpn/easy-rsa/pki/issued')
            config.setdefault('server_config', '/etc/openvpn/server.conf')
            config.setdefault('db_path', 'vpn_bot.db')
            config.setdefault('max_configs_per_user', 3)
            config.setdefault('client_config_template', '/etc/openvpn/client-template.ovpn')
            
            return config
    except FileNotFoundError:
        return init_config()

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

# Инициализация базы данных
def init_db():
    try:
        config = load_config()
        db_path = config.get('db_path', 'vpn_bot.db')
        print(f"Инициализация БД по пути: {db_path}")
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Таблица users
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                username TEXT,
                config_name TEXT,
                private_key TEXT,
                certificate TEXT,
                status TEXT DEFAULT 'active',
                is_trial INTEGER DEFAULT 0,
                is_paid INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME
            )
        ''')
        
        # Таблица payments
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
        print("✅ База данных успешно инициализирована!")
        
    except Exception as e:
        print(f"❌ Ошибка инициализации БД: {e}")
        raise

# Генерация случайного имени для конфига
def generate_config_name(user_id):
    random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"user_{user_id}_{random_suffix}"

# Вспомогательные функции для извлечения чистых сертификатов и ключей
def extract_certificate_content(cert_content):
    """Извлекает только содержимое сертификата между BEGIN и END"""
    lines = cert_content.split('\n')
    certificate_lines = []
    in_certificate = False
    
    for line in lines:
        if '-----BEGIN CERTIFICATE-----' in line:
            in_certificate = True
            certificate_lines.append(line)  # Добавляем BEGIN line
            continue
        elif '-----END CERTIFICATE-----' in line:
            certificate_lines.append(line)  # Добавляем END line
            break
        elif in_certificate:
            certificate_lines.append(line)
    
    return '\n'.join(certificate_lines)

def extract_private_key_content(key_content):
    """Извлекает только содержимое приватного ключа между BEGIN и END"""
    lines = key_content.split('\n')
    key_lines = []
    in_key = False
    
    for line in lines:
        if '-----BEGIN PRIVATE KEY-----' in line:
            in_key = True
            key_lines.append(line)  # Добавляем BEGIN line
            continue
        elif '-----END PRIVATE KEY-----' in line:
            key_lines.append(line)  # Добавляем END line
            break
        elif in_key:
            key_lines.append(line)
    
    return '\n'.join(key_lines)

# Создание клиентского сертификата OpenVPN
def create_ovpn_client_certificate(username):
    try:
        config = load_config()
        easy_rsa_dir = config.get('easy_rsa_dir', '/etc/openvpn/easy-rsa/')
        keys_dir = config.get('keys_dir', '/etc/openvpn/easy-rsa/pki/private')
        issued_dir = config.get('issued_dir', '/etc/openvpn/easy-rsa/pki/issued')
        
        # Генерируем уникальное имя для клиента
        client_name = f"client_{username}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Переходим в директорию easy-rsa
        original_dir = os.getcwd()
        os.chdir(easy_rsa_dir)
        
        print(f"Создание сертификата для: {client_name}")
        
        # Создаем клиентский сертификат (автоматически подтверждаем)
        process = subprocess.Popen([
            './easyrsa', 'build-client-full', client_name, 'nopass'
        ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        # Автоматически отвечаем 'yes' на все запросы
        stdout, stderr = process.communicate(input='yes\n')
        
        if process.returncode != 0:
            logger.error(f"Certificate generation error: {stderr}")
            os.chdir(original_dir)
            return None, None, None
        
        # Читаем приватный ключ
        private_key_path = os.path.join(keys_dir, f"{client_name}.key")
        if os.path.exists(private_key_path):
            with open(private_key_path, 'r') as f:
                private_key_content = f.read()
                private_key = extract_private_key_content(private_key_content)
        else:
            logger.error(f"Private key not found: {private_key_path}")
            os.chdir(original_dir)
            return None, None, None
        
        # Читаем сертификат
        cert_path = os.path.join(issued_dir, f"{client_name}.crt")
        if os.path.exists(cert_path):
            with open(cert_path, 'r') as f:
                certificate_content = f.read()
                certificate = extract_certificate_content(certificate_content)
        else:
            logger.error(f"Certificate not found: {cert_path}")
            os.chdir(original_dir)
            return None, None, None
        
        os.chdir(original_dir)
        return client_name, private_key, certificate
        
    except Exception as e:
        logger.error(f"OpenVPN certificate error: {e}")
        return None, None, None

# Генерация конфигурации клиента OpenVPN
def generate_ovpn_client_config(client_name, private_key, certificate):
    config = load_config()
    
    # Читаем CA сертификат
    with open(config['ca_cert_path'], 'r') as f:
        ca_cert_content = f.read()
        ca_cert = extract_certificate_content(ca_cert_content)
    
    # Читаем TLS ключ
    ta_key = ""
    if os.path.exists(config['ta_key_path']):
        with open(config['ta_key_path'], 'r') as f:
            ta_key_content = f.read()
            # Для TLS ключа просто читаем как есть (это не сертификат)
            ta_key = ta_key_content
    
    # Генерируем чистый конфиг без лишних опций
    client_config = f"""client
dev tun
proto {config['protocol']}
remote {config['server_ip']} {config['server_port']}
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
cipher AES-256-GCM
auth SHA256
verb 3

<ca>
{ca_cert}
</ca>

<cert>
{certificate}
</cert>

<key>
{private_key}
</key>
"""
    
    if ta_key:
        client_config += f"""
<tls-crypt>
{ta_key}
</tls-crypt>
"""
    
    return client_config

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
        
        # Проверяем максимальное количество конфигов на пользователя
        max_configs = config.get('max_configs_per_user', 3)
        conn = sqlite3.connect(config.get('db_path', 'vpn_bot.db'))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE user_id = ?", (user_id,))
        user_config_count = cursor.fetchone()[0]
        conn.close()
        
        if user_config_count >= max_configs:
            return {'success': False, 'error': f'Превышено максимальное количество конфигов ({max_configs}) на пользователя'}
        
        # Создаем сертификат и ключи
        client_name, private_key, certificate = create_ovpn_client_certificate(username)
        if not private_key or not certificate:
            return {'success': False, 'error': 'Certificate generation failed'}
        
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
        encrypted_certificate = cipher_suite.encrypt(certificate.encode())
        
        # Сохранение в базу
        conn = sqlite3.connect(config.get('db_path', 'vpn_bot.db'))
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO users (user_id, username, config_name, private_key, certificate, 
               is_trial, is_paid, expires_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
            (user_id, username, config_name, encrypted_private_key, encrypted_certificate, is_trial_val, is_paid_val, expires_at)
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
        
        # Генерация конфига
        client_config = generate_ovpn_client_config(client_name, private_key, certificate)
        qr_buffer = generate_qr_code(client_config, config_name)
        
        return {
            'success': True,
            'config': client_config,
            'qr_buffer': qr_buffer,
            'config_name': config_name,
            'expires_at': expires_at,
            'client_name': client_name
        }
            
    except Exception as e:
        logger.error(f"Create config error: {e}")
        return {'success': False, 'error': str(e)}

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "Unknown"
        
        # Проверяем что БД существует и доступна
        config = load_config()
        db_path = config.get('db_path', 'vpn_bot.db')
        if not os.path.exists(db_path):
            init_db()  # Переинициализируем если БД удалена
            
        # Добавляем пользователя в базу если его нет
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Проверяем существует ли таблица
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        if not cursor.fetchone():
            conn.close()
            init_db()  # Пересоздаем таблицы
            conn = sqlite3.connect(db_path)
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
            [InlineKeyboardButton("💰 Купить доступ (50 руб.)", callback_data='buy')],
            [InlineKeyboardButton("🎁 Бесплатный пробный период (7 дней)", callback_data='trial')],
            [InlineKeyboardButton("📱 Мои конфиги", callback_data='my_configs')],
            [InlineKeyboardButton("❓ Помощь", callback_data='help')]
        ]
        
        if is_admin(user_id):
            keyboard.append([InlineKeyboardButton("👑 Админ панель", callback_data='admin')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🔒 Добро пожаловать в OpenVPN сервис!\n\n"
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
        config = load_config()
        conn = sqlite3.connect(config.get('db_path', 'vpn_bot.db'))
        cursor = conn.cursor()
        cursor.execute("""
            SELECT config_name, status, expires_at, is_trial, is_paid 
            FROM users WHERE user_id = ? ORDER BY created_at DESC
        """, (user_id,))
        configs = cursor.fetchall()
        conn.close()
        
        if configs:
            text = "📱 Ваши конфигурации:\n\n"
            for config in configs:
                status_emoji = "✅" if config[1] == 'active' else "❌"
                config_type = "🎁 Пробный" if config[3] == 1 else "💳 Платный"
                text += f"{status_emoji} {config_type} - {config[0]}\n"
                if config[2]:
                    text += f"⏰ До: {config[2]}\n"
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
                         f"⏰ Действует до: {result['expires_at']}"
                )
                
                # Отправляем QR код
                if result['qr_buffer']:
                    await context.bot.send_photo(
                        chat_id=user_id,
                        photo=result['qr_buffer'],
                        caption="QR код для импорта в OpenVPN"
                    )
                
                # Отправляем конфиг файл
                with tempfile.NamedTemporaryFile(mode='w+', suffix='.ovpn', delete=False) as temp_file:
                    temp_file.write(result['config'])
                    temp_file.flush()
                    
                    with open(temp_file.name, 'rb') as config_file:
                        await context.bot.send_document(
                            chat_id=user_id,
                            document=config_file,
                            filename=f"{result['config_name']}.ovpn",
                            caption="Конфигурационный файл OpenVPN"
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
        config = load_config()
        conn = sqlite3.connect(config.get('db_path', 'vpn_bot.db'))
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
                text=f"🎁 Пробный период активирован на {config['trial_days']} дней!\n\n"
                     f"🔧 Имя конфига: {result['config_name']}\n"
                     f"⏰ Действует до: {result['expires_at']}"
            )
            
            # Отправляем QR код
            if result['qr_buffer']:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=result['qr_buffer'],
                    caption="QR код для импорта в OpenVPN"
                )
            
            # Отправляем конфиг файл
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.ovpn', delete=False) as temp_file:
                temp_file.write(result['config'])
                temp_file.flush()
                
                with open(temp_file.name, 'rb') as config_file:
                    await context.bot.send_document(
                        chat_id=user_id,
                        document=config_file,
                        filename=f"{result['config_name']}.ovpn",
                        caption="Конфигурационный файл OpenVPN"
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
🤖 **OpenVPN Bot - Помощь**

📋 **Доступные команды:**
/start - Главное меню
/myconfigs - Мои конфигурации

💡 **Как использовать:**
1. Нажмите «Бесплатный пробный период»
2. Получите конфиг и QR код
3. Импортируйте в приложение OpenVPN

📱 **Приложения:**
- OpenVPN Connect (iOS/Android)
- OpenVPN GUI (Windows)
- Tunnelblick (macOS)

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
        f"🌐 Сервер: {config['server_ip']}:{config['server_port']}\n"
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
        config = load_config()
        conn = sqlite3.connect(config.get('db_path', 'vpn_bot.db'))
        cursor = conn.cursor()
        cursor.execute("""
            SELECT config_name, status, expires_at, is_trial, is_paid 
            FROM users WHERE user_id = ? ORDER BY created_at DESC
        """, (user_id,))
        configs = cursor.fetchall()
        conn.close()
        
        if configs:
            text = "📱 Ваши конфигурации:\n\n"
            for config in configs:
                status_emoji = "✅" if config[1] == 'active' else "❌"
                config_type = "🎁 Пробный" if config[3] == 1 else "💳 Платный"
                text += f"{status_emoji} {config_type} - {config[0]}\n"
                if config[2]:
                    text += f"⏰ До: {config[2]}\n"
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
        text=f"👑 Админ панель\n\nСервер: {config['server_ip']}:{config['server_port']}",
        reply_markup=reply_markup
    )

async def admin_stats(query, context):
    if not is_admin(query.from_user.id):
        return
    
    try:
        config = load_config()
        conn = sqlite3.connect(config.get('db_path', 'vpn_bot.db'))
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
🌐 Сервер: {config['server_ip']}:{config['server_port']}
        """
        
        await context.bot.send_message(chat_id=query.from_user.id, text=stats_text)
    except Exception as e:
        logger.error(f"Admin stats error: {e}")

def main():
    try:
        # Инициализация
        config = init_config()
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
