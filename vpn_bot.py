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
from yoomoney import Quickpay, Client
import asyncio

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = "7953514140:AAGg-AgyL6Y2mvzfyKesnpouJkU6p_B8Zeo"
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

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.create_tables()
        self.clean_expired_subscriptions()

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
        default_settings = [
            ("dns1", "8.8.8.8"),
            ("dns2", "8.8.4.4"),
            ("port", "1194"),
            ("price", "50"),
            ("speed_limit", "10"),
            ("yoomoney_wallet", "4100117852673007"),
            ("yoomoney_token", "")
        ]
        
        for key, value in default_settings:
            cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))
        
        self.conn.commit()
        logger.info("Таблицы базы данных созданы")

    def clean_expired_subscriptions(self):
        """Удаляет просроченные подписки"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM subscriptions WHERE end_date < datetime("now")')
            deleted = cursor.rowcount
            if deleted > 0:
                logger.info(f"Удалено {deleted} просроченных подписок")
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
                INSERT INTO subscriptions 
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
            WHERE user_id = ? AND end_date > datetime("now")
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
            WHERE s.end_date > datetime("now")
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

class OpenVPNManager:
    def create_client_config(self, client_name, speed_limit=10):
        try:
            # Создаем запрос сертификата
            subprocess.run([
                '/bin/bash', '-c', 
                f'cd /etc/openvpn/easy-rsa && ./easyrsa --batch gen-req {client_name} nopass'
            ], check=True, capture_output=True, timeout=60)
            
            # Подписываем сертификат
            subprocess.run([
                '/bin/bash', '-c', 
                f'cd /etc/openvpn/easy-rsa && echo "yes" | ./easyrsa --batch sign-req client {client_name}'
            ], check=True, capture_output=True, timeout=60)
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"Ошибка создания сертификата: {e.stderr.decode()}")

        # Получаем IP сервера
        try:
            server_ip = subprocess.check_output("curl -s ifconfig.me", shell=True, timeout=10).decode().strip()
        except:
            server_ip = "77.239.105.17"

        # Читаем файлы сертификатов
        try:
            with open(f"{OVPN_KEYS_DIR}ca.crt", 'r') as f:
                ca_cert = f.read()
            with open(f"{OVPN_KEYS_DIR}issued/{client_name}.crt", 'r') as f:
                client_cert = f.read()
            with open(f"{OVPN_KEYS_DIR}private/{client_name}.key", 'r') as f:
                client_key = f.read()
            with open(f"{OVPN_KEYS_DIR}ta.key", 'r') as f:
                ta_key = f.read()
        except Exception as e:
            raise Exception(f"Ошибка чтения файлов: {str(e)}")

        # Получаем настройки из базы
        dns1 = self.db.get_setting('dns1', '8.8.8.8')
        dns2 = self.db.get_setting('dns2', '8.8.4.4')
        port = self.db.get_setting('port', '1194')

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
auth SHA256
verb 3
redirect-gateway def1
dhcp-option DNS {dns1}
dhcp-option DNS {dns2}
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
        try:
            with open(config_path, 'w') as f:
                f.write(config_content)
        except Exception as e:
            raise Exception(f"Ошибка записи конфига: {str(e)}")
        
        return config_path

    def revoke_client(self, client_name):
        try:
            result = subprocess.run([
                '/bin/bash', '-c', 
                f'cd /etc/openvpn/easy-rsa && echo "yes" | ./easyrsa --batch revoke {client_name}'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                return False
            
            result = subprocess.run([
                '/bin/bash', '-c', 
                f'cd /etc/openvpn/easy-rsa && ./easyrsa --batch gen-crl'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                return False
            
            # Перезапускаем OpenVPN
            subprocess.run(['systemctl', 'restart', 'openvpn@server'], timeout=30)
            
            # Удаляем конфиг файл
            config_path = f"{OVPN_CLIENT_DIR}{client_name}.ovpn"
            if os.path.exists(config_path):
                os.remove(config_path)
                
            return True
            
        except:
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
        self.application.add_handler(CommandHandler("trial", self.trial))
        self.application.add_handler(CommandHandler("referral", self.referral))
        self.application.add_handler(CommandHandler("checkpayment", self.check_payment))
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

    async def create_payment(self, user_id, amount):
        """Создает платеж в ЮMoney"""
        try:
            label = f"vpn_{user_id}_{int(datetime.now().timestamp())}"
            quickpay = Quickpay(
                receiver=self.db.get_setting('yoomoney_wallet'),
                quickpay_form="shop",
                targets="Оплата VPN доступа",
                paymentType="SB",
                sum=amount,
                label=label
            )
            return quickpay.redirected_url, label
        except Exception as e:
            logger.error(f"Ошибка создания платежа: {e}")
            return None, None

    async def check_yoomoney_payment(self, label):
        """Проверяет оплату через ЮMoney"""
        try:
            token = self.db.get_setting('yoomoney_token')
            if not token:
                return False
                
            client = Client(token)
            history = client.operation_history(label=label)
            
            for operation in history.operations:
                if operation.status == 'success':
                    return True
            return False
        except Exception as e:
            logger.error(f"Ошибка проверки платежа: {e}")
            return False

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user = update.effective_user
            logger.info(f"Команда /start от пользователя {user.id}")
            
            referred_by = None
            if context.args:
                referral_code = context.args[0]
                referred_by = self.db.get_user_by_referral_code(referral_code)
            
            referral_code = self.db.add_user(user.id, user.first_name, user.username, referred_by)
            
            await self.show_main_menu(update.message, user, referral_code)
            
        except Exception as e:
            logger.error(f"Ошибка в команде /start: {e}")
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

    async def show_main_menu(self, message, user, referral_code=None):
        keyboard = [
            [InlineKeyboardButton("🛒 Купить доступ", callback_data='buy')],
            [InlineKeyboardButton("📁 Мой конфиг", callback_data='myconfig')],
            [InlineKeyboardButton("🎁 Бесплатный пробный период", callback_data='trial')],
            [InlineKeyboardButton("👥 Реферальная программа", callback_data='referral')]
        ]
        
        if self.db.is_admin(user.id):
            keyboard.append([InlineKeyboardButton("👨‍💻 Админ панель", callback_data='admin_panel')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = f"Привет, {user.first_name}! 👋\n\n"
        message_text += "🤖 Добро пожаловать в Coffee Coma VPN!\n\n"
        
        if referral_code:
            bot_username = (await self.application.bot.get_me()).username
            referral_link = f"https://t.me/{bot_username}?start={referral_code}"
            message_text += f"📋 Ваш реферальный код: `{referral_code}`\n"
            message_text += f"🔗 Ваша ссылка: {referral_link}\n\n"
        
        message_text += "Выберите действие:"
        
        await message.reply_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')

    async def buy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user = update.effective_user
            price = int(self.db.get_setting('price', 50))
            
            # Создаем платеж
            payment_url, payment_label = await self.create_payment(user.id, price)
            
            if not payment_url:
                await update.message.reply_text("❌ Ошибка при создании платежа")
                return
            
            # Сохраняем информацию о платеже
            context.user_data['payment_label'] = payment_label
            context.user_data['payment_user_id'] = user.id
            
            keyboard = [
                [InlineKeyboardButton("💳 Перейти к оплате", url=payment_url)],
                [InlineKeyboardButton("✅ Проверить оплату", callback_data='check_payment')],
                [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"💰 *Оплата VPN доступа*\n\n"
                f"Сумма: {price} руб.\n"
                f"Способ оплаты: СБП/Карта\n\n"
                f"1. Нажмите 'Перейти к оплате'\n"
                f"2. Оплатите счет\n"
                f"3. Вернитесь в бот и нажмите 'Проверить оплату'",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Ошибка в команде /buy: {e}")
            await update.message.reply_text("❌ Ошибка при создании платежа.")

    async def check_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            payment_label = context.user_data.get('payment_label')
            
            if not payment_label:
                await update.message.reply_text("❌ Информация о платеже не найдена")
                return
                
            # Проверяем оплату
            payment_success = await self.check_yoomoney_payment(payment_label)
            
            if payment_success:
                # Создаем конфиг
                client_name = f"client_{user_id}_{int(datetime.now().timestamp())}"
                speed_limit = int(self.db.get_setting('speed_limit', 10))
                
                config_path = self.ovpn.create_client_config(client_name, speed_limit)
                self.db.add_subscription(user_id, client_name, config_path, 30, speed_limit)
                
                # Отправляем конфиг
                await update.message.reply_document(
                    document=open(config_path, 'rb'),
                    caption="✅ Оплата прошла успешно! Ваш конфигурационный файл готов.\nСрок действия: 30 дней"
                )
                
                # Начисляем реферальную награду если есть
                cursor = self.db.conn.cursor()
                cursor.execute('SELECT referred_by FROM users WHERE user_id = ?', (user_id,))
                referrer = cursor.fetchone()
                
                if referrer and referrer[0]:
                    # Добавляем дни рефереру
                    referrer_id = referrer[0]
                    cursor.execute('''
                        UPDATE subscriptions 
                        SET end_date = datetime(end_date, '+5 days') 
                        WHERE user_id = ? AND end_date > datetime('now')
                    ''', (referrer_id,))
                    self.db.conn.commit()
                    
                    # Помечаем награду как полученную
                    cursor.execute('''
                        UPDATE referrals 
                        SET reward_claimed = 1 
                        WHERE referrer_id = ? AND referred_id = ?
                    ''', (referrer_id, user_id))
                    self.db.conn.commit()
                    
                    try:
                        await self.application.bot.send_message(
                            referrer_id,
                            "🎉 Вам начислено +5 дней за реферала!"
                        )
                    except:
                        pass
            else:
                keyboard = [
                    [InlineKeyboardButton("🔄 Попробовать снова", callback_data='check_payment')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "❌ Оплата не найдена. Попробуйте проверить позже или используйте пробный период.",
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Ошибка проверки платежа: {e}")
            await update.message.reply_text("❌ Ошибка при проверке платежа")

    async def my_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            config_path = self.db.get_user_config(user_id)
            
            if config_path and os.path.exists(config_path):
                await update.message.reply_document(
                    document=open(config_path, 'rb'),
                    caption="✅ Ваш конфигурационный файл OpenVPN"
                )
            else:
                await update.message.reply_text("❌ У вас нет активной подписки.")
                
        except Exception as e:
            logger.error(f"Ошибка в my_config: {e}")
            await update.message.reply_text("❌ Ошибка при получении конфига.")

    async def trial(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            
            if self.db.has_used_trial(user_id):
                await update.message.reply_text("❌ Вы уже использовали бесплатный пробный период.")
                return
            
            client_name = f"trial_{user_id}_{int(datetime.now().timestamp())}"
            config_path = self.ovpn.create_client_config(client_name, TRIAL_SPEED_LIMIT)
            self.db.add_subscription(user_id, client_name, config_path, TRIAL_DAYS, TRIAL_SPEED_LIMIT, is_trial=True)
            
            await update.message.reply_document(
                document=open(config_path, 'rb'),
                caption=f"✅ Вам предоставлен бесплатный пробный период на {TRIAL_DAYS} дней!\n⚡ Скорость: {TRIAL_SPEED_LIMIT} Мбит/с"
            )
            
        except Exception as e:
            logger.error(f"Ошибка в trial: {e}")
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")

    async def referral(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            
            cursor = self.db.conn.cursor()
            cursor.execute('SELECT referral_code FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            
            if not result:
                await update.message.reply_text("❌ Реферальный код не найден")
                return
            
            referral_code = result[0]
            bot_username = (await self.application.bot.get_me()).username
            referral_link = f"https://t.me/{bot_username}?start={referral_code}"
            
            pending_rewards, total_referrals = self.db.get_referral_stats(user_id)
            
            message = f"👥 *Реферальная программа*\n\n"
            message += f"📋 Ваш реферальный код: `{referral_code}`\n"
            message += f"🔗 Ваша ссылка: {referral_link}\n\n"
            message += f"📊 Статистика:\n"
            message += f"• Всего приглашено: {total_referrals}\n"
            message += f"• Доступно наград: {pending_rewards}\n\n"
            message += "🎁 За каждого приглашенного друга:\n"
            message += "• Ваш друг получает пробный период 5 дней\n"
            message += "• Вы получаете +5 дней к вашей подписке"
            
            keyboard = []
            if pending_rewards > 0:
                keyboard.append([InlineKeyboardButton("🎯 Забрать награду", callback_data='claim_reward')])
            
            keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='main_menu')])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Ошибка в referral: {e}")
            await update.message.reply_text("❌ Ошибка при получении реферальной информации.")

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
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
            
        except Exception as e:
            logger.error(f"Ошибка в admin_panel: {e}")
            await update.message.reply_text("❌ Ошибка при открытии админ-панели.")

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            
            data = query.data
            logger.info(f"Обработка callback: {data}")
            
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
            elif data == 'claim_reward':
                await self.claim_reward_callback(query)
            elif data == 'main_menu':
                await self.show_main_menu(query)
            elif data.startswith('revoke_'):
                client_name = data.replace('revoke_', '')
                await self.revoke_client_callback(query, client_name)
            elif data == 'admin_back':
                await self.admin_panel_callback(query)
            elif data in ['change_dns', 'change_port', 'change_price', 'change_speed', 'change_yoomoney_wallet', 'change_yoomoney_token']:
                context.user_data['awaiting_input'] = data
                await self.handle_settings_input(query, data)
                
        except Exception as e:
            logger.error(f"Ошибка в button_handler: {e}")
            try:
                await query.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")
            except:
                pass

    async def buy_callback(self, query):
        user = query.from_user
        price = int(self.db.get_setting('price', 50))
        
        # Создаем платеж
        payment_url, payment_label = await self.create_payment(user.id, price)
        
        if not payment_url:
            await query.message.edit_text("❌ Ошибка при создании платежа")
            return
        
        # Сохраняем информацию о платеже
        context.user_data['payment_label'] = payment_label
        context.user_data['payment_user_id'] = user.id
        
        keyboard = [
            [InlineKeyboardButton("💳 Перейти к оплате", url=payment_url)],
            [InlineKeyboardButton("✅ Проверить оплату", callback_data='check_payment')],
            [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(
            f"💰 *Оплата VPN доступа*\n\n"
            f"Сумма: {price} руб.\n"
            f"Способ оплаты: СБП/Карта\n\n"
            f"1. Нажмите 'Перейти к оплате'\n"
            f"2. Оплатите счет\n"
            f"3. Вернитесь в бот и нажмите 'Проверить оплату'",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    async def my_config_callback(self, query):
        user_id = query.from_user.id
        config_path = self.db.get_user_config(user_id)
        
        if config_path and os.path.exists(config_path):
            await query.message.reply_document(
                document=open(config_path, 'rb'),
                caption="✅ Ваш конфигурационный файл OpenVPN"
            )
        else:
            await query.message.edit_text("❌ У вас нет активной подписки.")

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
                caption=f"✅ Вам предоставлен бесплатный пробный период на {TRIAL_DAYS} дней!\n⚡ Скорость: {TRIAL_SPEED_LIMIT} Мбит/с"
            )
            
        except Exception as e:
            await query.message.edit_text(f"❌ Ошибка: {str(e)}")

    async def referral_callback(self, query):
        user_id = query.from_user.id
        
        cursor = self.db.conn.cursor()
        cursor.execute('SELECT referral_code FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        
        if not result:
            await query.message.edit_text("❌ Реферальный код не найден")
            return
        
        referral_code = result[0]
        bot_username = (await self.application.bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start={referral_code}"
        
        pending_rewards, total_referrals = self.db.get_referral_stats(user_id)
        
        message = f"👥 *Реферальная программа*\n\n"
        message += f"📋 Ваш реферальный код: `{referral_code}`\n"
        message += f"🔗 Ваша ссылка: {referral_link}\n\n"
        message += f"📊 Статистика:\n"
        message += f"• Всего приглашено: {total_referrals}\n"
        message += f"• Доступно наград: {pending_rewards}\n\n"
        message += "🎁 За каждого приглашенного друга:\n"
        message += "• Ваш друг получает пробный период 5 дней\n"
        message += "• Вы получаете +5 дней к вашей подписке"
        
        keyboard = []
        if pending_rewards > 0:
            keyboard.append([InlineKeyboardButton("🎯 Забрать награду", callback_data='claim_reward')])
        
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='main_menu')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(message, reply_markup=reply_markup, parse_mode='Markdown')

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
        yoomoney_wallet = self.db.get_setting('yoomoney_wallet', '')
        yoomoney_token = self.db.get_setting('yoomoney_token', '')
        
        keyboard = [
            [InlineKeyboardButton(f"🌐 DNS: {dns1} {dns2}", callback_data='change_dns')],
            [InlineKeyboardButton(f"🔌 Порт: {port}", callback_data='change_port')],
            [InlineKeyboardButton(f"💰 Цена: {price} руб", callback_data='change_price')],
            [InlineKeyboardButton(f"⚡ Скорость: {speed_limit} Мбит/с", callback_data='change_speed')],
            [InlineKeyboardButton(f"💳 ЮMoney Кошелек: {yoomoney_wallet}", callback_data='change_yoomoney_wallet')],
            [InlineKeyboardButton(f"🔑 ЮMoney Токен: {'установлен' if yoomoney_token else 'не установлен'}", callback_data='change_yoomoney_token')],
            [InlineKeyboardButton("🔙 Назад", callback_data='admin_back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = "⚙️ *Текущие настройки сервера:*\n\n"
        message += f"🌐 *DNS серверы:* {dns1}, {dns2}\n"
        message += f"🔌 *Порт OpenVPN:* {port}\n"
        message += f"💰 *Цена подписки:* {price} руб\n"
        message += f"⚡ *Ограничение скорости:* {speed_limit} Мбит/с\n"
        message += f"💳 *ЮMoney Кошелек:* {yoomoney_wallet}\n"
        message += f"🔑 *ЮMoney Токен:* {'установлен' if yoomoney_token else 'не установлен'}\n\n"
        message += "Выберите параметр для изменения:"
        
        await query.message.edit_text(message, reply_markup=reply_markup, parse_mode='Markdown')

    async def handle_settings_input(self, query, input_type):
        messages = {
            'change_dns': "Введите новые DNS серверы через пробел (например: 1.1.1.1 1.0.0.1):",
            'change_port': "Введите новый порт для OpenVPN (например: 443):",
            'change_price': "Введите новую цену подписки в рублях (например: 100):",
            'change_speed': "Введите новое ограничение скорости в Мбит/с (например: 20):",
            'change_yoomoney_wallet': "Введите номер кошелька ЮMoney:",
            'change_yoomoney_token': "Введите токен доступа ЮMoney:"
        }
        
        await query.message.reply_text(messages.get(input_type, "Введите новое значение:"))

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

    async def revoke_client_callback(self, query, client_name):
        success = self.ovpn.revoke_client(client_name)
        if success:
            self.db.delete_subscription(client_name)
            await query.message.reply_text(f"✅ Ключ {client_name} отозван и удален!")
        else:
            await query.message.reply_text(f"❌ Ошибка при отзыве ключа {client_name}")

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
        
        cursor = self.db.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users')
        users_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM subscriptions WHERE end_date > datetime("now")')
        active_subs = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM referrals')
        referrals_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT SUM(speed_limit) FROM subscriptions WHERE end_date > datetime("now")')
        total_speed = cursor.fetchone()[0] or 0
        
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

    async def check_payment_callback(self, query):
        try:
            user_id = query.from_user.id
            payment_label = context.user_data.get('payment_label')
            
            if not payment_label:
                await query.message.edit_text("❌ Информация о платеже не найдена")
                return
                
            # Проверяем оплату
            payment_success = await self.check_yoomoney_payment(payment_label)
            
            if payment_success:
                # Создаем конфиг
                client_name = f"client_{user_id}_{int(datetime.now().timestamp())}"
                speed_limit = int(self.db.get_setting('speed_limit', 10))
                
                config_path = self.ovpn.create_client_config(client_name, speed_limit)
                self.db.add_subscription(user_id, client_name, config_path, 30, speed_limit)
                
                # Отправляем конфиг
                await query.message.reply_document(
                    document=open(config_path, 'rb'),
                    caption="✅ Оплата прошла успешно! Ваш конфигурационный файл готов.\nСрок действия: 30 дней"
                )
                
                # Начисляем реферальную награду если есть
                cursor = self.db.conn.cursor()
                cursor.execute('SELECT referred_by FROM users WHERE user_id = ?', (user_id,))
                referrer = cursor.fetchone()
                
                if referrer and referrer[0]:
                    # Добавляем дни рефереру
                    referrer_id = referrer[0]
                    cursor.execute('''
                        UPDATE subscriptions 
                        SET end_date = datetime(end_date, '+5 days') 
                        WHERE user_id = ? AND end_date > datetime('now')
                    ''', (referrer_id,))
                    self.db.conn.commit()
                    
                    # Помечаем награду как полученную
                    cursor.execute('''
                        UPDATE referrals 
                        SET reward_claimed = 1 
                        WHERE referrer_id = ? AND referred_id = ?
                    ''', (referrer_id, user_id))
                    self.db.conn.commit()
                    
                    try:
                        await self.application.bot.send_message(
                            referrer_id,
                            "🎉 Вам начислено +5 дней за реферала!"
                        )
                    except:
                        pass
            else:
                keyboard = [
                    [InlineKeyboardButton("🔄 Попробовать снова", callback_data='check_payment')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.message.edit_text(
                    "❌ Оплата не найдена. Попробуйте проверить позже или используйте пробный период.",
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Ошибка проверки платежа: {e}")
            await query.message.edit_text("❌ Ошибка при проверке платежа")

    async def claim_reward_callback(self, query):
        user_id = query.from_user.id
        
        # Получаем активную подписку пользователя
        cursor = self.db.conn.cursor()
        cursor.execute('''
            SELECT client_name FROM subscriptions 
            WHERE user_id = ? AND end_date > datetime("now")
        ''', (user_id,))
        active_sub = cursor.fetchone()
        
        if not active_sub:
            await query.message.edit_text("❌ У вас нет активной подписки для получения награды")
            return
            
        # Начисляем награду
        rewards_claimed = self.db.claim_referral_reward(user_id)
        
        if rewards_claimed > 0:
            # Добавляем дни к текущей подписке
            cursor.execute('''
                UPDATE subscriptions 
                SET end_date = datetime(end_date, '+5 days') 
                WHERE user_id = ? AND end_date > datetime("now")
            ''', (user_id,))
            self.db.conn.commit()
            
            await query.message.edit_text(f"🎉 Вы получили {rewards_claimed * 5} дней к вашей подписке!")
        else:
            await query.message.edit_text("❌ Нет доступных наград для получения.")

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
        
        await query.message.edit_text(
            "🤖 *Главное меню*\n\nВыберите действие:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

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
            if input_type == 'change_dns':
                dns_servers = text.split()
                if len(dns_servers) != 2:
                    await update.message.reply_text("❌ Неверный формат. Введите 2 DNS сервера через пробел.")
                    return
                
                self.db.update_setting('dns1', dns_servers[0])
                self.db.update_setting('dns2', dns_servers[1])
                await update.message.reply_text(f"✅ DNS серверы изменены: {dns_servers[0]}, {dns_servers[1]}")
                
            elif input_type == 'change_port':
                if not text.isdigit() or not (1 <= int(text) <= 65535):
                    await update.message.reply_text("❌ Неверный порт. Должен быть число от 1 до 65535.")
                    return
                
                self.db.update_setting('port', text)
                await update.message.reply_text(f"✅ Порт изменен: {text}")
                
            elif input_type == 'change_price':
                if not text.isdigit() or int(text) <= 0:
                    await update.message.reply_text("❌ Неверная цена. Должно быть положительное число.")
                    return
                
                self.db.update_setting('price', text)
                await update.message.reply_text(f"✅ Цена изменена: {text} руб")
                
            elif input_type == 'change_speed':
                if not text.isdigit() or not (1 <= int(text) <= 1000):
                    await update.message.reply_text("❌ Неверная скорость. Должно быть число от 1 до 1000.")
                    return
                
                self.db.update_setting('speed_limit', text)
                await update.message.reply_text(f"✅ Ограничение скорости изменено: {text} Мбит/с")
            
            elif input_type == 'change_yoomoney_wallet':
                if not text.isdigit() or len(text) != 13:
                    await update.message.reply_text("❌ Неверный формат кошелька. Должно быть 13 цифр.")
                    return
                
                self.db.update_setting('yoomoney_wallet', text)
                await update.message.reply_text(f"✅ Кошелек ЮMoney изменен: {text}")
                
            elif input_type == 'change_yoomoney_token':
                self.db.update_setting('yoomoney_token', text)
                await update.message.reply_text("✅ Токен ЮMoney обновлен!")
            
            del context.user_data['awaiting_input']
            await self.settings_panel_callback(update)
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
            del context.user_data['awaiting_input']

    def run(self):
        self.application.run_polling()

if __name__ == "__main__":
    bot = VPNBot()
    bot.run()
