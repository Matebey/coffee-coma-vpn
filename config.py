import os
import sqlite3
import requests
import time

# Токен бота от @BotFather - ЗАМЕНИТЕ НА СВОЙ!
BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"

# Настройки ЮMoney - ЗАМЕНИТЕ НА СВОИ!
YOOMONEY_WALLET = "ВАШ_НОМЕР_КОШЕЛЬКА"
YOOMONEY_SECRET = "ВАШ_СЕКРЕТНЫЙ_КЛЮЧ"

# Настройки CloudTips - ЗАМЕНИТЕ НА СВОИ!
CLOUDTIPS_TOKEN = "ВАШ_CLOUDTIPS_TOKEN"

# Настройки OpenVPN
OVPN_CONFIG_DIR = "/etc/openvpn/server/"
OVPN_CLIENT_DIR = "/etc/openvpn/client-configs/"
OVPN_KEYS_DIR = "/etc/openvpn/easy-rsa/pki/"

# Путь к базе данных
DB_PATH = "/opt/coffee-coma-vpn/vpn_bot.db"

# Админ пользователи - ЗАМЕНИТЕ НА СВОЙ ID!
ADMINS = [123456789]  # Замените на ваш Telegram ID

# Настройки реферальной программы
REFERRAL_REWARD_DAYS = 5
TRIAL_DAYS = 5
DEFAULT_SPEED_LIMIT = 10
TRIAL_SPEED_LIMIT = 5

# IP сервера - ЗАМЕНИТЕ НА ВАШ IP!
SERVER_IP = "77.239.105.17"

# Создаем директории
os.makedirs(OVPN_CLIENT_DIR, exist_ok=True)

class YooMoneyAPI:
    def __init__(self, wallet, secret):
        self.wallet = wallet
        self.secret = secret
    
    def check_payment(self, label, amount):
        """Проверяет наличие платежа по метке"""
        try:
            # В реальной реализации используйте официальное API ЮMoney
            import time
            time.sleep(2)
            return False  # Для демо всегда возвращаем False
            
        except Exception as e:
            print(f"Ошибка проверки платежа: {e}")
            return False

class CloudTipsAPI:
    def __init__(self, token):
        self.token = token
        self.base_url = "https://api.cloudtips.ru/api"
    
    def create_payment(self, amount, description):
        """Создает платеж в CloudTips"""
        try:
            # Демо-реализация CloudTips API
            return {
                'success': True,
                'payment_url': f"https://cloudtips.ru/payment?amount={amount}",
                'payment_id': f"ct_{int(time.time())}"
            }
        except Exception as e:
            print(f"Ошибка создания платежа CloudTips: {e}")
            return {'success': False}

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

# Инициализация API
yoomoney_api = YooMoneyAPI(YOOMONEY_WALLET, YOOMONEY_SECRET)
cloudtips_api = CloudTipsAPI(CLOUDTIPS_TOKEN)

# Динамические настройки
PRICES = {
    "1_month": int(get_setting('price', 50))
}

DNS_SERVERS = [get_setting('dns1', '8.8.8.8'), get_setting('dns2', '8.8.4.4')]
OVPN_PORT = get_setting('port', '1194')
