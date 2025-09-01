#!/bin/bash

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}"
echo "   ______          __           ______                 ________    ____"
echo "  / ____/___  ____/ /_  _______/ ____/___  ____  _____/  _/   |  / __ \\"
echo " / /   / __ \/ __  / / / / ___/ /   / __ \/ __ \/ ___// // /| | / /_/ /"
echo "/ /___/ /_/ / /_/ / /_/ / /__/ /___/ /_/ / / / / /  _/ // ___ |/ ____/"
echo "\____/\____/\__,_/\__,_/\___/\____/\____/_/ /_/_/  /___/_/  |_/_/"
echo -e "${NC}"
echo -e "${BLUE}=== Coffee Coma VPN Auto Installer ===${NC}"

# Проверка на root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Пожалуйста, запустите скрипт с правами root: sudo ./install.sh${NC}"
    exit 1
fi

# Переменные
INSTALL_DIR="/opt/coffee-coma-vpn"
SERVICE_FILE="/etc/systemd/system/coffee-coma-vpn.service"
EASYRSA_DIR="/etc/openvpn/easy-rsa"

# Функция для вывода сообщений
log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# Обновление системы
log "Обновление системы..."
apt update && apt upgrade -y

# Установка необходимых пакетов
log "Установка пакетов..."
apt install -y openvpn easy-rsa python3 python3-pip python3-venv git sqlite3 curl iptables-persistent net-tools

# Создание директории
log "Создание рабочей директории..."
mkdir -p $INSTALL_DIR
cd $INSTALL_DIR

# Клонирование репозитория или копирование файлов
if [ -d "/root/coffee-coma-vpn" ]; then
    log "Копирование файлов из локальной директории..."
    cp -rf /root/coffee-coma-vpn/* $INSTALL_DIR/
else
    log "Скачивание файлов с GitHub..."
    git clone https://github.com/your-repo/coffee-coma-vpn.git .
fi

chmod +x $INSTALL_DIR/*.sh

# Настройка OpenVPN
log "Настройка OpenVPN сервера..."

# Проверяем существование easy-rsa и копируем если нужно
if [ ! -d "/usr/share/easy-rsa/" ]; then
    error "Easy-RSA не установлена. Проверьте установку пакета easy-rsa."
    exit 1
fi

if [ ! -d "$EASYRSA_DIR" ]; then
    cp -r /usr/share/easy-rsa/ $EASYRSA_DIR
fi

cd $EASYRSA_DIR

# Создаем файл vars
cat > vars << EOF
set_var EASYRSA_REQ_COUNTRY    "RU"
set_var EASYRSA_REQ_PROVINCE   "Moscow"
set_var EASYRSA_REQ_CITY       "Moscow"
set_var EASYRSA_REQ_ORG        "CoffeeComaVPN"
set_var EASYRSA_REQ_EMAIL      "admin@coffeecoma.vpn"
set_var EASYRSA_REQ_OU         "VPN"
set_var EASYRSA_KEY_SIZE       2048
set_var EASYRSA_ALGO           rsa
set_var EASYRSA_CA_EXPIRE      3650
set_var EASYRSA_CERT_EXPIRE    365
set_var EASYRSA_CRL_DAYS       180
EOF

# Инициализируем PKI
./easyrsa --batch init-pki
./easyrsa --batch build-ca nopass

# Генерируем серверный сертификат
./easyrsa --batch gen-req server nopass
./easyrsa --batch sign-req server server

# Генерируем DH параметры и TLS ключ
./easyrsa --batch gen-dh
openvpn --genkey --secret pki/ta.key

# Создаем конфигурацию сервера
cat > /etc/openvpn/server.conf << EOF
port 1194
proto udp
dev tun
ca $EASYRSA_DIR/pki/ca.crt
cert $EASYRSA_DIR/pki/issued/server.crt
key $EASYRSA_DIR/pki/private/server.key
dh $EASYRSA_DIR/pki/dh.pem
server 10.8.0.0 255.255.255.0
push "redirect-gateway def1 bypass-dhcp"
push "dhcp-option DNS 8.8.8.8"
push "dhcp-option DNS 8.8.4.4"
keepalive 10 120
tls-auth $EASYRSA_DIR/pki/ta.key 0
cipher AES-256-CBC
auth SHA256
user nobody
group nogroup
persist-key
persist-tun
status /var/log/openvpn-status.log
verb 3
explicit-exit-notify 1
EOF

# Включаем IP forwarding
echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
sysctl -p

# Настраиваем iptables
# Определяем сетевой интерфейс
NET_INTERFACE=$(ip route | grep default | awk '{print $5}' | head -n1)
if [ -z "$NET_INTERFACE" ]; then
    NET_INTERFACE="eth0"
fi

iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o $NET_INTERFACE -j MASQUERADE

# Сохраняем правила iptables
mkdir -p /etc/iptables/
iptables-save > /etc/iptables/rules.v4

# Создаем директорию для клиентских конфигов
mkdir -p /etc/openvpn/client-configs/

# Настройка Python окружения
log "Настройка Python окружения..."
cd $INSTALL_DIR
python3 -m venv venv
source venv/bin/activate

# Проверяем существование requirements.txt
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    # Устанавливаем основные зависимости если файла нет
    pip install python-telegram-bot sqlite3 python-dateutil requests
fi

# Создаем базу данных
log "Создание базы данных..."
sqlite3 $INSTALL_DIR/vpn_bot.db "CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, referral_code TEXT UNIQUE, referred_by INTEGER, trial_used INTEGER DEFAULT 0);"
sqlite3 $INSTALL_DIR/vpn_bot.db "CREATE TABLE IF NOT EXISTS subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, client_name TEXT UNIQUE, config_path TEXT, start_date TIMESTAMP, end_date TIMESTAMP, speed_limit INTEGER DEFAULT 10, is_trial INTEGER DEFAULT 0, FOREIGN KEY (user_id) REFERENCES users (user_id));"
sqlite3 $INSTALL_DIR/vpn_bot.db "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);"
sqlite3 $INSTALL_DIR/vpn_bot.db "CREATE TABLE IF NOT EXISTS referrals (referral_id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER, referred_id INTEGER, reward_claimed INTEGER DEFAULT 0, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (referrer_id) REFERENCES users (user_id), FOREIGN KEY (referred_id) REFERENCES users (user_id));"

# Добавляем настройки по умолчанию
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings VALUES ('dns1', '8.8.8.8');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings VALUES ('dns2', '8.8.4.4');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings VALUES ('port', '1194');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings VALUES ('price', '50');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings VALUES ('speed_limit', '10');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings VALUES ('yoomoney_wallet', '4100117852673007');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings VALUES ('cloudtips_token', 'ВАШ_CLOUDTIPS_TOKEN');"

# Создаем service файл
log "Создание systemd service..."
cat > $SERVICE_FILE << EOF
[Unit]
Description=Coffee Coma VPN Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment=PATH=$INSTALL_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/vpn_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Даем права
chmod 644 $SERVICE_FILE
chmod +x $INSTALL_DIR/*.sh

# Создаем симлинки для удобства
ln -sf $INSTALL_DIR/admin_panel.sh /usr/local/bin/vpn-admin
ln -sf $INSTALL_DIR/reinstall.sh /usr/local/bin/vpn-reinstall
ln -sf $INSTALL_DIR/update.sh /usr/local/bin/vpn-update
chmod +x /usr/local/bin/vpn-*

# Запускаем сервисы
log "Запуск сервисов..."
systemctl daemon-reload
systemctl enable openvpn-server@server.service
systemctl start openvpn-server@server.service
systemctl enable coffee-coma-vpn
systemctl start coffee-coma-vpn

# Проверяем статус OpenVPN
if systemctl is-active --quiet openvpn-server@server.service; then
    log "OpenVPN сервер успешно запущен"
else
    error "OpenVPN сервер не запустился. Проверьте конфигурацию."
fi

# Получаем IP сервера
SERVER_IP=$(curl -s ifconfig.me || hostname -I | awk '{print $1}')

log "Установка завершена!"
echo -e "${YELLOW}=================================================${NC}"
echo -e "${GREEN}✅ OpenVPN сервер настроен и запущен${NC}"
echo -e "${GREEN}✅ Telegram бот установлен${NC}"
echo -e "${GREEN}✅ Systemd service создан${NC}"
echo -e "${YELLOW}=================================================${NC}"
echo -e "${BLUE}Следующие шаги:${NC}"
echo "1. Отредактируйте конфиг: nano /opt/coffee-coma-vpn/config.py"
echo "2. Укажите ваш Telegram ID и токен бота"
echo "3. Перезапустите бота: systemctl restart coffee-coma-vpn"
echo -e "${YELLOW}=================================================${NC}"
echo -e "${GREEN}IP вашего сервера: $SERVER_IP${NC}"
echo -e "${GREEN}Порт OpenVPN: 1194${NC}"
echo -e "${YELLOW}=================================================${NC}"

# Проверяем статусы
echo -e "${BLUE}Статус сервисов:${NC}"
systemctl status openvpn-server@server.service --no-pager -l
echo ""
systemctl status coffee-coma-vpn --no-pager -l

# Создаем базовый конфиг файл если его нет
if [ ! -f "$INSTALL_DIR/config.py" ]; then
    cat > $INSTALL_DIR/config.py << EOF
# Конфигурация Coffee Coma VPN Bot
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
ADMIN_ID = YOUR_ADMIN_ID
DATABASE_PATH = "$INSTALL_DIR/vpn_bot.db"
EOF
    log "Создан базовый config.py. Не забудьте настроить его!"
fi

log "Для управления используйте команды:"
echo "  vpn-admin    - Панель администратора"
echo "  vpn-reinstall - Переустановка системы"
echo "  vpn-update   - Обновление системы"
