import os

# Токен бота от @BotFather
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

# ID администратора (ваш Telegram ID)
ADMIN_ID = YOUR_ADMIN_ID_HERE

# Настройки оплаты
YOOMONEY_TOKEN = "YOUR_YOOMONEY_TOKEN_HERE"
CLOUDTIPSBOT_TOKEN = "YOUR_CLOUDTIPSBOT_TOKEN_HERE"

# Настройки OpenVPN
OVPN_DIR = "/etc/openvpn/"  # Директория с OpenVPN
OVPN_KEYS_DIR = "/etc/openvpn/easy-rsa/keys/"  # Директория с ключами
OVPN_CONFIG_TEMPLATE = "/etc/openvpn/client-template.ovpn"  # Шаблон конфига

# Настройки тарифов
PRICE = 300  # Цена за месяц в рублях
TRIAL_PERIOD_DAYS = 7  # Пробный период для новых пользователей
REFERRAL_BONUS_DAYS = 7  # Бонус за реферала

# Настройки сервера
SERVER_SPEED = "100"  # Скорость в Mbps
SERVER_DNS = "1.1.1.1"  # DNS сервер
SERVER_PORT = "1194"  # Порт OpenVPN

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
