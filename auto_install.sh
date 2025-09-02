#!/bin/bash

# Автоматическая установка VPN бота
echo "=== Автоматическая установка VPN бота ==="

# Проверка на root
if [ "$EUID" -ne 0 ]
  then echo "Пожалуйста, запустите скрипт от имени root"
  exit
fi

# Ввод данных
echo "Введите данные для настройки:"
read -p "Введите токен бота от @BotFather: " BOT_TOKEN
read -p "Введите ваш Telegram ID: " TELEGRAM_ID
read -p "Введите токен YooMoney (или нажмите Enter чтобы пропустить): " YOOMONEY_TOKEN
read -p "Введите токен CloudTips (или нажмите Enter чтобы пропустить): " CLOUDTIPS_TOKEN

# Установка системных зависимостей
echo "Установка системных зависимостей..."
apt update
apt upgrade -y
apt install -y python3 python3-pip python3-venv git openvpn easy-rsa sqlite3

# Установка OpenVPN через автоматический скрипт
echo "Установка OpenVPN..."
wget https://git.io/vpn -O openvpn-install.sh
chmod +x openvpn-install.sh

# Автоматический ответ на вопросы установщика OpenVPN
echo "Автоматическая установка OpenVPN..."
export AUTO_INSTALL=y
export APPROVE_INSTALL=y
export APPROVE_IP=y
export IPV6_SUPPORT=n
export PORT_CHOICE=1
export PROTOCOL_CHOICE=1
export DNS=1
export COMPRESSION_ENABLED=n
export CUSTOMIZE_ENC=n
export CLIENT=client
export PASS=1

# Запуск установщика OpenVPN
./openvpn-install.sh << EOF
$IPV6_SUPPORT
$PORT_CHOICE
$PROTOCOL_CHOICE
$DNS
$COMPRESSION_ENABLED
$CUSTOMIZE_ENC
$CLIENT
$PASS
EOF

# Настройка OpenVPN сервера
echo "Настройка OpenVPN сервера..."

# Создание директории для конфигураций
mkdir -p /etc/openvpn/easy-rsa/
cd /etc/openvpn/easy-rsa/

# Инициализация PKI
echo "Инициализация PKI..."
easyrsa init-pki

# Создание CA
echo "Создание CA..."
easyrsa --batch build-ca nopass

# Генерация серверного сертификата
echo "Генерация серверного сертификата..."
easyrsa build-server-full server nopass

# Генерация DH параметров
echo "Генерация DH параметров..."
easyrsa gen-dh

# Генерация TLS ключа
echo "Генерация TLS ключа..."
openvpn --genkey secret ta.key

# Создание конфигурации сервера
echo "Создание конфигурации сервера..."
cat > /etc/openvpn/server.conf << EOF
port 1194
proto udp
dev tun
ca /etc/openvpn/easy-rsa/pki/ca.crt
cert /etc/openvpn/easy-rsa/pki/issued/server.crt
key /etc/openvpn/easy-rsa/pki/private/server.key
dh /etc/openvpn/easy-rsa/pki/dh.pem
server 10.8.0.0 255.255.255.0
ifconfig-pool-persist /var/log/openvpn/ipp.txt
push "redirect-gateway def1 bypass-dhcp"
push "dhcp-option DNS 8.8.8.8"
push "dhcp-option DNS 8.8.4.4"
keepalive 10 120
tls-auth /etc/openvpn/easy-rsa/ta.key 0
cipher AES-256-CBC
persist-key
persist-tun
status /var/log/openvpn/openvpn-status.log
verb 3
explicit-exit-notify 1
EOF

# Включение IP forwarding
echo "Включение IP forwarding..."
echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
sysctl -p

# Настройка firewall
echo "Настройка firewall..."
iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o eth0 -j MASQUERADE
iptables-save > /etc/iptables/rules.v4

# Создание виртуального окружения
echo "Создание виртуального окружения..."
python3 -m venv /opt/vpnbot/venv
source /opt/vpnbot/venv/bin/activate

# Установка Python зависимостей с обходом проблемных версий
echo "Установка Python зависимостей..."
pip install --upgrade pip
pip install python-telegram-bot==13.7 pyyaml==5.4.1

# Создание директории для бота
echo "Создание структуры бота..."
mkdir -p /opt/vpnbot/{config,db,scripts}

# Создание конфигурационного файла
echo "Создание конфигурации бота..."
cat > /opt/vpnbot/config/config.yaml << EOF
bot:
  token: "$BOT_TOKEN"
  admin_id: $TELEGRAM_ID

payments:
  yoomoney:
    token: "$YOOMONEY_TOKEN"
    enabled: false
  cloudtips:
    token: "$CLOUDTIPS_TOKEN"
    enabled: false

vpn:
  server_ip: $(curl -s ifconfig.me)
  server_port: 1194
  config_path: "/etc/openvpn/client-configs"
  price: 100.0
  duration_days: 30

database:
  path: "/opt/vpnbot/db/vpn_bot.db"
EOF

# Создание основного скрипта бота
echo "Создание скрипта бота..."
cat > /opt/vpnbot/vpn_bot.py << 'EOF'
#!/usr/bin/env python3
import logging
import sqlite3
import yaml
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка конфигурации
with open('/opt/vpnbot/config/config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Состояния для ConversationHandler
SELECTING_ACTION, PROCESSING_PAYMENT = range(2)

class VPNBot:
    def __init__(self):
        self.bot_token = config['bot']['token']
        self.admin_id = config['bot']['admin_id']
        self.db_path = config['database']['path']
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                balance REAL DEFAULT 0,
                is_active BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        conn.commit()
        conn.close()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('INSERT OR IGNORE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)',
                      (user.id, user.username, user.first_name, user.last_name))
        conn.commit()
        conn.close()

        welcome_text = f"""
👋 Привет, {user.first_name}!

Добро пожаловать в VPN сервис! Здесь ты можешь:
• 🛡️ Получить безопасный доступ в интернет
• 🌐 Обойти географические ограничения
• 🔒 Защитить свою приватность

Для начала работы используй команды:
/buy - Купить VPN доступ
/status - Проверить статус
/help - Получить помощь

Цена: {config['vpn']['price']} руб. за {config['vpn']['duration_days']} дней
        """
        
        await update.message.reply_text(welcome_text)

    async def buy_vpn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [['💰 Оплатить', '❌ Отмена']]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        
        await update.message.reply_text(
            f"💳 Для получения VPN доступа необходимо оплатить {config['vpn']['price']} руб.\n\n"
            "После оплаты вы получите файл конфигурации для подключения.",
            reply_markup=reply_markup
        )
        
        return SELECTING_ACTION

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        
        if text == '💰 Оплатить':
            await update.message.reply_text(
                "⚠️ Платежная система в разработке. Для тестирования используйте команду /test_payment",
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
        
        elif text == '❌ Отмена':
            await update.message.reply_text(
                "❌ Операция отменена.",
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
        
        return SELECTING_ACTION

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "❌ Операция отменена.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    async def test_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        if user.id != self.admin_id:
            await update.message.reply_text("❌ Эта команда только для администратора")
            return

        # Генерация тестового конфига
        client_name = f"client_{user.id}"
        os.system(f"/etc/openvpn/easy-rsa/easyrsa build-client-full {client_name} nopass")
        
        # Создание клиентского конфига
        client_config = f"""client
dev tun
proto udp
remote {config['vpn']['server_ip']} {config['vpn']['server_port']}
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
cipher AES-256-CBC
verb 3
<ca>
{open('/etc/openvpn/easy-rsa/pki/ca.crt').read()}
</ca>
<cert>
{open(f'/etc/openvpn/easy-rsa/pki/issued/{client_name}.crt').read()}
</cert>
<key>
{open(f'/etc/openvpn/easy-rsa/pki/private/{client_name}.key').read()}
</key>
<tls-auth>
{open('/etc/openvpn/easy-rsa/ta.key').read()}
</tls-auth>
"""
        
        with open(f'/tmp/{client_name}.ovpn', 'w') as f:
            f.write(client_config)
        
        await update.message.reply_document(
            document=open(f'/tmp/{client_name}.ovpn', 'rb'),
            caption="✅ Ваш VPN конфиг готов! Используйте его в OpenVPN клиенте."
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """
🤖 Доступные команды:

/start - Начать работу с ботом
/buy - Купить VPN доступ
/status - Проверить статус подписки
/help - Показать эту справку

📞 Поддержка: @your_support
        """
        await update.message.reply_text(help_text)

def main():
    bot = VPNBot()
    
    application = Application.builder().token(bot.bot_token).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("test_payment", bot.test_payment))
    
    # Conversation handler для покупки
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('buy', bot.buy_vpn)],
        states={
            SELECTING_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message)],
        },
        fallbacks=[CommandHandler('cancel', bot.cancel)],
    )
    
    application.add_handler(conv_handler)

    # Запуск бота
    application.run_polling()

if __name__ == '__main__':
    main()
EOF

# Создание сервисного файла
echo "Создание сервиса systemd..."
cat > /etc/systemd/system/vpnbot.service << EOF
[Unit]
Description=VPN Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/vpnbot
Environment=PATH=/opt/vpnbot/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/opt/vpnbot/venv/bin/python /opt/vpnbot/vpn_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Установка прав
chmod +x /opt/vpnbot/vpn_bot.py
chown -R root:root /opt/vpnbot

# Запуск сервиса
echo "Запуск VPN бота..."
systemctl daemon-reload
systemctl enable vpnbot.service
systemctl start vpnbot.service

# Создание скрипта управления клиентами
echo "Создание скрипта управления клиентами..."
cat > /usr/local/bin/vpn-manage << 'EOF'
#!/bin/bash

case "$1" in
    add)
        if [ -z "$2" ]; then
            echo "Usage: vpn-manage add <client_name>"
            exit 1
        fi
        cd /etc/openvpn/easy-rsa/
        ./easyrsa build-client-full "$2" nopass
        echo "Клиент $2 добавлен"
        ;;
    revoke)
        if [ -z "$2" ]; then
            echo "Usage: vpn-manage revoke <client_name>"
            exit 1
        fi
        cd /etc/openvpn/easy-rsa/
        ./easyrsa revoke "$2"
        echo "Клиент $2 отозван"
        ;;
    list)
        ls /etc/openvpn/easy-rsa/pki/issued/ | grep -v server | sed 's/\.crt//g'
        ;;
    *)
        echo "Usage: vpn-manage {add|revoke|list} [client_name]"
        exit 1
        ;;
esac
EOF

chmod +x /usr/local/bin/vpn-manage

echo "=== Установка завершена! ==="
echo "Бот запущен как сервис: systemctl status vpnbot"
echo "Для управления клиентами используйте: vpn-manage {add|revoke|list}"
echo "Для тестирования отправьте боту команду: /test_payment"
