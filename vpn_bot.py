import logging
import sqlite3
import subprocess
import os
import re
import secrets
import string
import time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Попробуем импортировать config
try:
    from config import BOT_TOKEN, ADMINS, OVPN_CLIENT_DIR, DB_PATH, REFERRAL_REWARD_DAYS, TRIAL_DAYS, DEFAULT_SPEED_LIMIT, TRIAL_SPEED_LIMIT, SERVER_IP, cloudtips_api
except ImportError:
    # Значения по умолчанию
    BOT_TOKEN = "7953514140:AAGg-AgyL6Y2mvzfyKesnpouJkU6p_B8Zeo"
    ADMINS = [5631675412]
    OVPN_CLIENT_DIR = "/etc/openvpn/client-configs/"
    DB_PATH = "/opt/coffee-coma-vpn/vpn_bot.db"
    REFERRAL_REWARD_DAYS = 7
    TRIAL_DAYS = 7
    DEFAULT_SPEED_LIMIT = 10
    TRIAL_SPEED_LIMIT = 5
    SERVER_IP = "77.239.105.17"

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
        self.clean_expired_subscriptions()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                trial_used INTEGER DEFAULT 0
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                client_name TEXT UNIQUE,
                config_path TEXT,
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                speed_limit INTEGER DEFAULT 10,
                is_trial INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                referral_id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER,
                reward_claimed INTEGER DEFAULT 0,
                date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referrer_id) REFERENCES users (user_id),
                FOREIGN KEY (referred_id) REFERENCES users (user_id)
            )
        ''')
        self.conn.commit()

    def add_user(self, user_id, first_name, username, referred_by=None):
        try:
            cursor = self.conn.cursor()
            referral_code = self.generate_referral_code()
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, first_name, username, referral_code, referred_by)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, first_name, username, referral_code, referred_by))
            if referred_by:
                cursor.execute('INSERT OR IGNORE INTO referrals (referrer_id, referred_id) VALUES (?, ?)', (referred_by, user_id))
            self.conn.commit()
            return referral_code
        except Exception as e:
            logger.error(f"Ошибка добавления пользователя: {e}")
            return None

    def generate_referral_code(self):
        alphabet = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(secrets.choice(alphabet) for _ in range(8))
            cursor = self.conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM users WHERE referral_code = ?', (code,))
            if cursor.fetchone()[0] == 0:
                return code

    def add_subscription(self, user_id, client_name, config_path, days, speed_limit=10, is_trial=False):
        try:
            start_date = datetime.now()
            end_date = start_date + timedelta(days=days)
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO subscriptions (user_id, client_name, config_path, start_date, end_date, speed_limit, is_trial)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, client_name, config_path, start_date, end_date, speed_limit, int(is_trial)))
            if is_trial:
                cursor.execute('UPDATE users SET trial_used = 1 WHERE user_id = ?', (user_id,))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка добавления подписки: {e}")
            raise

    def get_user_config(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT config_path FROM subscriptions WHERE user_id = ? AND end_date > datetime("now") ORDER BY end_date DESC LIMIT 1', (user_id,))
        result = cursor.fetchone()
        return result[0] if result else None

    def is_admin(self, user_id):
        return user_id in ADMINS

    def get_user_by_referral_code(self, referral_code):
        cursor = self.conn.cursor()
        cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (referral_code,))
        result = cursor.fetchone()
        return result[0] if result else None

    def has_used_trial(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT trial_used FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        return result[0] if result else 0

class OpenVPNManager:
    def __init__(self, db):
        self.db = db
    
    def create_client_config(self, client_name, speed_limit=10):
        try:
            # Создаем сертификаты
            subprocess.run([
                '/bin/bash', '-c', 
                f'cd /etc/openvpn/easy-rsa && ./easyrsa --batch gen-req {client_name} nopass'
            ], check=True, timeout=60, capture_output=True)
            
            subprocess.run([
                '/bin/bash', '-c', 
                f'cd /etc/openvpn/easy-rsa && echo "yes" | ./easyrsa --batch sign-req client {client_name}'
            ], check=True, timeout=60, capture_output=True)
            
            # ПРАВИЛЬНЫЕ ПУТИ К ФАЙЛАМ:
            ca_cert_path = "/etc/openvpn/ca.crt"
            ta_key_path = "/etc/openvpn/ta.key"
            client_cert_path = f"/etc/openvpn/easy-rsa/pki/issued/{client_name}.crt"
            client_key_path = f"/etc/openvpn/easy-rsa/pki/private/{client_name}.key"
            
            # Проверяем существование файлов
            for file_path in [ca_cert_path, ta_key_path, client_cert_path, client_key_path]:
                if not os.path.exists(file_path):
                    raise Exception(f"Файл не найден: {file_path}")
            
            # Читаем файлы
            with open(ca_cert_path, 'r') as f: 
                ca_cert = f.read()
            with open(client_cert_path, 'r') as f: 
                client_cert = f.read()
            with open(client_key_path, 'r') as f: 
                client_key = f.read()
            with open(ta_key_path, 'r') as f: 
                ta_key = f.read()

            # Создаем конфиг
            config_content = f'''client
dev tun
proto udp
remote {SERVER_IP} 1194
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
cipher AES-256-CBC
verb 3
<ca>
{ca_cert}
</ca>
<cert>
{client_cert}
</cert>
<key>
{client_key}
</key>
<tls-auth>
{ta_key}
</tls-auth>
key-direction 1
'''

            config_path = f"{OVPN_CLIENT_DIR}{client_name}.ovpn"
            with open(config_path, 'w') as f:
                f.write(config_content)
            
            return config_path
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"Ошибка создания сертификата: {e.stderr.decode()}")
        except Exception as e:
            raise Exception(f"Ошибка создания конфига: {str(e)}")

class VPNBot:
    def __init__(self):
        self.db = Database()
        self.ovpn = OpenVPNManager(self.db)
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.setup_handlers()
        logger.info("Бот инициализирован")

    def setup_handlers(self):
        """Настройка всех обработчиков команд"""
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("buy", self.buy))
        self.application.add_handler(CommandHandler("myconfig", self.my_config))
        self.application.add_handler(CommandHandler("admin", self.admin_panel))
        self.application.add_handler(CommandHandler("trial", self.trial))
        self.application.add_handler(CommandHandler("referral", self.referral))
        self.application.add_handler(CommandHandler("startbot", self.start_bot))
        self.application.add_handler(CommandHandler("stopbot", self.stop_bot))
        self.application.add_handler(CommandHandler("status", self.status))
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Обработчик для любых сообщений
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user = update.effective_user
            referred_by = None
            if context.args:
                referral_code = context.args[0]
                referred_by = self.db.get_user_by_referral_code(referral_code)
            referral_code = self.db.add_user(user.id, user.first_name, user.username, referred_by)
            await self.show_main_menu(update.message, user, referral_code)
        except Exception as e:
            logger.error(f"Ошибка в start: {e}")
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

    async def show_main_menu(self, message, user, referral_code=None):
        keyboard = [
            [InlineKeyboardButton("🛒 Купить доступ", callback_data='buy')],
            [InlineKeyboardButton("📁 Мой конфиг", callback_data='myconfig')],
            [InlineKeyboardButton("🎁 7 дней пробный период", callback_data='trial')],
            [InlineKeyboardButton("👥 Реферальная программа", callback_data='referral')]
        ]
        
        if self.db.is_admin(user.id):
            keyboard.append([InlineKeyboardButton("👨‍💻 Админ панель", callback_data='admin_panel')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = f"Привет, {user.first_name}! 👋\n\n🤖 Coffee Coma VPN\n\n"
        
        if referral_code:
            bot_username = (await self.application.bot.get_me()).username
            referral_link = f"https://t.me/{bot_username}?start={referral_code}"
            message_text += f"📋 Реферальный код: `{referral_code}`\n🔗 Ссылка: {referral_link}\n\n"
        
        message_text += "Выберите действие:"
        
        await message.reply_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')

    async def trial(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            if self.db.has_used_trial(user_id):
                await update.message.reply_text("❌ Вы уже использовали пробный период.")
                return
            
            client_name = f"trial_{user_id}_{int(time.time())}"
            config_path = self.ovpn.create_client_config(client_name, TRIAL_SPEED_LIMIT)
            self.db.add_subscription(user_id, client_name, config_path, TRIAL_DAYS, TRIAL_SPEED_LIMIT, True)
            
            await update.message.reply_document(
                document=open(config_path, 'rb'),
                caption=f"🎉 Пробный период на 7 дней!\n⚡ Скорость: {TRIAL_SPEED_LIMIT} Мбит/с\n🌐 Сервер: {SERVER_IP}"
            )
        except Exception as e:
            logger.error(f"Ошибка в trial: {e}")
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.db.is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен.")
            return
        
        keyboard = [
            [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
            [InlineKeyboardButton("🔄 Перезапустить бота", callback_data='admin_restart')],
            [InlineKeyboardButton("⏹ Остановить бота", callback_data='admin_stop')],
            [InlineKeyboardButton("🔧 Перезапустить OpenVPN", callback_data='admin_restart_ovpn')]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("👨‍💻 Админ-панель:", reply_markup=reply_markup)

    async def start_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.db.is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен.")
            return
        
        subprocess.run(["systemctl", "start", "coffee-coma-vpn.service"])
        await update.message.reply_text("✅ Бот запущен")

    async def stop_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.db.is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен.")
            return
        
        subprocess.run(["systemctl", "stop", "coffee-coma-vpn.service"])
        await update.message.reply_text("✅ Бот остановлен")

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.db.is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен.")
            return
        
        bot_status = subprocess.run(["systemctl", "is-active", "coffee-coma-vpn.service"], capture_output=True, text=True).stdout.strip()
        ovpn_status = subprocess.run(["systemctl", "is-active", "openvpn@server.service"], capture_output=True, text=True).stdout.strip()
        
        await update.message.reply_text(
            f"📊 Статус системы:\n\n"
            f"🤖 Бот: {bot_status}\n"
            f"🔌 OpenVPN: {ovpn_status}\n"
            f"🌐 IP: {SERVER_IP}\n"
            f"🚪 Порт: 1194"
        )

    async def buy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "💰 Тарифы:\n\n"
            "• 1 месяц - 50 руб\n"
            "• 3 месяца - 120 руб\n"
            "• 6 месяцев - 200 руб\n\n"
            "💳 Оплата через CloudTips"
        )

    async def my_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        config_path = self.db.get_user_config(user_id)
        
        if config_path and os.path.exists(config_path):
            await update.message.reply_document(
                document=open(config_path, 'rb'),
                caption="📁 Ваш конфиг OpenVPN"
            )
        else:
            await update.message.reply_text("❌ У вас нет активной подписки.")

    async def referral(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        cursor = self.db.conn.cursor()
        cursor.execute('SELECT referral_code FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        
        if result:
            referral_code = result[0]
            bot_username = (await self.application.bot.get_me()).username
            referral_link = f"https://t.me/{bot_username}?start={referral_code}"
            
            await update.message.reply_text(
                f"👥 Реферальная программа\n\n"
                f"🔗 Ваша ссылка: {referral_link}\n"
                f"📋 Код: `{referral_code}`\n\n"
                f"💎 За каждого приглашенного друга вы получаете +7 дней к подписке!",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ Ошибка получения реферальной информации.")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка обычных сообщений"""
        message_text = update.message.text
        if message_text == "админ":
            await self.admin_panel(update, context)
        else:
            await update.message.reply_text("Используйте команды из меню 📋")

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        
        if data == 'trial':
            await self.trial(update, context)
        elif data == 'admin_panel':
            await self.admin_panel(update, context)
        elif data == 'admin_stop':
            await self.stop_bot(update, context)
        elif data == 'admin_restart':
            await update.message.reply_text("🔄 Перезапускаю бота...")
            os.system("systemctl restart coffee-coma-vpn.service")
        elif data == 'admin_restart_ovpn':
            await update.message.reply_text("🔄 Перезапускаю OpenVPN...")
            os.system("pkill openvpn && sleep 2 && /usr/sbin/openvpn --config /etc/openvpn/server.conf --daemon")
        elif data == 'admin_stats':
            await self.status(update, context)

    def run(self):
        logger.info("Запуск бота...")
        self.application.run_polling()

if __name__ == "__main__":
    try:
        bot = VPNBot()
        bot.run()
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
