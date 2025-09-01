import os
import sqlite3

# Токен бота от @BotFather
BOT_TOKEN = "7953514140:AAGg-AgyL6Y2mvzfyKesnpouJkU6p_B8Zeo"

# Админ пользователи
ADMINS = [5631675412]

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
