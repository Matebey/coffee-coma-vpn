import os
import sqlite3

# Токен бота от @BotFather - ЗАМЕНИТЕ НА СВОЙ!
BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"

# Админ пользователи - ЗАМЕНИТЕ НА СВОЙ ID!
ADMINS = [ВАШ_TELEGRAM_ID]

# Пути
OVPN_KEYS_DIR = "/etc/openvpn/easy-rsa/pki/"
OVPN_CLIENT_DIR = "/etc/openvpn/client-configs/"
DB_PATH = "/opt/coffee-coma-vpn/vpn_bot.db"

# Настройки
REFERRAL_REWARD_DAYS = 5
TRIAL_DAYS = 5
DEFAULT_SPEED_LIMIT = 10
TRIAL_SPEED_LIMIT = 5

# Создаем директории
os.makedirs(OVPN_CLIENT_DIR, exist_ok=True)
