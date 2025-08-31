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

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.create_tables()

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
                user_id INTEGER PRIMARY KEY,
                client_name TEXT,
                config_path TEXT,
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                speed_limit INTEGER DEFAULT 10,
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
        cursor = self.conn.cursor()
        
        # Генерируем реферальный код
        referral_code = self.generate_referral_code()
        
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, first_name, username, referral_code, referred_by)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, first_name, username, referral_code, referred_by))
        
        # Если пользователь пришел по реферальной ссылке
        if referred_by:
            cursor.execute('''
                INSERT INTO referrals (referrer_id, referred_id)
                VALUES (?, ?)
            ''', (referred_by, user_id))
            
        self.conn.commit()
        return referral_code

    def generate_referral_code(self):
        """Генерирует уникальный реферальный код"""
        while True:
            code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            cursor = self.conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM users WHERE referral_code = ?', (code,))
            if cursor.fetchone()[0] == 0:
                return code

    def add_subscription(self, user_id, client_name, config_path, days, speed_limit=10, is_trial=False):
        start_date = datetime.now()
        end_date = start_date + timedelta(days=days)
        cursor = self.conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO subscriptions (user_id, client_name, config_path, start_date, end_date, speed_limit)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, client_name, config_path, start_date, end_date, speed_limit))
        
        if is_trial:
            cursor.execute('UPDATE users SET trial_used = 1 WHERE user_id = ?', (user_id,))
            
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

    def get_all_subscriptions(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT s.user_id, s.client_name, s.config_path, s.end_date, s.speed_limit, u.first_name
            FROM subscriptions s
            JOIN users u ON s.user_id = u.user_id
        ''')
        return cursor.fetchall()

    def delete_subscription(self, client_name):
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM subscriptions WHERE client_name = ?', (client_name,))
        self.conn.commit()

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
            SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND reward_claimed = 0
        ''', (user_id,))
        pending_rewards = cursor.fetchone()[0]
        
        cursor.execute('''
            SELECT COUNT(*) FROM referrals WHERE referrer_id = ?
        ''', (user_id,))
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
                '/usr/bin/env', 'bash', '-c', 
                f'cd /etc/openvpn/easy-rsa && ./easyrsa --batch gen-req {client_name} nopass'
            ], check=True, capture_output=True, text=True, timeout=30)
            
            # Подписываем сертификат
            subprocess.run([
                '/usr/bin/env', 'bash', '-c', 
                f'cd /etc/openvpn/easy-rsa && echo "yes" | ./easyrsa --batch sign-req client {client_name}'
            ], check=True, capture_output=True, text=True, timeout=30)
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"Ошибка создания сертификата: {e.stderr}")

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
            print(f"Ошибка настройки ограничения скорости: {e}")

    def revoke_client(self, client_name):
        try:
            subprocess.run([
                '/usr/bin/env', 'bash', '-c', 
                f'cd /etc/openvpn/easy-rsa && echo "yes" | ./easyrsa --batch revoke {client_name}'
            ], check=True, capture_output=True, text=True, timeout=30)
            
            subprocess.run([
                '/usr/bin/env', 'bash', '-c', 
                f'cd /etc/openvpn/easy-rsa && ./easyrsa --batch gen-crl'
            ], check=True, capture_output=True, text=True, timeout=30)
            
            subprocess.run(['systemctl', 'restart', 'openvpn@server'], check=True, timeout=30)
            
            config_path = os.path.join(OVPN_CLIENT_DIR, f'{client_name}.ovpn')
            if os.path.exists(config_path):
                os.remove(config_path)
                
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"Ошибка отзыва ключа: {e}")
            return False

class VPNBot:
    def __init__(self):
        self.db = Database()
        self.ovpn = OpenVPNManager()
        self.application = Application.builder().token(BOT_TOKEN).build()
        
        # Регистрируем обработчики
        self.setup_handlers()

    def setup_handlers(self):
        """Настройка всех обработчиков команд"""
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
        user = update.effective_user
        referral_code = None
        
        # Проверяем реферальную ссылку
        if context.args:
            referral_code = context.args[0]
            referred_by = self.db.get_user_by_referral_code(referral_code)
            if referred_by and referred_by != user.id:
                referral_code = referral_code
            else:
                referral_code = None
        
        referral_code = self.db.add_user(user.id, user.first_name, user.username, referred_by if referral_code else None)
        
        await self.show_main_menu(update.message, user, referral_code)

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
        
        message_text = f"Привет, {user.first_name}!\\n\\n"
        message_text += "🤖 Coffee Coma VPN Bot - продажа доступа к VPN серверу\\n\\n"
        
        if referral_code:
            message_text += f"📋 Ваш реферальный код: `{referral_code}`\\n"
            message_text += f"🔗 Ваша реферальная ссылка: https://t.me/{(await self.application.bot.get_me()).username}?start={referral_code}\\n\\n"
        
        message_text += "Выберите действие:"
        
        await message.reply_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')

    async def trial(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if self.db.has_used_trial(user_id):
            keyboard = [
                [InlineKeyboardButton("🛒 Купить доступ", callback_data='buy')],
                [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "❌ Вы уже использовали бесплатный пробный период.\\nПриобретите полный доступ для продолжения использования VPN.",
                reply_markup=reply_markup
            )
            return
        
        try:
            client_name = f"trial_{user_id}_{int(datetime.now().timestamp())}"
            config_path = self.ovpn.create_client_config(client_name, speed_limit=5)  # 5 Мбит/с для пробного периода
            self.db.add_subscription(user_id, client_name, config_path, 5, speed_limit=5, is_trial=True)
            
            keyboard = [
                [InlineKeyboardButton("📁 Скачать конфиг", callback_data='myconfig')],
                [InlineKeyboardButton("👥 Реферальная программа", callback_data='referral')],
                [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "✅ Вам предоставлен бесплатный пробный период на 5 дней!\\n\\n"
                "⚡ Скорость: 5 Мбит/с\\n"
                "⏰ Срок действия: 5 дней\\n\\n"
                "Для продления доступа приобретите полную подписку.",
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
        
        message_text = "👥 Реферальная программа\\n\\n"
        message_text += f"📋 Ваш реферальный код: `{referral_code}`\\n"
        message_text += f"🔗 Ваша ссылка: {referral_link}\\n\\n"
        message_text += f"📊 Статистика:\\n"
        message_text += f"• Всего приглашено: {total_referrals}\\n"
        message_text += f"• Доступно наград: {pending_rewards}\\n\\n"
        message_text += "🎁 За каждого приглашенного друга:\\n"
        message_text += "• Ваш друг получает пробный период 5 дней\\n"
        message_text += "• Вы получаете +5 дней к вашей подписке\\n\\n"
        
        keyboard = []
        if pending_rewards > 0:
            keyboard.append([InlineKeyboardButton("🎯 Забрать награду", callback_data='claim_reward')])
        
        keyboard.extend([
            [InlineKeyboardButton("📋 Поделиться ссылкой", url=f"https://t.me/share/url?url={referral_link}&text=Присоединяйся%20к%20VPN!")],
            [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')

    async def check_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        price = self.db.get_setting('price', 50)
        label = f"vpn_{user_id}"
        
        # ПРОВЕРЯЕМ РЕАЛЬНЫЙ ПЛАТЕЖ ЧЕРЕЗ ЮMONEY API
        payment_received = yoomoney_api.check_payment(label, price)
        
        if payment_received:
            client_name = f"user_{user_id}_{int(datetime.now().timestamp())}"
            speed_limit = 10  # стандартная скорость
            
            try:
                config_path = self.ovpn.create_client_config(client_name, speed_limit)
                self.db.add_subscription(user_id, client_name, config_path, 30, speed_limit)
                
                await update.message.reply_document(
                    document=open(config_path, 'rb'),
                    caption="✅ Оплата подтверждена! Ваш конфиг на 30 дней создан!\\n⚡ Скорость: 10 Мбит/с"
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

    # ... остальной код с исправленными обработчиками ...

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
        elif data == 'trial':
            await self.trial_callback(query)
        elif data == 'referral':
            await self.referral_callback(query)
        elif data == 'claim_reward':
            await self.claim_reward_callback(query)
        # ... остальные обработчики ...

    async def claim_reward_callback(self, query):
        user_id = query.from_user.id
        rewards_claimed = self.db.claim_referral_reward(user_id)
        
        if rewards_claimed > 0:
            # Продлеваем подписку на 5 дней за каждого реферала
            cursor = self.db.conn.cursor()
            cursor.execute('SELECT client_name, end_date FROM subscriptions WHERE user_id = ?', (user_id,))
            subscription = cursor.fetchone()
            
            if subscription:
                client_name, end_date = subscription
                new_end_date = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S') + timedelta(days=5 * rewards_claimed)
                cursor.execute('UPDATE subscriptions SET end_date = ? WHERE user_id = ?', (new_end_date.strftime('%Y-%m-%d %H:%M:%S'), user_id))
                self.db.conn.commit()
                
                await query.message.edit_text(
                    f"🎉 Поздравляем! Вы получили {rewards_claimed * 5} дней к вашей подписке!\\n"
                    f"📅 Новая дата окончания: {new_end_date.strftime('%d.%m.%Y')}"
                )
            else:
                # Создаем новую подписку если нет активной
                client_name = f"user_{user_id}_{int(datetime.now().timestamp())}"
                try:
                    config_path = self.ovpn.create_client_config(client_name, speed_limit=10)
                    self.db.add_subscription(user_id, client_name, config_path, 5 * rewards_claimed, speed_limit=10)
                    
                    await query.message.reply_document(
                        document=open(config_path, 'rb'),
                        caption=f"🎉 Поздравляем! Вы получили {rewards_claimed * 5} дней доступа к VPN!"
                    )
                except Exception as e:
                    await query.message.edit_text(f"❌ Ошибка при создании конфига: {str(e)}")
        else:
            await query.message.edit_text("❌ Нет доступных наград для получения.")

# ... остальной код ...

if __name__ == "__main__":
    bot = VPNBot()
    bot.run()
