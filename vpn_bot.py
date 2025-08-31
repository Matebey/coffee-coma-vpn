import logging
import sqlite3
import subprocess
import os
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

class OpenVPNManager:
    def create_client_config(self, client_name):
        # Генерация клиентского сертификата
        subprocess.run([
            'cd /etc/openvpn/easy-rsa/ && ./easyrsa gen-req {} nopass'.format(client_name),
        ], shell=True, check=True)
        
        subprocess.run([
            'cd /etc/openvpn/easy-rsa/ && echo "yes" | ./easyrsa sign-req client {}'.format(client_name),
        ], shell=True, check=True)

        # Получаем текущие настройки
        dns1, dns2 = DNS_SERVERS
        port = OVPN_PORT
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

class VPNBot:
    def __init__(self):
        self.db = Database()
        self.ovpn = OpenVPNManager()
        self.application = Application.builder().token(BOT_TOKEN).build()
        
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("buy", self.buy))
        self.application.add_handler(CommandHandler("myconfig", self.my_config))
        self.application.add_handler(CommandHandler("admin", self.admin_panel))
        self.application.add_handler(CommandHandler("settings", self.settings_panel))
        self.application.add_handler(CallbackQueryHandler(self.button_handler))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        self.db.add_user(user.id, user.first_name, user.username)
        
        keyboard = [
            [InlineKeyboardButton("🛒 Купить доступ (50 руб/месяц)", callback_data='buy')],
            [InlineKeyboardButton("📁 Мой конфиг", callback_data='myconfig')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_html(
            f"Привет, {user.mention_html()}!\\n\\n"
            "🤖 <b>Coffee Coma VPN Bot</b> - продажа доступа к VPN серверу\\n\\n"
            "Выберите действие:",
            reply_markup=reply_markup
        )

    async def buy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        payment_url = "https://yoomoney.ru/quickpay/confirm.xml?receiver=ВАШ_НОМЕР_КОШЕЛЬКА&quickpay-form=small&sum=50&label=vpn_{}&paymentType=AC".format(user.id)
        
        keyboard = [[InlineKeyboardButton("💳 Оплатить 50 руб", url=payment_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "Оплатите 50 рублей за доступ на 1 месяц\\n\\n"
            "После оплаты нажмите /checkpayment для проверки",
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
        
        keyboard = [
            [InlineKeyboardButton("🎁 Бесплатный доступ", callback_data='admin_free')],
            [InlineKeyboardButton("⚙️ Настройки сервера", callback_data='admin_settings')],
            [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text("👨‍💻 Панель администратора:", reply_markup=reply_markup)

    async def settings_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.db.is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен")
            return
        
        keyboard = [
            [InlineKeyboardButton("🌐 Изменить DNS", callback_data='change_dns')],
            [InlineKeyboardButton("🔌 Изменить порт", callback_data='change_port')],
            [InlineKeyboardButton("💰 Изменить цену", callback_data='change_price')],
            [InlineKeyboardButton("🔙 Назад", callback_data='admin_back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text("⚙️ Настройки сервера:", reply_markup=reply_markup)

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.data == 'buy':
            await self.buy(update, context)
        elif query.data == 'myconfig':
            await self.my_config(update, context)
        elif query.data == 'admin_free':
            await self.create_free_config(query)
        elif query.data == 'admin_settings':
            await self.settings_panel(update, context)
        elif query.data == 'admin_stats':
            await self.show_stats(query)
        elif query.data == 'change_dns':
            await query.message.reply_text("Введите новые DNS серверы через пробел (например: 1.1.1.1 1.0.0.1):")
            context.user_data['awaiting_dns'] = True
        elif query.data == 'change_port':
            await query.message.reply_text("Введите новый порт для OpenVPN:")
            context.user_data['awaiting_port'] = True
        elif query.data == 'change_price':
            await query.message.reply_text("Введите новую цену подписки:")
            context.user_data['awaiting_price'] = True
        elif query.data == 'admin_back':
            await self.admin_panel(update, context)

    async def create_free_config(self, query):
        user_id = query.from_user.id
        if not self.db.is_admin(user_id):
            await query.message.reply_text("❌ Доступ запрещен")
            return
        
        client_name = f"admin_{user_id}_{int(datetime.now().timestamp())}"
        config_path = self.ovpn.create_client_config(client_name)
        self.db.add_subscription(user_id, client_name, config_path, 30)
        
        await query.message.reply_document(
            document=open(config_path, 'rb'),
            caption="✅ Ваш бесплатный конфиг на 30 дней создан!"
        )

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