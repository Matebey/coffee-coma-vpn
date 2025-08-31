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
from config import BOT_TOKEN, ADMINS, OVPN_KEYS_DIR, OVPN_CLIENT_DIR, DB_PATH, DNS_SERVERS, OVPN_PORT, yoomoney_api, PRICES, REFERRAL_REWARD_DAYS, TRIAL_DAYS, DEFAULT_SPEED_LIMIT, TRIAL_SPEED_LIMIT

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
        logger.info("База данных инициализирована")

    def create_tables(self):
        cursor = self.conn.cursor()
        # Таблица пользователей
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
        # Таблица подписок
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
        # Таблица настроек
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        # Таблица рефералов
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
        
        self.conn.commit()
        logger.info("Таблицы базы данных созданы")

    def clean_expired_subscriptions(self):
        """Удаляет просроченные подписки"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                DELETE FROM subscriptions 
                WHERE end_date < datetime('now')
            ''')
            deleted_count = cursor.rowcount
            if deleted_count > 0:
                logger.info(f"Удалено {deleted_count} просроченных подписок")
            self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка очистки просроченных подписок: {e}")

    def add_user(self, user_id, first_name, username, referred_by=None):
        try:
            cursor = self.conn.cursor()
            referral_code = self.generate_referral_code()
            
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, first_name, username, referral_code, referred_by)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, first_name, username, referral_code, referred_by))
            
            if referred_by:
                cursor.execute('''
                    INSERT OR IGNORE INTO referrals (referrer_id, referred_id)
                    VALUES (?, ?)
                ''', (referred_by, user_id))
            
            self.conn.commit()
            logger.info(f"Добавлен пользователь: {user_id}")
            return referral_code
            
        except Exception as e:
            logger.error(f"Ошибка добавления пользователя: {e}")
            return None

    def generate_referral_code(self):
        """Генерирует уникальный реферальный код"""
        alphabet = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(secrets.choice(alphabet) for _ in range(8))
            cursor = self.conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM users WHERE referral_code = ?', (code,))
            if cursor.fetchone()[0] == 0:
                return code

    def add_subscription(self, user_id, client_name, config_path, days, speed_limit=10, is_trial=False):
        """Добавляет подписку пользователю"""
        try:
            start_date = datetime.now()
            end_date = start_date + timedelta(days=days)
            cursor = self.conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO subscriptions 
                (user_id, client_name, config_path, start_date, end_date, speed_limit, is_trial)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, client_name, config_path, start_date, end_date, speed_limit, int(is_trial)))
            
            if is_trial:
                cursor.execute('UPDATE users SET trial_used = 1 WHERE user_id = ?', (user_id,))
            
            self.conn.commit()
            logger.info(f"Добавлена подписка для {user_id} на {days} дней")
            
        except Exception as e:
            logger.error(f"Ошибка добавления подписки: {e}")
            raise

    def get_user_config(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT config_path FROM subscriptions 
            WHERE user_id = ? AND end_date > datetime('now')
            ORDER BY end_date DESC LIMIT 1
        ''', (user_id,))
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
            FROM subscriptions s
            JOIN users u ON s.user_id = u.user_id
            WHERE s.end_date > datetime('now')
            ORDER BY s.end_date DESC
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
        cursor.execute('''
            SELECT COUNT(*) FROM referrals 
            WHERE referrer_id = ? AND reward_claimed = 0
        ''', (user_id,))
        pending_rewards = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,))
        total_referrals = cursor.fetchone()[0]
        
        return pending_rewards, total_referrals

    def claim_referral_reward(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE referrals SET reward_claimed = 1 
            WHERE referrer_id = ? AND reward_claimed = 0
        ''', (user_id,))
        self.conn.commit()
        return cursor.rowcount

    def update_speed_limit(self, client_name, speed_limit):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE subscriptions SET speed_limit = ? WHERE client_name = ?', (speed_limit, client_name))
        self.conn.commit()
        return cursor.rowcount

class OpenVPNManager:
    def __init__(self):
        self.db = Database()

    def create_client_config(self, client_name, speed_limit=10):
        try:
            # Создаем запрос сертификата
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

        dns1 = self.db.get_setting('dns1', '8.8.8.8')
        dns2 = self.db.get_setting('dns2', '8.8.4.4')
        port = self.db.get_setting('port', '1194')
        server_ip = subprocess.check_output("curl -s ifconfig.me", shell=True).decode().strip()

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
        
        # Настраиваем ограничение скорости
        self.set_speed_limit(client_name, speed_limit)
        
        return config_path

    def set_speed_limit(self, client_name, speed_limit):
        """Устанавливает ограничение скорости для клиента"""
        try:
            # Создаем скрипт для ограничения скорости
            script_content = f'''#!/bin/bash
# Ограничение скорости для {client_name}
tc qdisc add dev tun0 root handle 1: htb default 30
tc class add dev tun0 parent 1: classid 1:1 htb rate {speed_limit}mbit
tc class add dev tun0 parent 1:1 classid 1:10 htb rate {speed_limit}mbit
tc filter add dev tun0 protocol ip parent 1:0 prio 1 u32 match ip src 10.8.0.0/24 flowid 1:1
'''
            script_path = f"/etc/openvpn/client-speed/{client_name}.sh"
            os.makedirs("/etc/openvpn/client-speed", exist_ok=True)
            
            with open(script_path, 'w') as f:
                f.write(script_content)
            
            os.chmod(script_path, 0o755)
            
        except Exception as e:
            logger.error(f"Ошибка настройки ограничения скорости: {e}")

    def revoke_client(self, client_name):
        try:
            subprocess.run([
                'cd', '/etc/openvpn/easy-rsa',
                '&&', 'echo', 'yes', '|', './easyrsa', '--batch', 'revoke', client_name
            ], check=True, capture_output=True, timeout=30)
            
            subprocess.run([
                'cd', '/etc/openvpn/easy-rsa',
                '&&', './easyrsa', '--batch', 'gen-crl'
            ], check=True, capture_output=True, timeout=30)
            
            subprocess.run(['systemctl', 'restart', 'openvpn@server'], check=True, timeout=30)
            
            config_path = os.path.join(OVPN_CLIENT_DIR, f'{client_name}.ovpn')
            if os.path.exists(config_path):
                os.remove(config_path)
                
            # Удаляем скрипт ограничения скорости
            speed_script = f"/etc/openvpn/client-speed/{client_name}.sh"
            if os.path.exists(speed_script):
                os.remove(speed_script)
                
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Ошибка отзыва ключа: {e}")
            return False

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
        self.application.add_handler(CommandHandler("settings", self.settings_panel))
        self.application.add_handler(CommandHandler("checkpayment", self.check_payment))
        self.application.add_handler(CommandHandler("trial", self.trial))
        self.application.add_handler(CommandHandler("referral", self.referral))
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user = update.effective_user
            logger.info(f"Команда /start от пользователя {user.id}")
            
            referred_by = None
            if context.args:
                referral_code = context.args[0]
                referred_by = self.db.get_user_by_referral_code(referral_code)
            
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
            
            message = f"Привет, {user.first_name}! 👋\n\n"
            message += "🤖 Добро пожаловать в Coffee Coma VPN!\n\n"
            
            if referral_code:
                bot_username = (await self.application.bot.get_me()).username
                referral_link = f"https://t.me/{bot_username}?start={referral_code}"
                message += f"📋 Ваш реферальный код: `{referral_code}`\n"
                message += f"🔗 Ваша ссылка: {referral_link}\n\n"
            
            message += "Выберите действие:"
            
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            logger.info(f"Главное меню показано для {user.id}")
            
        except Exception as e:
            logger.error(f"Ошибка в команде /start: {e}")
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

    async def buy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user = update.effective_user
            price = self.db.get_setting('price', 50)
            
            # Ссылка для СБП платежа
            sbp_url = f"https://yoomoney.ru/quickpay/confirm.xml?receiver={self.db.get_setting('yoomoney_wallet', '4100117852673007')}&quickpay-form=small&sum={price}&label=vpn_{user.id}&paymentType=AC"
            
            keyboard = [
                [InlineKeyboardButton(f"💳 Оплатить {price} руб (СБП)", url=sbp_url)],
                [InlineKeyboardButton("✅ Проверить оплату", callback_data='check_payment')],
                [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"💰 *Тарифы VPN*\n\n"
                f"• 1 месяц - {price} рублей\n"
                f"• Скорость: {self.db.get_setting('speed_limit', 10)} Мбит/с\n"
                f"• Безлимитный трафик\n\n"
                f"Для оплаты нажмите кнопку ниже:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Ошибка в команде /buy: {e}")
            await update.message.reply_text("❌ Ошибка при отображении тарифов.")

    async def check_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        price = self.db.get_setting('price', 50)
        label = f"vpn_{user_id}"
        
        # Проверяем платеж через ЮMoney API
        payment_received = yoomoney_api.check_payment(label, price)
        
        if payment_received:
            client_name = f"user_{user_id}_{int(datetime.now().timestamp())}"
            speed_limit = int(self.db.get_setting('speed_limit', 10))
            
            try:
                config_path = self.ovpn.create_client_config(client_name, speed_limit)
                self.db.add_subscription(user_id, client_name, config_path, 30, speed_limit)
                
                await update.message.reply_document(
                    document=open(config_path, 'rb'),
                    caption=f"✅ Оплата подтверждена! Ваш конфиг на 30 дней создан!\n⚡ Скорость: {speed_limit} Мбит/с"
                )
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка при создании конфига: {str(e)}")
        else:
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
            keyboard = [
                [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_document(
                document=open(config_path, 'rb'),
                caption="Ваш конфигурационный файл OpenVPN",
                reply_markup=reply_markup
            )
        else:
            keyboard = [
                [InlineKeyboardButton("🛒 Купить доступ", callback_data='buy')],
                [InlineKeyboardButton("🎁 Получить пробный период", callback_data='trial')],
                [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "У вас нет активной подписки.",
                reply_markup=reply_markup
            )

    async def trial(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if self.db.has_used_trial(user_id):
            keyboard = [
                [InlineKeyboardButton("🛒 Купить доступ", callback_data='buy')],
                [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "❌ Вы уже использовали бесплатный пробный период.",
                reply_markup=reply_markup
            )
            return
        
        try:
            client_name = f"trial_{user_id}_{int(datetime.now().timestamp())}"
            config_path = self.ovpn.create_client_config(client_name, TRIAL_SPEED_LIMIT)
            self.db.add_subscription(user_id, client_name, config_path, TRIAL_DAYS, TRIAL_SPEED_LIMIT, is_trial=True)
            
            keyboard = [
                [InlineKeyboardButton("📁 Скачать конфиг", callback_data='myconfig')],
                [InlineKeyboardButton("👥 Реферальная программа", callback_data='referral')],
                [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"✅ Вам предоставлен бесплатный пробный период на {TRIAL_DAYS} дней!\n\n"
                f"⚡ Скорость: {TRIAL_SPEED_LIMIT} Мбит/с\n"
                f"⏰ Срок действия: {TRIAL_DAYS} дней\n\n"
                f"Для продления доступа приобретите полную подписку.",
                reply_markup=reply_markup
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка при создании пробного доступа: {str(e)}")

    async def referral(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        # Получаем реферальный код пользователя
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
        
        message_text = "👥 *Реферальная программа*\n\n"
        message_text += f"📋 Ваш реферальный код: `{referral_code}`\n"
        message_text += f"🔗 Ваша ссылка: {referral_link}\n\n"
        message_text += f"📊 Статистика:\n"
        message_text += f"• Всего приглашено: {total_referrals}\n"
        message_text += f"• Доступно наград: {pending_rewards}\n\n"
        message_text += "🎁 За каждого приглашенного друга:\n"
        message_text += "• Ваш друг получает пробный период 5 дней\n"
        message_text += "• Вы получаете +5 дней к вашей подписке\n\n"
        
        keyboard = []
        if pending_rewards > 0:
            keyboard.append([InlineKeyboardButton("🎯 Забрать награду", callback_data='claim_reward')])
        
        keyboard.extend([
            [InlineKeyboardButton("📋 Поделиться ссылкой", url=f"https://t.me/share/url?url={referral_link}&text=Присоединяйся%20к%20VPN!")],
            [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')

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
            [InlineKeyboardButton("🔙 В главное меню", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text("👨‍💻 *Панель администратора*", reply_markup=reply_markup, parse_mode='Markdown')

    async def settings_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.db.is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен")
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
        
        message = "⚙️ *Текущие настройки сервера:*\n\n"
        message += f"🌐 *DNS серверы:* {dns1}, {dns2}\n"
        message += f"🔌 *Порт OpenVPN:* {port}\n"
        message += f"💰 *Цена подписки:* {price} руб\n"
        message += f"⚡ *Ограничение скорости:* {speed_limit} Мбит/с\n\n"
        message += "Выберите параметр для изменения:"
        
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

    async def manage_keys(self, query):
        user_id = query.from_user.id
        if not self.db.is_admin(user_id):
            await query.message.reply_text("❌ Доступ запрещен")
            return
        
        subscriptions = self.db.get_all_subscriptions()
        
        if not subscriptions:
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='admin_back')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("❌ Нет активных подписок", reply_markup=reply_markup)
            return
        
        keyboard = []
        for user_id, client_name, config_path, end_date, speed_limit, first_name in subscriptions:
            keyboard.append([InlineKeyboardButton(
                f"🗑️ {client_name} ({first_name}) - {speed_limit}Мбит/с до {end_date[:10]}", 
                callback_data=f'revoke_{client_name}'
            )])
        
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_back')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_text("🗑️ Выберите ключ для удаления:", reply_markup=reply_markup)

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
        elif data == 'admin_settings':
            await self.settings_panel_callback(query)
        elif data == 'admin_keys':
            await self.manage_keys(query)
        elif data == 'admin_free':
            await self.create_free_config(query)
        elif data == 'admin_stats':
            await self.show_stats(query)
        elif data == 'admin_back':
            await self.admin_panel_callback(query)
        elif data == 'main_menu':
            await self.show_main_menu(query)
        elif data == 'trial':
            await self.trial_callback(query)
        elif data == 'referral':
            await self.referral_callback(query)
        elif data == 'check_payment':
            await self.check_payment_callback(query)
        elif data == 'claim_reward':
            await self.claim_reward_callback(query)
        elif data == 'change_dns':
            context.user_data['awaiting_input'] = 'dns'
            await query.message.reply_text("Введите новые DNS серверы через пробел (например: 1.1.1.1 1.0.0.1):")
        elif data == 'change_port':
            context.user_data['awaiting_input'] = 'port'
            await query.message.reply_text("Введите новый порт для OpenVPN (например: 443):")
        elif data == 'change_price':
            context.user_data['awaiting_input'] = 'price'
            await query.message.reply_text("Введите новую цену подписки в рублях (например: 100):")
        elif data == 'change_speed':
            context.user_data['awaiting_input'] = 'speed'
            await query.message.reply_text("Введите новое ограничение скорости в Мбит/с (например: 20):")
        elif data.startswith('revoke_'):
            client_name = data.replace('revoke_', '')
            success = self.ovpn.revoke_client(client_name)
            if success:
                self.db.delete_subscription(client_name)
                keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='admin_back')]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text(f"✅ Ключ {client_name} отозван и удален!", reply_markup=reply_markup)
            else:
                keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='admin_back')]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text(f"❌ Ошибка при отзыве ключа {client_name}", reply_markup=reply_markup)

    async def show_main_menu(self, query):
        user = query.from_user
        referral_code = self.db.add_user(user.id, user.first_name, user.username)
        
        keyboard = [
            [InlineKeyboardButton("🛒 Купить доступ", callback_data='buy')],
            [InlineKeyboardButton("📁 Мой конфиг", callback_data='myconfig')],
            [InlineKeyboardButton("🎁 Бесплатный пробный период", callback_data='trial')],
            [InlineKeyboardButton("👥 Реферальная программа", callback_data='referral')]
        ]
        
        if self.db.is_admin(user.id):
            keyboard.append([InlineKeyboardButton("👨‍💻 Админ панель", callback_data='admin_panel')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = "🤖 *Главное меню*\n\nВыберите действие:"
        
        await query.message.edit_text(message, reply_markup=reply_markup, parse_mode='Markdown')

    async def buy_callback(self, query):
        user = query.from_user
        price = self.db.get_setting('price', 50)
        
        sbp_url = f"https://yoomoney.ru/quickpay/confirm.xml?receiver={self.db.get_setting('yoomoney_wallet', '4100117852673007')}&quickpay-form=small&sum={price}&label=vpn_{user.id}&paymentType=AC"
        
        keyboard = [
            [InlineKeyboardButton(f"💳 Оплатить {price} руб (СБП)", url=sbp_url)],
            [InlineKeyboardButton("✅ Проверить оплату", callback_data='check_payment')],
            [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(
            f"💰 *Тарифы VPN*\n\n"
            f"• 1 месяц - {price} рублей\n"
            f"• Скорость: {self.db.get_setting('speed_limit', 10)} Мбит/с\n"
            f"• Безлимитный трафик\n\n"
            f"Для оплаты нажмите кнопку ниже:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    async def my_config_callback(self, query):
        user_id = query.from_user.id
        config_path = self.db.get_user_config(user_id)
        
        if config_path and os.path.exists(config_path):
            keyboard = [
                [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.message.reply_document(
                document=open(config_path, 'rb'),
                caption="Ваш конфигурационный файл OpenVPN",
                reply_markup=reply_markup
            )
        else:
            keyboard = [
                [InlineKeyboardButton("🛒 Купить доступ", callback_data='buy')],
                [InlineKeyboardButton("🎁 Получить пробный период", callback_data='trial')],
                [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.message.edit_text(
                "У вас нет активной подписки.",
                reply_markup=reply_markup
            )

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
            [InlineKeyboardButton("🔙 В главное меню", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text("👨‍💻 *Панель администратора*", reply_markup=reply_markup, parse_mode='Markdown')

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
        
        message = "⚙️ *Текущие настройки сервера:*\n\n"
        message += f"🌐 *DNS серверы:* {dns1}, {dns2}\n"
        message += f"🔌 *Порт OpenVPN:* {port}\n"
        message += f"💰 *Цена подписки:* {price} руб\n"
        message += f"⚡ *Ограничение скорости:* {speed_limit} Мбит/с\n\n"
        message += "Выберите параметр для изменения:"
        
        await query.message.edit_text(message, reply_markup=reply_markup, parse_mode='Markdown')

    async def check_payment_callback(self, query):
        user_id = query.from_user.id
        price = self.db.get_setting('price', 50)
        label = f"vpn_{user_id}"
        
        payment_received = yoomoney_api.check_payment(label, price)
        
        if payment_received:
            client_name = f"user_{user_id}_{int(datetime.now().timestamp())}"
            speed_limit = int(self.db.get_setting('speed_limit', 10))
            
            try:
                config_path = self.ovpn.create_client_config(client_name, speed_limit)
                self.db.add_subscription(user_id, client_name, config_path, 30, speed_limit)
                
                await query.message.reply_document(
                    document=open(config_path, 'rb'),
                    caption=f"✅ Оплата подтверждена! Ваш конфиг на 30 дней создан!\n⚡ Скорость: {speed_limit} Мбит/с"
                )
            except Exception as e:
                await query.message.edit_text(f"❌ Ошибка при создании конфига: {str(e)}")
        else:
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data='check_payment')],
                [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.message.edit_text(
                "❌ Оплата не найдена. Пожалуйста, подождите несколько минут или проверьте правильность оплаты.",
                reply_markup=reply_markup
            )

    async def trial_callback(self, query):
        user_id = query.from_user.id
        
        if self.db.has_used_trial(user_id):
            keyboard = [
                [InlineKeyboardButton("🛒 Купить доступ", callback_data='buy')],
                [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.message.edit_text(
                "❌ Вы уже использовали бесплатный пробный период.",
                reply_markup=reply_markup
            )
            return
        
        try:
            client_name = f"trial_{user_id}_{int(datetime.now().timestamp())}"
            config_path = self.ovpn.create_client_config(client_name, TRIAL_SPEED_LIMIT)
            self.db.add_subscription(user_id, client_name, config_path, TRIAL_DAYS, TRIAL_SPEED_LIMIT, is_trial=True)
            
            keyboard = [
                [InlineKeyboardButton("📁 Скачать конфиг", callback_data='myconfig')],
                [InlineKeyboardButton("👥 Реферальная программа", callback_data='referral')],
                [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.message.edit_text(
                f"✅ Вам предоставлен бесплатный пробный период на {TRIAL_DAYS} дней!\n\n"
                f"⚡ Скорость: {TRIAL_SPEED_LIMIT} Мбит/с\n"
                f"⏰ Срок действия: {TRIAL_DAYS} дней\n\n"
                f"Для продления доступа приобретите полную подписку.",
                reply_markup=reply_markup
            )
            
        except Exception as e:
            await query.message.edit_text(f"❌ Ошибка при создании пробного доступа: {str(e)}")

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
        
        message_text = "👥 *Реферальная программа*\n\n"
        message_text += f"📋 Ваш реферальный код: `{referral_code}`\n"
        message_text += f"🔗 Ваша ссылка: {referral_link}\n\n"
        message_text += f"📊 Статистика:\n"
        message_text += f"• Всего приглашено: {total_referrals}\n"
        message_text += f"• Доступно наград: {pending_rewards}\n\n"
        message_text += "🎁 За каждого приглашенного друга:\n"
        message_text += "• Ваш друг получает пробный период 5 дней\n"
        message_text += "• Вы получаете +5 дней к вашей подписке\n\n"
        
        keyboard = []
        if pending_rewards > 0:
            keyboard.append([InlineKeyboardButton("🎯 Забрать награду", callback_data='claim_reward')])
        
        keyboard.extend([
            [InlineKeyboardButton("📋 Поделиться ссылкой", url=f"https://t.me/share/url?url={referral_link}&text=Присоединяйся%20к%20VPN!")],
            [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')

    async def claim_reward_callback(self, query):
        user_id = query.from_user.id
        rewards_claimed = self.db.claim_referral_reward(user_id)
        
        if rewards_claimed > 0:
            # Продлеваем подписку на 5 дней за каждого реферала
            cursor = self.db.conn.cursor()
            cursor.execute('SELECT client_name, end_date FROM subscriptions WHERE user_id = ? ORDER BY end_date DESC LIMIT 1', (user_id,))
            subscription = cursor.fetchone()
            
            if subscription:
                client_name, end_date = subscription
                new_end_date = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S') + timedelta(days=REFERRAL_REWARD_DAYS * rewards_claimed)
                cursor.execute('UPDATE subscriptions SET end_date = ? WHERE client_name = ?', (new_end_date.strftime('%Y-%m-%d %H:%M:%S'), client_name))
                self.db.conn.commit()
                
                await query.message.edit_text(
                    f"🎉 Поздравляем! Вы получили {rewards_claimed * REFERRAL_REWARD_DAYS} дней к вашей подписке!\n"
                    f"📅 Новая дата окончания: {new_end_date.strftime('%d.%m.%Y')}"
                )
            else:
                # Создаем новую подписку если нет активной
                client_name = f"user_{user_id}_{int(datetime.now().timestamp())}"
                try:
                    speed_limit = int(self.db.get_setting('speed_limit', 10))
                    config_path = self.ovpn.create_client_config(client_name, speed_limit)
                    self.db.add_subscription(user_id, client_name, config_path, REFERRAL_REWARD_DAYS * rewards_claimed, speed_limit)
                    
                    await query.message.reply_document(
                        document=open(config_path, 'rb'),
                        caption=f"🎉 Поздравляем! Вы получили {rewards_claimed * REFERRAL_REWARD_DAYS} дней доступа к VPN!"
                    )
                except Exception as e:
                    await query.message.edit_text(f"❌ Ошибка при создании конфига: {str(e)}")
        else:
            await query.message.edit_text("❌ Нет доступных наград для получения.")

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
                caption=f"✅ Ваш бесплатный конфиг на 7 дней создан!\n⚡ Скорость: {speed_limit} Мбит/с"
            )
        except Exception as e:
            await query.message.edit_text(f"❌ Ошибка при создании конфига: {str(e)}")

    async def show_stats(self, query):
        user_id = query.from_user.id
        if not self.db.is_admin(user_id):
            await query.message.edit_text("❌ Доступ запрещен")
            return
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM users')
        users_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM subscriptions WHERE end_date > datetime("now")')
        active_subs = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM referrals')
        referrals_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT SUM(speed_limit) FROM subscriptions WHERE end_date > datetime("now")')
        total_speed = cursor.fetchone()[0] or 0
        
        conn.close()
        
        message = f"📊 *Статистика системы:*\n\n"
        message += f"👥 Всего пользователей: {users_count}\n"
        message += f"🔗 Активных подписок: {active_subs}\n"
        message += f"👥 Рефералов: {referrals_count}\n"
        message += f"⚡ Общая скорость: {total_speed} Мбит/с\n\n"
        message += f"🌐 DNS: {self.db.get_setting('dns1', '8.8.8.8')}, {self.db.get_setting('dns2', '8.8.4.4')}\n"
        message += f"🔌 Порт: {self.db.get_setting('port', '1194')}\n"
        message += f"💰 Цена: {self.db.get_setting('price', '50')} руб\n"
        message += f"⚡ Скорость: {self.db.get_setting('speed_limit', '10')} Мбит/с"
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='admin_back')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(message, reply_markup=reply_markup, parse_mode='Markdown')

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = update.message.text
        
        if not self.db.is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен")
            return
        
        if 'awaiting_input' not in context.user_data:
            return
        
        input_type = context.user_data['awaiting_input']
        
        try:
            if input_type == 'dns':
                dns_servers = text.split()
                if len(dns_servers) != 2:
                    await update.message.reply_text("❌ Неверный формат. Введите 2 DNS сервера через пробел.")
                    return
                
                ip_pattern = r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$'
                if not re.match(ip_pattern, dns_servers[0]) or not re.match(ip_pattern, dns_servers[1]):
                    await update.message.reply_text("❌ Неверный формат IP адресов.")
                    return
                
                self.db.update_setting('dns1', dns_servers[0])
                self.db.update_setting('dns2', dns_servers[1])
                await update.message.reply_text(f"✅ DNS серверы изменены: {dns_servers[0]}, {dns_servers[1]}")
                
            elif input_type == 'port':
                if not text.isdigit() or not (1 <= int(text) <= 65535):
                    await update.message.reply_text("❌ Неверный порт. Должен быть число от 1 до 65535.")
                    return
                
                self.db.update_setting('port', text)
                await update.message.reply_text(f"✅ Порт изменен: {text}")
                
            elif input_type == 'price':
                if not text.isdigit() or int(text) <= 0:
                    await update.message.reply_text("❌ Неверная цена. Должно быть положительное число.")
                    return
                
                self.db.update_setting('price', text)
                await update.message.reply_text(f"✅ Цена изменена: {text} руб")
                
            elif input_type == 'speed':
                if not text.isdigit() or not (1 <= int(text) <= 1000):
                    await update.message.reply_text("❌ Неверная скорость. Должно быть число от 1 до 1000.")
                    return
                
                self.db.update_setting('speed_limit', text)
                await update.message.reply_text(f"✅ Ограничение скорости изменено: {text} Мбит/с")
            
            del context.user_data['awaiting_input']
            await self.settings_panel(update, context)
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
            del context.user_data['awaiting_input']

    def run(self):
        self.application.run_polling()

if __name__ == "__main__":
    bot = VPNBot()
    bot.run()
