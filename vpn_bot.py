import logging
import sqlite3
import subprocess
import os
import re
import secrets
import string
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from config import BOT_TOKEN, ADMINS, OVPN_KEYS_DIR, OVPN_CLIENT_DIR, DB_PATH, DNS_SERVERS, OVPN_PORT, yoomoney_api, PRICES

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER PRIMARY KEY,
                client_name TEXT,
                config_path TEXT,
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        self.conn.commit()

    def add_user(self, user_id, first_name, username):
        cursor = self.conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO users (user_id, first_name, username) VALUES (?, ?, ?)', 
                      (user_id, first_name, username))
        self.conn.commit()

    def add_subscription(self, user_id, client_name, config_path, days):
        start_date = datetime.now()
        end_date = start_date + timedelta(days=days)
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO subscriptions (user_id, client_name, config_path, start_date, end_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, client_name, config_path, start_date, end_date))
        self.conn.commit()

    def get_user_config(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT config_path FROM subscriptions WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        return result[0] if result else None

    def is_admin(self, user_id):
        return user_id in ADMINS

    def update_setting(self, key, value):
        cursor = self.conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        self.conn.commit()
        return True

    def get_setting(self, key, default=None):
        cursor = self.conn.cursor()
        cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
        result = cursor.fetchone()
        return result[0] if result else default

class OpenVPNManager:
    def create_client_config(self, client_name):
        try:
            # Создаем сертификат
            subprocess.run([
                'cd', '/etc/openvpn/easy-rsa', 
                '&&', './easyrsa', '--batch', 'gen-req', client_name, 'nopass'
            ], check=True, capture_output=True, timeout=30)
            
            # Подписываем сертификат
            subprocess.run([
                'cd', '/etc/openvpn/easy-rsa',
                '&&', 'echo', 'yes', '|', './easyrsa', '--batch', 'sign-req', 'client', client_name
            ], check=True, capture_output=True, timeout=30)
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"Ошибка создания сертификата: {e.stderr}")

        # Читаем файлы сертификатов
        cert_path = os.path.join(OVPN_KEYS_DIR, 'issued', f'{client_name}.crt')
        key_path = os.path.join(OVPN_KEYS_DIR, 'private', f'{client_name}.key')
        
        if not os.path.exists(cert_path) or not os.path.exists(key_path):
            raise Exception("Файлы сертификатов не созданы")

        server_ip = subprocess.check_output("curl -s ifconfig.me", shell=True).decode().strip()

        config_content = f'''client
dev tun
proto udp
remote {server_ip} {OVPN_PORT}
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
cipher AES-256-CBC
verb 3
<ca>
{open(os.path.join(OVPN_KEYS_DIR, 'ca.crt')).read()}
</ca>
<cert>
{open(cert_path).read()}
</cert>
<key>
{open(key_path).read()}
</key>
<tls-auth>
{open(os.path.join(OVPN_KEYS_DIR, 'ta.key')).read()}
</tls-auth>
key-direction 1
'''

        config_path = os.path.join(OVPN_CLIENT_DIR, f'{client_name}.ovpn')
        with open(config_path, 'w') as f:
            f.write(config_content)
        
        return config_path

class VPNBot:
    def __init__(self):
        self.db = Database()
        self.ovpn = OpenVPNManager()
        
        try:
            self.application = Application.builder().token(BOT_TOKEN).build()
            self.setup_handlers()
            logger.info("Бот инициализирован успешно")
        except Exception as e:
            logger.error(f"Ошибка инициализации бота: {e}")
            raise

    def setup_handlers(self):
        """Настройка обработчиков команд"""
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("buy", self.buy))
        self.application.add_handler(CommandHandler("myconfig", self.my_config))
        self.application.add_handler(CommandHandler("admin", self.admin_panel))
        self.application.add_handler(CommandHandler("checkpayment", self.check_payment))
        self.application.add_handler(CallbackQueryHandler(self.button_handler))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        self.db.add_user(user.id, user.first_name, user.username)
        
        keyboard = [
            [InlineKeyboardButton("🛒 Купить доступ", callback_data='buy')],
            [InlineKeyboardButton("📁 Мой конфиг", callback_data='myconfig')]
        ]
        
        if self.db.is_admin(user.id):
            keyboard.append([InlineKeyboardButton("👨‍💻 Админ панель", callback_data='admin_panel')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"Привет, {user.first_name}!\\n\\n"
            "🤖 Coffee Coma VPN Bot\\n\\n"
            "Выберите действие:",
            reply_markup=reply_markup
        )

    async def buy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        price = self.db.get_setting('price', 50)
        
        keyboard = [
            [InlineKeyboardButton(f"💳 Оплатить {price} руб", callback_data='check_payment')],
            [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"Оплатите {price} рублей за доступ на 1 месяц\\n\\n"
            "После оплаты нажмите кнопку ниже:",
            reply_markup=reply_markup
        )

    async def check_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        price = self.db.get_setting('price', 50)
        
        # Всегда говорим что оплата не найдена (для тестирования)
        keyboard = [
            [InlineKeyboardButton("🔄 Попробовать снова", callback_data='check_payment')],
            [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "❌ Оплата не найдена. Пожалуйста, подождите несколько минут или проверьте правильность оплаты.",
            reply_markup=reply_markup
        )

    async def my_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        config_path = self.db.get_user_config(user_id)
        
        if config_path and os.path.exists(config_path):
            await update.message.reply_document(
                document=open(config_path, 'rb'),
                caption="Ваш конфигурационный файл OpenVPN"
            )
        else:
            await update.message.reply_text("У вас нет активной подписки. Купите доступ /buy")

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.db.is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен")
            return
        
        await update.message.reply_text("👨‍💻 Админ панель в разработке...")

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == 'buy':
            await self.buy_callback(query)
        elif data == 'myconfig':
            await self.my_config_callback(query)
        elif data == 'admin_panel':
            await self.admin_panel_callback(query)
        elif data == 'check_payment':
            await self.check_payment_callback(query)
        elif data == 'main_menu':
            await self.main_menu_callback(query)

    async def buy_callback(self, query):
        user = query.from_user
        price = self.db.get_setting('price', 50)
        
        keyboard = [
            [InlineKeyboardButton(f"💳 Оплатить {price} руб", callback_data='check_payment')],
            [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(
            f"Оплатите {price} рублей за доступ на 1 месяц\\n\\n"
            "После оплаты нажмите кнопку ниже:",
            reply_markup=reply_markup
        )

    async def my_config_callback(self, query):
        user_id = query.from_user.id
        config_path = self.db.get_user_config(user_id)
        
        if config_path and os.path.exists(config_path):
            await query.message.reply_document(
                document=open(config_path, 'rb'),
                caption="Ваш конфигурационный файл OpenVPN"
            )
        else:
            await query.message.edit_text("У вас нет активной подписки. Купите доступ")

    async def admin_panel_callback(self, query):
        user_id = query.from_user.id
        if not self.db.is_admin(user_id):
            await query.message.edit_text("❌ Доступ запрещен")
            return
        
        await query.message.edit_text("👨‍💻 Админ панель в разработке...")

    async def check_payment_callback(self, query):
        user_id = query.from_user.id
        price = self.db.get_setting('price', 50)
        
        # Всегда говорим что оплата не найдена
        keyboard = [
            [InlineKeyboardButton("🔄 Попробовать снова", callback_data='check_payment')],
            [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(
            "❌ Оплата не найдена. Пожалуйста, подождите несколько минут или проверьте правильность оплаты.",
            reply_markup=reply_markup
        )

    async def main_menu_callback(self, query):
        user = query.from_user
        
        keyboard = [
            [InlineKeyboardButton("🛒 Купить доступ", callback_data='buy')],
            [InlineKeyboardButton("📁 Мой конфиг", callback_data='myconfig')]
        ]
        
        if self.db.is_admin(user.id):
            keyboard.append([InlineKeyboardButton("👨‍💻 Админ панель", callback_data='admin_panel')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(
            "🤖 Главное меню\\n\\nВыберите действие:",
            reply_markup=reply_markup
        )

    def run(self):
        self.application.run_polling()

if __name__ == "__main__":
    bot = VPNBot()
    bot.run()
