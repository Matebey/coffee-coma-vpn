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

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация (ЗАМЕНИТЕ НА СВОИ ЗНАЧЕНИЯ!)
BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"
ADMINS = [ВАШ_TELEGRAM_ID]  # Ваш Telegram ID

# Пути
OVPN_KEYS_DIR = "/etc/openvpn/easy-rsa/pki/"
OVPN_CLIENT_DIR = "/etc/openvpn/client-configs/"
DB_PATH = "/opt/coffee-coma-vpn/vpn_bot.db"

# Настройки
REFERRAL_REWARD_DAYS = 5
TRIAL_DAYS = 5
DEFAULT_SPEED_LIMIT = 10
TRIAL_SPEED_LIMIT = 5

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
        
        # Настройки по умолчанию
        cursor.execute('INSERT OR IGNORE INTO settings VALUES ("dns1", "8.8.8.8")')
        cursor.execute('INSERT OR IGNORE INTO settings VALUES ("dns2", "8.8.4.4")')
        cursor.execute('INSERT OR IGNORE INTO settings VALUES ("port", "1194")')
        cursor.execute('INSERT OR IGNORE INTO settings VALUES ("price", "50")')
        cursor.execute('INSERT OR IGNORE INTO settings VALUES ("speed_limit", "10")')
        cursor.execute('INSERT OR IGNORE INTO settings VALUES ("yoomoney_wallet", "4100117852673007")')
        
        self.conn.commit()

    def clean_expired_subscriptions(self):
        """Удаляет просроченные подписки"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM subscriptions WHERE end_date < datetime("now")')
            self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка очистки подписок: {e}")

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
                INSERT INTO subscriptions 
                (user_id, client_name, config_path, start_date, end_date, speed_limit, is_trial)
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

    def get_all_subscriptions(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT s.user_id, s.client_name, s.config_path, s.end_date, s.speed_limit, u.first_name
            FROM subscriptions s JOIN users u ON s.user_id = u.user_id
            WHERE s.end_date > datetime("now") ORDER BY s.end_date DESC
        ''')
        return cursor.fetchall()

    def delete_subscription(self, client_name):
        try:
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM subscriptions WHERE client_name = ?', (client_name,))
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Ошибка удаления подписки: {e}")
            return False

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

    def get_referral_stats(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND reward_claimed = 0', (user_id,))
        pending_rewards = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,))
        total_referrals = cursor.fetchone()[0]
        return pending_rewards, total_referrals

    def claim_referral_reward(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE referrals SET reward_claimed = 1 WHERE referrer_id = ? AND reward_claimed = 0', (user_id,))
        self.conn.commit()
        return cursor.rowcount

class OpenVPNManager:
    def create_client_config(self, client_name, speed_limit=10):
        try:
            # Создаем сертификат
            subprocess.run([
                '/usr/bin/env', 'bash', '-c', 
                f'cd /etc/openvpn/easy-rsa && ./easyrsa --batch gen-req {client_name} nopass'
            ], check=True, timeout=30)
            
            # Подписываем сертификат
            subprocess.run([
                '/usr/bin/env', 'bash', '-c', 
                f'cd /etc/openvpn/easy-rsa && echo "yes" | ./easyrsa --batch sign-req client {client_name}'
            ], check=True, timeout=30)
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"Ошибка создания сертификата")

        # Читаем файлы сертификатов
        cert_path = f"{OVPN_KEYS_DIR}issued/{client_name}.crt"
        key_path = f"{OVPN_KEYS_DIR}private/{client_name}.key"
        
        if not os.path.exists(cert_path) or not os.path.exists(key_path):
            raise Exception("Файлы сертификатов не созданы")

        dns1 = "8.8.8.8"
        dns2 = "8.8.4.4"
        port = "1194"
        
        # Получаем IP сервера
        try:
            server_ip = subprocess.check_output("curl -s ifconfig.me", shell=True).decode().strip()
        except:
            server_ip = "your_server_ip"

        config_content = f'''client
dev tun
proto udp
remote {server_ip} {port}
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
cipher AES-256-CBC
verb 3
<ca>
{open(f"{OVPN_KEYS_DIR}ca.crt").read()}
</ca>
<cert>
{open(cert_path).read()}
</cert>
<key>
{open(key_path).read()}
</key>
<tls-auth>
{open(f"{OVPN_KEYS_DIR}ta.key").read()}
</tls-auth>
key-direction 1
'''

        config_path = f"{OVPN_CLIENT_DIR}{client_name}.ovpn"
        with open(config_path, 'w') as f:
            f.write(config_content)
        
        return config_path

    def revoke_client(self, client_name):
        try:
            subprocess.run([
                '/usr/bin/env', 'bash', '-c', 
                f'cd /etc/openvpn/easy-rsa && echo "yes" | ./easyrsa --batch revoke {client_name}'
            ], check=True, timeout=30)
            
            subprocess.run([
                '/usr/bin/env', 'bash', '-c', 
                f'cd /etc/openvpn/easy-rsa && ./easyrsa --batch gen-crl'
            ], check=True, timeout=30)
            
            subprocess.run(['systemctl', 'restart', 'openvpn@server'], check=True, timeout=30)
            
            config_path = f"{OVPN_CLIENT_DIR}{client_name}.ovpn"
            if os.path.exists(config_path):
                os.remove(config_path)
                
            return True
            
        except subprocess.CalledProcessError:
            return False

class VPNBot:
    def __init__(self):
        self.db = Database()
        self.ovpn = OpenVPNManager()
        
        try:
            self.application = Application.builder().token(BOT_TOKEN).build()
            self.setup_handlers()
        except Exception as e:
            logger.error(f"Ошибка инициализации бота: {e}")
            raise

    def setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("buy", self.buy))
        self.application.add_handler(CommandHandler("myconfig", self.my_config))
        self.application.add_handler(CommandHandler("admin", self.admin_panel))
        self.application.add_handler(CommandHandler("trial", self.trial))
        self.application.add_handler(CommandHandler("referral", self.referral))
        self.application.add_handler(CallbackQueryHandler(self.button_handler))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        referred_by = None
        if context.args:
            referred_by = self.db.get_user_by_referral_code(context.args[0])
        
        referral_code = self.db.add_user(user.id, user.first_name, user.username, referred_by)
        
        keyboard = [
            [InlineKeyboardButton("🛒 Купить доступ", callback_data='buy')],
            [InlineKeyboardButton("📁 Мой конфиг", callback_data='myconfig')],
            [InlineKeyboardButton("🎁 Бесплатный пробный период", callback_data='trial')],
            [InlineKeyboardButton("👥 Реферальная программа", callback_data='referral')]
        ]
        
        if self.db.is_admin(user.id):
            keyboard.append([InlineKeyboardButton("👨‍💻 Админ панель", callback_data='admin_panel')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = f"Привет, {user.first_name}! 👋\n\n🤖 Добро пожаловать в Coffee Coma VPN!\n\nВыберите действие:"
        
        await update.message.reply_text(message, reply_markup=reply_markup)

    async def buy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        price = self.db.get_setting('price', 50)
        
        keyboard = [
            [InlineKeyboardButton(f"💳 Оплатить {price} руб", callback_data='check_payment')],
            [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"💰 Тарифы VPN\n\n1 месяц - {price} рублей\nСкорость: 10 Мбит/с\n\nДля проверки оплаты нажмите кнопку:",
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
            await update.message.reply_text("У вас нет активной подписки.")

    async def trial(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if self.db.has_used_trial(user_id):
            await update.message.reply_text("❌ Вы уже использовали бесплатный пробный период.")
            return
        
        try:
            client_name = f"trial_{user_id}_{int(datetime.now().timestamp())}"
            config_path = self.ovpn.create_client_config(client_name, TRIAL_SPEED_LIMIT)
            self.db.add_subscription(user_id, client_name, config_path, TRIAL_DAYS, TRIAL_SPEED_LIMIT, is_trial=True)
            
            await update.message.reply_document(
                document=open(config_path, 'rb'),
                caption=f"✅ Вам предоставлен бесплатный пробный период на {TRIAL_DAYS} дней!"
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")

    async def referral(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        cursor = self.db.conn.cursor()
        cursor.execute('SELECT referral_code FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        
        if not result:
            await update.message.reply_text("❌ Ошибка: реферальный код не найден")
            return
        
        referral_code = result[0]
        bot_username = (await self.application.bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start={referral_code}"
        
        pending_rewards, total_referrals = self.db.get_referral_stats(user_id)
        
        message = f"👥 Реферальная программа\n\nВаш код: {referral_code}\nВаша ссылка: {referral_link}\n\nПриглашено: {total_referrals}\nНаград: {pending_rewards}"
        
        await update.message.reply_text(message)

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.db.is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен")
            return
        
        keyboard = [
            [InlineKeyboardButton("⚙️ Настройки сервера", callback_data='admin_settings')],
            [InlineKeyboardButton("🗑️ Управление ключами", callback_data='admin_keys')],
            [InlineKeyboardButton("🎁 Выдать бесплатный доступ", callback_data='admin_free')],
            [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
            [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text("👨‍💻 Панель администратора", reply_markup=reply_markup)

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == 'buy':
            await self.buy_callback(query)
        elif data == 'myconfig':
            await self.my_config_callback(query)
        elif data == 'trial':
            await self.trial_callback(query)
        elif data == 'referral':
            await self.referral_callback(query)
        elif data == 'admin_panel':
            await self.admin_panel_callback(query)
        elif data == 'admin_settings':
            await self.settings_panel_callback(query)
        elif data == 'admin_keys':
            await self.manage_keys(query)
        elif data == 'admin_free':
            await self.create_free_config(query)
        elif data == 'admin_stats':
            await self.show_stats(query)
        elif data == 'check_payment':
            await self.check_payment_callback(query)
        elif data == 'main_menu':
            await self.show_main_menu(query)
        elif data.startswith('revoke_'):
            client_name = data.replace('revoke_', '')
            success = self.ovpn.revoke_client(client_name)
            if success:
                self.db.delete_subscription(client_name)
                await query.message.reply_text(f"✅ Ключ {client_name} отозван!")
            else:
                await query.message.reply_text(f"❌ Ошибка при отзыве ключа")

    async def buy_callback(self, query):
        user = query.from_user
        price = self.db.get_setting('price', 50)
        
        keyboard = [
            [InlineKeyboardButton(f"💳 Оплатить {price} руб", callback_data='check_payment')],
            [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(
            f"💰 Тарифы VPN\n\n1 месяц - {price} рублей\nСкорость: 10 Мбит/с\n\nДля проверки оплаты нажмите кнопку:",
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
            await query.message.edit_text("У вас нет активной подписки.")

    async def trial_callback(self, query):
        user_id = query.from_user.id
        
        if self.db.has_used_trial(user_id):
            await query.message.edit_text("❌ Вы уже использовали бесплатный пробный период.")
            return
        
        try:
            client_name = f"trial_{user_id}_{int(datetime.now().timestamp())}"
            config_path = self.ovpn.create_client_config(client_name, TRIAL_SPEED_LIMIT)
            self.db.add_subscription(user_id, client_name, config_path, TRIAL_DAYS, TRIAL_SPEED_LIMIT, is_trial=True)
            
            await query.message.reply_document(
                document=open(config_path, 'rb'),
                caption=f"✅ Вам предоставлен бесплатный пробный период на {TRIAL_DAYS} дней!"
            )
            
        except Exception as e:
            await query.message.edit_text(f"❌ Ошибка: {str(e)}")

    async def referral_callback(self, query):
        user_id = query.from_user.id
        
        cursor = self.db.conn.cursor()
        cursor.execute('SELECT referral_code FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        
        if not result:
            await query.message.edit_text("❌ Ошибка: реферальный код не найден")
            return
        
        referral_code = result[0]
        bot_username = (await self.application.bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start={referral_code}"
        
        pending_rewards, total_referrals = self.db.get_referral_stats(user_id)
        
        message = f"👥 Реферальная программа\n\nВаш код: {referral_code}\nВаша ссылка: {referral_link}\n\nПриглашено: {total_referrals}\nНаград: {pending_rewards}"
        
        await query.message.edit_text(message)

    async def admin_panel_callback(self, query):
        user_id = query.from_user.id
        if not self.db.is_admin(user_id):
            await query.message.edit_text("❌ Доступ запрещен")
            return
        
        keyboard = [
            [InlineKeyboardButton("⚙️ Настройки сервера", callback_data='admin_settings')],
            [InlineKeyboardButton("🗑️ Управление ключами", callback_data='admin_keys')],
            [InlineKeyboardButton("🎁 Выдать бесплатный доступ", callback_data='admin_free')],
            [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
            [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text("👨‍💻 Панель администратора", reply_markup=reply_markup)

    async def settings_panel_callback(self, query):
        user_id = query.from_user.id
        if not self.db.is_admin(user_id):
            await query.message.edit_text("❌ Доступ запрещен")
            return
        
        dns1 = self.db.get_setting('dns1', '8.8.8.8')
        dns2 = self.db.get_setting('dns2', '8.8.4.4')
        port = self.db.get_setting('port', '1194')
        price = self.db.get_setting('price', '50')
        speed_limit = self.db.get_setting('speed_limit', '10')
        
        keyboard = [
            [InlineKeyboardButton(f"🌐 DNS: {dns1} {dns2}", callback_data='change_dns')],
            [InlineKeyboardButton(f"🔌 Порт: {port}", callback_data='change_port')],
            [InlineKeyboardButton(f"💰 Цена: {price} руб", callback_data='change_price')],
            [InlineKeyboardButton(f"⚡ Скорость: {speed_limit} Мбит/с", callback_data='change_speed')],
            [InlineKeyboardButton("🔙 Назад", callback_data='admin_back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = f"⚙️ Настройки сервера:\nDNS: {dns1}, {dns2}\nПорт: {port}\nЦена: {price} руб\nСкорость: {speed_limit} Мбит/с"
        
        await query.message.edit_text(message, reply_markup=reply_markup)

    async def manage_keys(self, query):
        user_id = query.from_user.id
        if not self.db.is_admin(user_id):
            await query.message.edit_text("❌ Доступ запрещен")
            return
        
        subscriptions = self.db.get_all_subscriptions()
        
        if not subscriptions:
            await query.message.edit_text("❌ Нет активных подписок")
            return
        
        keyboard = []
        for user_id, client_name, config_path, end_date, speed_limit, first_name in subscriptions:
            keyboard.append([InlineKeyboardButton(
                f"🗑️ {client_name} ({first_name}) до {end_date[:10]}", 
                callback_data=f'revoke_{client_name}'
            )])
        
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_back')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text("🗑️ Выберите ключ для удаления:", reply_markup=reply_markup)

    async def create_free_config(self, query):
        user_id = query.from_user.id
        if not self.db.is_admin(user_id):
            await query.message.edit_text("❌ Доступ запрещен")
            return
        
        try:
            client_name = f"admin_{user_id}_{int(datetime.now().timestamp())}"
            speed_limit = int(self.db.get_setting('speed_limit', 10))
            config_path = self.ovpn.create_client_config(client_name, speed_limit)
            self.db.add_subscription(user_id, client_name, config_path, 7, speed_limit)
            
            await query.message.reply_document(
                document=open(config_path, 'rb'),
                caption=f"✅ Ваш бесплатный конфиг на 7 дней создан!"
            )
        except Exception as e:
            await query.message.edit_text(f"❌ Ошибка при создании конфига: {str(e)}")

    async def show_stats(self, query):
        user_id = query.from_user.id
        if not self.db.is_admin(user_id):
            await query.message.edit_text("❌ Доступ запрещен")
            return
        
        cursor = self.db.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users')
        users_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM subscriptions WHERE end_date > datetime("now")')
        active_subs = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM referrals')
        referrals_count = cursor.fetchone()[0]
        
        message = f"📊 Статистика:\nПользователей: {users_count}\nАктивных подписок: {active_subs}\nРефералов: {referrals_count}"
        
        await query.message.edit_text(message)

    async def check_payment_callback(self, query):
        user_id = query.from_user.id
        price = self.db.get_setting('price', 50)
        
        # Всегда говорим что оплата не найдена (для демо)
        await query.message.edit_text("❌ Оплата не найдена. Для тестирования используйте пробный период.")

    async def show_main_menu(self, query):
        user = query.from_user
        
        keyboard = [
            [InlineKeyboardButton("🛒 Купить доступ", callback_data='buy')],
            [InlineKeyboardButton("📁 Мой конфиг", callback_data='myconfig')],
            [InlineKeyboardButton("🎁 Бесплатный пробный период", callback_data='trial')],
            [InlineKeyboardButton("👥 Реферальная программа", callback_data='referral')]
        ]
        
        if self.db.is_admin(user.id):
            keyboard.append([InlineKeyboardButton("👨‍💻 Админ панель", callback_data='admin_panel')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text("🤖 Главное меню\n\nВыберите действие:", reply_markup=reply_markup)

    def run(self):
        self.application.run_polling()

if __name__ == "__main__":
    bot = VPNBot()
    bot.run()
