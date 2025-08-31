import logging
import sqlite3
import subprocess
import os
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from config import BOT_TOKEN, ADMINS, OVPN_KEYS_DIR, OVPN_CLIENT_DIR, DB_PATH, DNS_SERVERS, OVPN_PORT

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

    def get_all_subscriptions(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT user_id, client_name, config_path, end_date FROM subscriptions')
        return cursor.fetchall()

    def delete_subscription(self, client_name):
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM subscriptions WHERE client_name = ?', (client_name,))
        self.conn.commit()

class OpenVPNManager:
    def __init__(self):
        self.db = Database()

    def create_client_config(self, client_name):
        # Генерация клиентского сертификата с автоматическим подтверждением
        try:
            # Генерация запроса
            subprocess.run([
                'cd /etc/openvpn/easy-rsa/ && ./easyrsa gen-req {} nopass'.format(client_name),
            ], shell=True, check=True, capture_output=True)
            
            # Автоматическое подписание (yes + enter)
            subprocess.run([
                'cd /etc/openvpn/easy-rsa/ && echo -e "yes" | ./easyrsa sign-req client {}'.format(client_name),
            ], shell=True, check=True, capture_output=True)
            
        except subprocess.CalledProcessError as e:
            logger.error(f"OpenVPN error: {e.stderr}")
            raise

        # Получаем текущие настройки
        dns1 = self.db.get_setting('dns1', '8.8.8.8')
        dns2 = self.db.get_setting('dns2', '8.8.4.4')
        port = self.db.get_setting('port', '1194')
        server_ip = subprocess.check_output("curl -s ifconfig.me", shell=True).decode().strip()

        # Создание конфигурационного файла
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
{open(os.path.join(OVPN_KEYS_DIR, 'issued', f'{client_name}.crt')).read()}
</cert>
<key>
{open(os.path.join(OVPN_KEYS_DIR, 'private', f'{client_name}.key')).read()}
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

    def revoke_client(self, client_name):
        try:
            # Отзываем сертификат
            subprocess.run([
                'cd /etc/openvpn/easy-rsa/ && ./easyrsa revoke {}'.format(client_name),
            ], shell=True, check=True, capture_output=True)
            
            # Обновляем CRL
            subprocess.run([
                'cd /etc/openvpn/easy-rsa/ && ./easyrsa gen-crl'
            ], shell=True, check=True, capture_output=True)
            
            # Удаляем конфиг файл
            config_path = os.path.join(OVPN_CLIENT_DIR, f'{client_name}.ovpn')
            if os.path.exists(config_path):
                os.remove(config_path)
                
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Revoke error: {e.stderr}")
            return False

class VPNBot:
    def __init__(self):
        self.db = Database()
        self.ovpn = OpenVPNManager()
        self.application = Application.builder().token(BOT_TOKEN).build()
        
        # Регистрация обработчиков
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("buy", self.buy))
        self.application.add_handler(CommandHandler("myconfig", self.my_config))
        self.application.add_handler(CommandHandler("admin", self.admin_panel))
        self.application.add_handler(CommandHandler("settings", self.settings_panel))
        self.application.add_handler(CommandHandler("checkpayment", self.check_payment))
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Обработчик текстовых сообщений для настроек
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        self.db.add_user(user.id, user.first_name, user.username)
        
        keyboard = [
            [InlineKeyboardButton("🛒 Купить доступ (50 руб/месяц)", callback_data='buy')],
            [InlineKeyboardButton("📁 Мой конфиг", callback_data='myconfig')]
        ]
        
        if self.db.is_admin(user.id):
            keyboard.append([InlineKeyboardButton("👨‍💻 Админ панель", callback_data='admin_panel')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_html(
            f"Привет, {user.mention_html()}!\\n\\n"
            "🤖 <b>Coffee Coma VPN Bot</b> - продажа доступа к VPN серверу\\n\\n"
            "Выберите действие:",
            reply_markup=reply_markup
        )

    async def buy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        price = self.db.get_setting('price', 50)
        payment_url = f"https://yoomoney.ru/quickpay/confirm.xml?receiver=ВАШ_НОМЕР_КОШЕЛЬКА&quickpay-form=small&sum={price}&label=vpn_{user.id}&paymentType=AC"
        
        keyboard = [
            [InlineKeyboardButton(f"💳 Оплатить {price} руб", url=payment_url)],
            [InlineKeyboardButton("✅ Проверить оплату", callback_data='check_payment')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"Оплатите {price} рублей за доступ на 1 месяц\\n\\n"
            "После оплаты нажмите 'Проверить оплату'",
            reply_markup=reply_markup
        )

    async def check_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        # Упрощенная проверка - всегда успешно
        # В реальности здесь должна быть интеграция с ЮMoney API
        client_name = f"user_{user_id}_{int(datetime.now().timestamp())}"
        
        try:
            config_path = self.ovpn.create_client_config(client_name)
            self.db.add_subscription(user_id, client_name, config_path, 30)
            
            await update.message.reply_document(
                document=open(config_path, 'rb'),
                caption="✅ Оплата подтверждена! Ваш конфиг на 30 дней создан!"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")

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
        
        keyboard = [
            [InlineKeyboardButton("🎁 Бесплатный доступ", callback_data='admin_free')],
            [InlineKeyboardButton("⚙️ Настройки сервера", callback_data='admin_settings')],
            [InlineKeyboardButton("🗑️ Управление ключами", callback_data='admin_keys')],
            [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text("👨‍💻 Панель администратора:", reply_markup=reply_markup)

    async def settings_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.db.is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен")
            return
        
        # Получаем текущие настройки
        dns1 = self.db.get_setting('dns1', '8.8.8.8')
        dns2 = self.db.get_setting('dns2', '8.8.4.4')
        port = self.db.get_setting('port', '1194')
        price = self.db.get_setting('price', '50')
        
        keyboard = [
            [InlineKeyboardButton(f"🌐 DNS: {dns1} {dns2}", callback_data='change_dns')],
            [InlineKeyboardButton(f"🔌 Порт: {port}", callback_data='change_port')],
            [InlineKeyboardButton(f"💰 Цена: {price} руб", callback_data='change_price')],
            [InlineKeyboardButton("🔙 Назад", callback_data='admin_back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = "⚙️ <b>Текущие настройки сервера:</b>\n\n"
        message += f"🌐 <b>DNS серверы:</b> {dns1}, {dns2}\n"
        message += f"🔌 <b>Порт OpenVPN:</b> {port}\n"
        message += f"💰 <b>Цена подписки:</b> {price} руб\n\n"
        message += "Выберите параметр для изменения:"
        
        await update.message.reply_html(message, reply_markup=reply_markup)

    async def manage_keys(self, query):
        user_id = query.from_user.id
        if not self.db.is_admin(user_id):
            await query.message.reply_text("❌ Доступ запрещен")
            return
        
        subscriptions = self.db.get_all_subscriptions()
        
        if not subscriptions:
            await query.message.reply_text("❌ Нет активных подписок")
            return
        
        keyboard = []
        for user_id, client_name, config_path, end_date in subscriptions:
            keyboard.append([InlineKeyboardButton(
                f"🗑️ {client_name} (до {end_date})", 
                callback_data=f'revoke_{client_name}'
            )])
        
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_back')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_text("🗑️ Выберите ключ для удаления:", reply_markup=reply_markup)

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        if not self.db.is_admin(user_id) and not query.data.startswith('check_'):
            await query.message.reply_text("❌ Доступ запрещен")
            return
        
        if query.data == 'buy':
            await self.buy(update, context)
        elif query.data == 'myconfig':
            await self.my_config(update, context)
        elif query.data == 'admin_panel':
            await self.admin_panel(update, context)
        elif query.data == 'admin_free':
            await self.create_free_config(query)
        elif query.data == 'admin_settings':
            await self.settings_panel(update, context)
        elif query.data == 'admin_keys':
            await self.manage_keys(query)
        elif query.data == 'admin_stats':
            await self.show_stats(query)
        elif query.data == 'admin_back':
            await self.admin_panel(update, context)
        elif query.data == 'change_dns':
            context.user_data['awaiting_input'] = 'dns'
            await query.message.reply_text("Введите новые DNS серверы через пробел (например: <code>1.1.1.1 1.0.0.1</code>):", parse_mode='HTML')
        elif query.data == 'change_port':
            context.user_data['awaiting_input'] = 'port'
            await query.message.reply_text("Введите новый порт для OpenVPN (например: <code>443</code>):", parse_mode='HTML')
        elif query.data == 'change_price':
            context.user_data['awaiting_input'] = 'price'
            await query.message.reply_text("Введите новую цену подписки в рублях (например: <code>100</code>):", parse_mode='HTML')
        elif query.data == 'check_payment':
            await self.check_payment(update, context)
        elif query.data.startswith('revoke_'):
            client_name = query.data.replace('revoke_', '')
            success = self.ovpn.revoke_client(client_name)
            if success:
                self.db.delete_subscription(client_name)
                await query.message.reply_text(f"✅ Ключ {client_name} отозван и удален!")
            else:
                await query.message.reply_text(f"❌ Ошибка при отзыве ключа {client_name}")

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
            
            del context.user_data['awaiting_input']
            await self.settings_panel(update, context)
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
            del context.user_data['awaiting_input']

    async def create_free_config(self, query):
        user_id = query.from_user.id
        if not self.db.is_admin(user_id):
            await query.message.reply_text("❌ Доступ запрещен")
            return
        
        try:
            client_name = f"admin_{user_id}_{int(datetime.now().timestamp())}"
            config_path = self.ovpn.create_client_config(client_name)
            self.db.add_subscription(user_id, client_name, config_path, 30)
            
            await query.message.reply_document(
                document=open(config_path, 'rb'),
                caption="✅ Ваш бесплатный конфиг на 30 дней создан!"
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Ошибка при создании конфига: {str(e)}")

    async def show_stats(self, query):
        user_id = query.from_user.id
        if not self.db.is_admin(user_id):
            await query.message.reply_text("❌ Доступ запрещен")
            return
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users')
        users_count = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM subscriptions')
        subs_count = cursor.fetchone()[0]
        conn.close()
        
        await query.message.reply_text(
            f"📊 Статистика:\\n👥 Пользователей: {users_count}\\n🔗 Активных подписок: {subs_count}"
        )

    def run(self):
        self.application.run_polling()

if __name__ == "__main__":
    bot = VPNBot()
    bot.run()
