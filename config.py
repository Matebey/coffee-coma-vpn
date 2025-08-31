import os
import sqlite3

# Токен бота от @BotFather
BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"

# Настройки ЮMoney
YOOMONEY_CLIENT_ID = "your_client_id"
YOOMONEY_REDIRECT_URI = "https://yourdomain.com/callback"
YOOMONEY_CLIENT_SECRET = "your_client_secret"
YOOMONEY_ACCESS_TOKEN = "your_access_token"
YOOMONEY_WALLET = "your_wallet_number"

# Настройки OpenVPN
OVPN_CONFIG_DIR = "/etc/openvpn/server/"
OVPN_CLIENT_DIR = "/etc/openvpn/client-configs/"
OVPN_KEYS_DIR = "/etc/openvpn/easy-rsa/pki/"

# Путь к базе данных
DB_PATH = "/opt/coffee-coma-vpn/vpn_bot.db"

# Админ пользователи (замените на ваш Telegram ID)
ADMINS = [123456789]

# Создаем директории
os.makedirs(OVPN_CLIENT_DIR, exist_ok=True)

# Функция для получения настроек из БД
def get_setting(key, default=None):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else default
    except:
        return default

# Динамические настройки
PRICES = {
    "1_month": int(get_setting('price', 50))
}

DNS_SERVERS = [get_setting('dns1', '8.8.8.8'), get_setting('dns2', '8.8.4.4')]
OVPN_PORT = get_setting('port', '1194')