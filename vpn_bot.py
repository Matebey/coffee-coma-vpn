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
from config import BOT_TOKEN, ADMINS, OVPN_KEYS_DIR, OVPN_CLIENT_DIR, DB_PATH, DNS_SERVERS, OVPN_PORT, yoomoney_api, cloudtips_api, PRICES, REFERRAL_REWARD_DAYS, TRIAL_DAYS, DEFAULT_SPEED_LIMIT, TRIAL_SPEED_LIMIT, SERVER_IP

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
            ("cloudtips_token", "ВАШ_CLOUDTIPS_TOKEN")
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
            
            # Проверяем, существует ли пользователь
            cursor.execute('SELECT referral_code FROM users WHERE user_id = ?', (user_id,))
            existing_user = cursor.fetchone()
            
            if existing_user:
                return existing_user[0]  # Возвращаем существующий реферальный код
            
            # Создаем нового пользователя
            referral_code = self.generate_referral_code()
            
            cursor.execute('''
                INSERT INTO users (user_id, first_name, username, referral_code, referred_by)
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
    def __init__(self, db):
        self.db = db
    
    def create_client_config(self, client_name, speed_limit=10):
        try:
            # Создаем запрос сертификата
            result = subprocess.run([
                '/bin/bash', '-c', 
                f'cd /etc/openvpn/easy-rsa && ./easyrsa --batch gen-req {client_name} nopass'
            ], capture_output=True, text=True, timeout=60)
            
            if result.returncode != 0:
                raise Exception(f"Ошибка создания запроса: {result.stderr}")
            
            # Подписываем сертификат
            result = subprocess.run([
                '/bin/bash', '-c', 
                f'cd /etc/openvpn/easy-rsa && echo "yes" | ./easyrsa --batch sign-req client {client_name}'
            ], capture_output=True, text=True, timeout=60)
            
            if result.returncode != 0:
                raise Exception(f"Ошибка подписания сертификата: {result.stderr}")
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"Ошибка создания сертификата: {e.stderr}")
        except Exception as e:
            raise Exception(f"Ошибка: {str(e)}")

        # Проверяем файлы сертификатов
        cert_path = f"{OVPN_KEYS_DIR}issued/{client_name}.crt"
        key_path = f"{OVPN_KEYS_DIR}private/{client_name}.key"
        
        if not os.path.exists(cert_path):
            raise Exception(f"Файл сертификата не создан: {cert_path}")
        if not os.path.exists(key_path):
            raise Exception(f"Файл ключа не создан: {key_path}")

        # Читаем файлы сертификатов
        try:
            with open(f"{OVPN_KEYS_DIR}ca.crt", 'r') as f:
                ca_cert = f.read()
            with open(cert_path, 'r') as f:
                client_cert = f.read()
            with open(key_path, 'r') as f:
                client_key = f.read()
            with open(f"{OVPN_KEYS_DIR}ta.key", 'r') as f:
                ta_key = f.read()
        except Exception as e:
            raise Exception(f"Ошибка чтения файлов: {str(e)}")

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
        self.ovpn = OpenVPNManager(self.db)
        
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

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user = update.effective_user
            logger.info(f"Команда /start от пользователя {user.id}")
            
            referred_by = None
            if context.args:
                referral_code = context.args[0]
                referred_by = self.db.get_user_by_referral_code(referral_code)
                if referred_by is None:
                    await update.message.reply_text("❌ Неверный реферальный код.")
                    return
            
            referral_code = self.db.add_user(user.id, user.first_name, user.username, referred_by)
            
            if referred_by:
                await update.message.reply_text(f"🎉 Вы зарегистрировались по реферальной ссылке!")
            
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
            price = self.db.get_setting('price', 50)
            
            # Создаем платеж в CloudTips
            payment_data = cloudtips_api.create_payment(price, f"VPN доступ для {user.id}")
            
            if payment_data['success']:
                keyboard = [
                    [InlineKeyboardButton(f"💳 Оплатить {price} руб (CloudTips)", url=payment_data['payment_url'])],
                    [InlineKeyboardButton("✅ Проверить оплату", callback_data='check_payment')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
                ]
            else:
                # Fallback to YooMoney
                yoomoney_url = f"https://yoomoney.ru/quickpay/confirm.xml?receiver={self.db.get_setting('yoomoney_wallet')}&quickpay-form=small&sum={price}&label=vpn_{user.id}&paymentType=AC"
                keyboard = [
                    [InlineKeyboardButton(f"💳 Оплатить {price} руб (ЮMoney)", url=yoomoney_url)],
                    [InlineKeyboardButton("✅ Проверить оплату", callback_data='check_payment')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
                ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"💰 *Тарифы VPN*\n\n"
                f"• 1 месяц - {price} рублей\n"
                f"• Скорость: {self.db.get_setting('speed_limit', 10)} Мбит/с\n"
                f"• Безлимитный трафик\n\n"
                f"Выберите способ оплаты:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Ошибка в команде /buy: {e}")
            await update.message.reply_text("❌ Ошибка при отображении тарифов.")

    async def check_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        price = self.db.get_setting('price', 50)
        
        # Проверяем платеж через ЮMoney API
        payment_received = yoomoney_api.check_payment(f"vpn_{user_id}", price)
        
        if payment_received:
            client_name = f"user_{user_id}_{int(datetime.now().timestamp())}"
            speed_limit = int(self.db.get_setting('speed_limit', 10))
            
            try:
                config_path = self.ovpn.create_client_config(client_name, speed_limit)
                self.db.add_subscription(user_id, client_name, config_path, 30, speed_limit)
                
                await update.message.reply_document(
                    document=open(config_path, 'rb'),
                    caption=f"✅ Оплата подтверждена! Ваш конфиг на 30 дней создан!\n⚡ Скорость: {speed_limit} Мбит/с\n🌐 Сервер: {SERVER_IP}"
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
        try:
            user_id = update.effective_user.id
            config_path = self.db.get_user_config(user_id)
            
            if config_path and os.path.exists(config_path):
                await update.message.reply_document(
                    document=open(config_path, 'rb'),
                    caption="📁 Ваш конфигурационный файл OpenVPN\n\n"
                           "💡 Инструкция по установке:\n"
                           "1. Скачайте файл\n"
                           "2. Установите OpenVPN клиент\n"
                           "3. Импортируйте этот файл\n"
                           "4. Подключитесь к серверу"
                )
            else:
                keyboard = [
                    [InlineKeyboardButton("🛒 Купить доступ", callback_data='buy')],
                    [InlineKeyboardButton("🎁 Получить пробный период", callback_data='trial')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "❌ У вас нет активной подписки.\n\n"
                    "Вы можете приобрести доступ или воспользоваться пробным периодом:",
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Ошибка в команде /myconfig: {e}")
            await update.message.reply_text("❌ Ошибка при получении конфига.")

    async def trial(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            
            if self.db.has_used_trial(user_id):
                await update.message.reply_text(
                    "❌ Вы уже использовали пробный период.\n\n"
                    "Приобретите полный доступ для продолжения использования VPN:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🛒 Купить доступ", callback_data='buy')]
                    ])
                )
                return
            
            client_name = f"trial_{user_id}_{int(datetime.now().timestamp())}"
            config_path = self.ovpn.create_client_config(client_name, TRIAL_SPEED_LIMIT)
            self.db.add_subscription(user_id, client_name, config_path, TRIAL_DAYS, TRIAL_SPEED_LIMIT, True)
            
            await update.message.reply_document(
                document=open(config_path, 'rb'),
                caption=f"🎉 Пробный период активирован на {TRIAL_DAYS} дней!\n"
                       f"⚡ Скорость: {TRIAL_SPEED_LIMIT} Мбит/с\n\n"
                       "💡 После окончания пробного периода вы можете приобрести полный доступ."
            )
            
        except Exception as e:
            logger.error(f"Ошибка в команде /trial: {e}")
            await update.message.reply_text("❌ Ошибка при активации пробного периода.")

    async def referral(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            cursor = self.db.conn.cursor()
            cursor.execute('SELECT referral_code FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            
            if not result:
                await update.message.reply_text("❌ Ошибка получения реферальной информации.")
                return
                
            referral_code = result[0]
            pending_rewards, total_referrals = self.db.get_referral_stats(user_id)
            
            bot_username = (await self.application.bot.get_me()).username
            referral_link = f"https://t.me/{bot_username}?start={referral_code}"
            
            message_text = f"👥 *Реферальная программа*\n\n"
            message_text += f"🔗 Ваша реферальная ссылка:\n`{referral_link}`\n\n"
            message_text += f"📋 Ваш реферальный код: `{referral_code}`\n\n"
            message_text += f"📊 Статистика:\n"
            message_text += f"• Всего приглашено: {total_referrals}\n"
            message_text += f"• Доступно наград: {pending_rewards}\n\n"
            message_text += f"🎁 За каждого приглашенного друга вы получаете +{REFERRAL_REWARD_DAYS} дней к подписке!\n\n"
            message_text += f"💡 Как это работает:\n"
            message_text += f"1. Делитесь своей ссылкой\n"
            message_text += f"2. Ваш друг переходит по ссылке и регистрируется\n"
            message_text += f"3. После его первой покупки вы получаете награду\n"
            message_text += f"4. Используйте награду для продления подписки"

            keyboard = []
            if pending_rewards > 0:
                keyboard.append([InlineKeyboardButton("🎁 Забрать награду", callback_data='claim_reward')])
            keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='main_menu')])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Ошибка в команде /referral: {e}")
            await update.message.reply_text("❌ Ошибка при получении реферальной информации.")

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            
            if not self.db.is_admin(user_id):
                await update.message.reply_text("❌ У вас нет доступа к админ-панели.")
                return
            
            keyboard = [
                [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
                [InlineKeyboardButton("👥 Пользователи", callback_data='admin_users')],
                [InlineKeyboardButton("⚙️ Настройки", callback_data='admin_settings')],
                [InlineKeyboardButton("🔧 Управление подписками", callback_data='admin_subscriptions')],
                [InlineKeyboardButton("🔄 Перезапустить сервисы", callback_data='admin_restart')],
                [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "👨‍💻 *Админ-панель*\n\n"
                "Выберите действие:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Ошибка в команде /admin: {e}")
            await update.message.reply_text("❌ Ошибка при открытии админ-панели.")

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        data = query.data
        
        try:
            if data == 'main_menu':
                await self.show_main_menu(query.message, query.from_user)
                
            elif data == 'buy':
                await self.buy(update, context)
                
            elif data == 'myconfig':
                await self.my_config(update, context)
                
            elif data == 'trial':
                await self.trial(update, context)
                
            elif data == 'referral':
                await self.referral(update, context)
                
            elif data == 'check_payment':
                await self.check_payment(update, context)
                
            elif data == 'claim_reward':
                await self.claim_reward(update, context)
                
            elif data == 'admin_panel':
                await self.admin_panel(update, context)
                
            elif data.startswith('admin_'):
                await self.handle_admin_actions(update, context, data)
                
        except Exception as e:
            logger.error(f"Ошибка в обработчике кнопок: {e}")
            await query.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

    async def claim_reward(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.callback_query.from_user.id
            rewards_claimed = self.db.claim_referral_reward(user_id)
            
            if rewards_claimed > 0:
                # Находим активную подписку и продлеваем ее
                cursor = self.db.conn.cursor()
                cursor.execute('''
                    SELECT client_name FROM subscriptions 
                    WHERE user_id = ? AND end_date > datetime("now")
                    ORDER BY end_date DESC LIMIT 1
                ''', (user_id,))
                
                result = cursor.fetchone()
                if result:
                    client_name = result[0]
                    cursor.execute('''
                        UPDATE subscriptions 
                        SET end_date = datetime(end_date, ?) 
                        WHERE client_name = ?
                    ''', (f"+{rewards_claimed * REFERRAL_REWARD_DAYS} days", client_name))
                    self.db.conn.commit()
                    
                    await update.callback_query.message.reply_text(
                        f"🎉 Поздравляем! Вы получили {rewards_claimed * REFERRAL_REWARD_DAYS} дней "
                        f"за {rewards_claimed} приглашенных друзей!"
                    )
                else:
                    # Создаем новую подписку если нет активной
                    client_name = f"ref_{user_id}_{int(datetime.now().timestamp())}"
                    config_path = self.ovpn.create_client_config(client_name, DEFAULT_SPEED_LIMIT)
                    self.db.add_subscription(user_id, client_name, config_path, 
                                           rewards_claimed * REFERRAL_REWARD_DAYS, DEFAULT_SPEED_LIMIT)
                    
                    await update.callback_query.message.reply_document(
                        document=open(config_path, 'rb'),
                        caption=f"🎉 Поздравляем! Вы получили {rewards_claimed * REFERRAL_REWARD_DAYS} дней "
                               f"за {rewards_claimed} приглашенных друзей!"
                    )
            else:
                await update.callback_query.message.reply_text(
                    "❌ Нет доступных наград для получения."
                )
                
        except Exception as e:
            logger.error(f"Ошибка при получении награды: {e}")
            await update.callback_query.message.reply_text("❌ Ошибка при получении награды.")

    async def handle_admin_actions(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        user_id = update.callback_query.from_user.id
        
        if not self.db.is_admin(user_id):
            await update.callback_query.message.reply_text("❌ У вас нет доступа.")
            return
            
        try:
            if action == 'admin_stats':
                cursor = self.db.conn.cursor()
                
                # Общая статистика
                cursor.execute('SELECT COUNT(*) FROM users')
                total_users = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM subscriptions WHERE end_date > datetime("now")')
                active_subscriptions = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM referrals')
                total_referrals = cursor.fetchone()[0]
                
                cursor.execute('SELECT SUM(speed_limit) FROM subscriptions WHERE end_date > datetime("now")')
                total_bandwidth = cursor.fetchone()[0] or 0
                
                message_text = f"📊 *Статистика системы*\n\n"
                message_text += f"• Всего пользователей: {total_users}\n"
                message_text += f"• Активных подписок: {active_subscriptions}\n"
                message_text += f"• Всего рефералов: {total_referrals}\n"
                message_text += f"• Общая пропускная способность: {total_bandwidth} Мбит/с\n\n"
                message_text += f"💻 Загрузка системы:\n"
                
                # Получаем информацию о системе
                try:
                    load_avg = os.getloadavg()
                    disk_usage = subprocess.check_output("df -h / | tail -1", shell=True).decode()
                    memory_info = subprocess.check_output("free -h", shell=True).decode()
                    
                    message_text += f"• Load average: {load_avg[0]:.2f}, {load_avg[1]:.2f}, {load_avg[2]:.2f}\n"
                    message_text += f"• Диск: {disk_usage.split()[4]}\n"
                    message_text += f"• Память: {memory_info.split()[7]}/{memory_info.split()[8]}\n"
                except:
                    message_text += "• Не удалось получить информацию о системе\n"
                
                await update.callback_query.message.reply_text(message_text, parse_mode='Markdown')
                
            elif action == 'admin_users':
                cursor = self.db.conn.cursor()
                cursor.execute('''
                    SELECT u.user_id, u.first_name, u.username, u.registration_date, 
                           COUNT(s.id) as sub_count
                    FROM users u
                    LEFT JOIN subscriptions s ON u.user_id = s.user_id
                    GROUP BY u.user_id
                    ORDER BY u.registration_date DESC
                    LIMIT 20
                ''')
                
                users = cursor.fetchall()
                
                message_text = "👥 *Последние 20 пользователей*\n\n"
                for user in users:
                    message_text += f"• {user[1]} (@{user[2] or 'нет'}) - {user[3].split()[0]}\n"
                    message_text += f"  ID: {user[0]}, Подписок: {user[4]}\n\n"
                
                await update.callback_query.message.reply_text(message_text, parse_mode='Markdown')
                
            elif action == 'admin_settings':
                keyboard = [
                    [InlineKeyboardButton("💰 Цена подписки", callback_data='setting_price')],
                    [InlineKeyboardButton("⚡ Лимит скорости", callback_data='setting_speed')],
                    [InlineKeyboardButton("🌐 DNS серверы", callback_data='setting_dns')],
                    [InlineKeyboardButton("🔌 Порт OpenVPN", callback_data='setting_port')],
                    [InlineKeyboardButton("💳 Настройки оплаты", callback_data='setting_payment')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.message.reply_text(
                    "⚙️ *Настройки системы*\n\n"
                    "Выберите параметр для изменения:",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
            elif action == 'admin_subscriptions':
                subscriptions = self.db.get_all_subscriptions()
                
                message_text = "🔧 *Активные подписки*\n\n"
                for sub in subscriptions:
                    days_left = (datetime.strptime(sub[3], '%Y-%m-%d %H:%M:%S') - datetime.now()).days
                    message_text += f"• {sub[5]} - {sub[1]}\n"
                    message_text += f"  Осталось: {days_left} дней, Скорость: {sub[4]} Мбит/с\n"
                    message_text += f"  Конфиг: {sub[2]}\n\n"
                
                if not subscriptions:
                    message_text += "Нет активных подписок"
                
                await update.callback_query.message.reply_text(message_text, parse_mode='Markdown')
                
            elif action == 'admin_restart':
                try:
                    subprocess.run(['systemctl', 'restart', 'openvpn@server'], timeout=30)
                    subprocess.run(['systemctl', 'restart', 'coffee-coma-vpn'], timeout=30)
                    
                    await update.callback_query.message.reply_text(
                        "✅ Сервисы успешно перезапущены!\n\n"
                        "• OpenVPN сервер\n"
                        "• Telegram бот"
                    )
                except Exception as e:
                    await update.callback_query.message.reply_text(f"❌ Ошибка при перезапуске: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Ошибка в админ-панели: {e}")
            await update.callback_query.message.reply_text("❌ Ошибка при выполнении действия.")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений для админ-панели"""
        user_id = update.effective_user.id
        message_text = update.message.text
        
        if not self.db.is_admin(user_id):
            return
            
        # Здесь можно добавить логику для изменения настроек через сообщения
        # Например: "/set price 100" - установить цену 100 рублей
        
        if message_text.startswith('/set '):
            parts = message_text.split()
            if len(parts) >= 3:
                setting_key = parts[1]
                setting_value = ' '.join(parts[2:])
                
                if setting_key in ['price', 'speed_limit', 'port', 'dns1', 'dns2', 
                                 'yoomoney_wallet', 'cloudtips_token']:
                    self.db.update_setting(setting_key, setting_value)
                    await update.message.reply_text(f"✅ Настройка '{setting_key}' обновлена на '{setting_value}'")
                else:
                    await update.message.reply_text("❌ Неизвестная настройка")
            else:
                await update.message.reply_text("❌ Неправильный формат команды. Используйте: /set ключ значение")

    def run(self):
        """Запуск бота"""
        logger.info("Запуск бота...")
        self.application.run_polling()

if __name__ == "__main__":
    try:
        bot = VPNBot()
        bot.run()
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        print(f"Критическая ошибка: {e}")
