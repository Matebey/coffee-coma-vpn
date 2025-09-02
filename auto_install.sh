#!/bin/bash

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Автоматическая установка VPN бота ===${NC}"

# Функция для проверки ошибок
check_error() {
    if [ $? -ne 0 ]; then
        echo -e "${RED}Ошибка на шаге: $1${NC}"
        exit 1
    fi
}

# Функция для ввода данных
input_data() {
    echo -e "${YELLOW}Введите данные для настройки:${NC}"
    
    read -p "Введите токен бота от @BotFather: " BOT_TOKEN
    read -p "Введите ваш Telegram ID: " ADMIN_ID
    read -p "Введите токен YooMoney (или нажмите Enter чтобы пропустить): " YOOMONEY_TOKEN
    read -p "Введите токен CloudTips (или нажмите Enter чтобы пропустить): " CLOUDTIPSBOT_TOKEN
    
    # Если токены не введены, ставим заглушки
    if [ -z "$YOOMONEY_TOKEN" ]; then
        YOOMONEY_TOKEN="your_yoomoney_token_here"
    fi
    if [ -z "$CLOUDTIPSBOT_TOKEN" ]; then
        CLOUDTIPSBOT_TOKEN="your_cloudtips_token_here"
    fi
}

# Функция установки зависимостей
install_dependencies() {
    echo -e "${YELLOW}Установка системных зависимостей...${NC}"
    apt update && apt upgrade -y
    apt install -y python3 python3-pip python3-venv git sqlite3 openvpn easy-rsa
    check_error "Установка системных зависимостей"
}

# Функция настройки OpenVPN
setup_openvpn() {
    echo -e "${YELLOW}Настройка OpenVPN...${NC}"
    
    # Копируем easy-rsa
    cp -r /usr/share/easy-rsa/ /etc/openvpn/
    mkdir -p /etc/openvpn/easy-rsa/keys
    mkdir -p /etc/openvpn/client-configs
    
    # Создаем шаблон конфига клиента
    cat > /etc/openvpn/client-template.ovpn << 'EOL'
client
dev tun
proto udp
remote YOUR_SERVER_IP 1194
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
cipher AES-256-CBC
verb 3
key-direction 1

<ca>
</ca>

<cert>
</cert>

<key>
</key>
EOL

    # Настраиваем сервер OpenVPN (упрощенная версия)
    cat > /etc/openvpn/server.conf << 'EOL'
port 1194
proto udp
dev tun
ca /etc/openvpn/easy-rsa/keys/ca.crt
cert /etc/openvpn/easy-rsa/keys/server.crt
key /etc/openvpn/easy-rsa/keys/server.key
dh /etc/openvpn/easy-rsa/keys/dh2048.pem
server 10.8.0.0 255.255.255.0
ifconfig-pool-persist ipp.txt
push "redirect-gateway def1 bypass-dhcp"
push "dhcp-option DNS 1.1.1.1"
push "dhcp-option DNS 1.0.0.1"
keepalive 10 120
cipher AES-256-CBC
comp-lzo
user nobody
group nogroup
persist-key
persist-tun
status openvpn-status.log
verb 3
explicit-exit-notify 1
EOL

    # Генерируем CA и сертификаты
    cd /etc/openvpn/easy-rsa/
    ./easyrsa init-pki
    echo -e "\n\n" | ./easyrsa build-ca nopass
    echo -e "\n\n" | ./easyrsa gen-req server nopass
    echo -e "yes\n\n" | ./easyrsa sign-req server server
    ./easyrsa gen-dh
    openvpn --genkey --secret ta.key
    
    # Копируем файлы в нужные директории
    cp pki/ca.crt /etc/openvpn/
    cp pki/issued/server.crt /etc/openvpn/
    cp pki/private/server.key /etc/openvpn/
    cp pki/dh.pem /etc/openvpn/
    cp ta.key /etc/openvpn/
    
    check_error "Настройка OpenVPN"
}

# Функция создания виртуального окружения
create_venv() {
    echo -e "${YELLOW}Создание виртуального окружения...${NC}"
    python3 -m venv venv
    source venv/bin/activate
    
    # Устанавливаем Python зависимости
    pip install python-telegram-bot==20.7 pyyaml==6.0 requests==2.31.0
    check_error "Установка Python зависимостей"
}

# Функция создания конфигурационных файлов
create_config_files() {
    echo -e "${YELLOW}Создание конфигурационных файлов...${NC}"
    
    # Создаем config.py
    cat > config.py << EOL
import os

# Токен бота от @BotFather
BOT_TOKEN = "$BOT_TOKEN"

# ID администратора (ваш Telegram ID)
ADMIN_ID = $ADMIN_ID

# Настройки оплаты
YOOMONEY_TOKEN = "$YOOMONEY_TOKEN"
CLOUDTIPSBOT_TOKEN = "$CLOUDTIPSBOT_TOKEN"

# Настройки OpenVPN
OVPN_DIR = "/etc/openvpn/"
OVPN_KEYS_DIR = "/etc/openvpn/easy-rsa/keys/"
OVPN_CONFIG_TEMPLATE = "/etc/openvpn/client-template.ovpn"

# Настройки тарифов
PRICE = 300
TRIAL_PERIOD_DAYS = 7
REFERRAL_BONUS_DAYS = 7

# Настройки сервера
SERVER_SPEED = "100"
SERVER_DNS = "1.1.1.1"
SERVER_PORT = "1194"

# Настройки базы данных
DB_PATH = "database.db"

# Текст сообщений
MESSAGES = {
    "start": "Добро пожаловать в VPN сервис!",
    "menu": "Главное меню:",
    "buy": "Выберите тариф:",
    "profile": "Ваш профиль:",
    "admin": "Админ панель:"
}
EOL

    # Создаем основной файл бота
    cat > bot.py << 'EOL'
import logging
import sqlite3
import subprocess
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
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
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                await context.bot.send_document(
                    chat_id=user.id,
                    document=config_file,
                    caption=f"Ваш пробный ключ на {config.TRIAL_PERIOD_DAYS} дней!"
                )
    
    conn.commit()
    conn.close()
    
    # Показываем главное меню
    await show_main_menu(update, context)

# Главное меню
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🛒 Купить доступ", callback_data='buy')],
        [InlineKeyboardButton("🔑 Мои ключи", callback_data='my_keys')],
        [InlineKeyboardButton("👤 Мой профиль", callback_data='profile')],
        [InlineKeyboardButton("🎁 Бесплатный ключ", callback_data='free_key')]
    ]
    
    if update.effective_user.id == config.ADMIN_ID:
        keyboard.append([InlineKeyboardButton("⚙️ Админ панель", callback_data='admin')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if hasattr(update, 'callback_query') and update.callback_query:
        await update.callback_query.edit_message_text(
            text=config.MESSAGES['menu'],
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            text=config.MESSAGES['menu'],
            reply_markup=reply_markup
        )

# Обработчик callback запросов
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'buy':
        await show_buy_options(query)
    elif query.data == 'profile':
        await show_profile(query)
    elif query.data == 'admin':
        await show_admin_panel(query)
    elif query.data == 'back_to_menu':
        await show_main_menu(update, context)
    else:
        await query.edit_message_text("Функция в разработке")

# Показ вариантов покупки
async def show_buy_options(query):
    keyboard = [
        [InlineKeyboardButton("1 месяц - 300 руб.", callback_data='buy_1')],
        [InlineKeyboardButton("3 месяца - 800 руб.", callback_data='buy_3')],
        [InlineKeyboardButton("6 месяцев - 1500 руб.", callback_data='buy_6')],
        [InlineKeyboardButton("Назад", callback_data='back_to_menu')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=config.MESSAGES['buy'],
        reply_markup=reply_markup
    )

# Показ профиля пользователя
async def show_profile(query):
    user = query.from_user
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
        
        await query.edit_message_text(
            text=profile_text,
            reply_markup=reply_markup
        )
    
    conn.close()

# Админ панель
async def show_admin_panel(query):
    if query.from_user.id != config.ADMIN_ID:
        await query.edit_message_text("У вас нет доступа к админ панели!")
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
    
    await query.edit_message_text(
        text=config.MESSAGES['admin'],
        reply_markup=reply_markup
    )

# Главная функция
def main():
    # Инициализация базы данных
    init_db()
    
    # Создаем Application
    application = Application.builder().token(config.BOT_TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Запускаем бота
    print("Бот запускается...")
    application.run_polling()

if __name__ == '__main__':
    main()
EOL

    # Создаем скрипт запуска
    cat > start_bot.sh << 'EOL'
#!/bin/bash
cd /root/coffee-coma-vpn
source venv/bin/activate
python bot.py
EOL

    chmod +x start_bot.sh
    check_error "Создание конфигурационных файлов"
}

# Функция настройки сервиса
setup_service() {
    echo -e "${YELLOW}Настройка сервиса для автозапуска...${NC}"
    
    cat > /etc/systemd/system/vpn-bot.service << 'EOL'
[Unit]
Description=VPN Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/coffee-coma-vpn
ExecStart=/root/coffee-coma-vpn/start_bot.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOL

    systemctl daemon-reload
    systemctl enable vpn-bot.service
    check_error "Настройка сервиса"
}

# Функция завершения установки
finish_installation() {
    echo -e "${GREEN}=== Установка завершена! ===${NC}"
    echo -e "${YELLOW}Следующие шаги:${NC}"
    echo "1. Запустите бота: systemctl start vpn-bot"
    echo "2. Проверьте статус: systemctl status vpn-bot"
    echo "3. Настройте файрвол для OpenVPN порта 1194:"
    echo "   ufw allow 1194/udp"
    echo "4. Перезагрузите OpenVPN: systemctl restart openvpn"
    echo ""
    echo -e "${GREEN}Бот готов к работе!${NC}"
}

# Основной процесс установки
main() {
    input_data
    install_dependencies
    setup_openvpn
    create_venv
    create_config_files
    setup_service
    finish_installation
}

# Запуск установки
main
