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
CONFIG_FILE="$INSTALL_DIR/config.py"
BOT_FILE="$INSTALL_DIR/vpn_bot.py"
SERVICE_FILE="/etc/systemd/system/coffee-coma-vpn.service"

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
apt install -y openvpn easy-rsa python3 python3-pip python3-venv git sqlite3 curl

# Создание директории
log "Создание рабочей директории..."
mkdir -p $INSTALL_DIR
cd $INSTALL_DIR

# Копирование файлов из текущей директории
log "Копирование файлов..."
cp -f /root/coffee-coma-vpn/*.py $INSTALL_DIR/
cp -f /root/coffee-coma-vpn/*.sh $INSTALL_DIR/
chmod +x $INSTALL_DIR/*.sh

# Настройка OpenVPN
log "Настройка OpenVPN сервера..."
cp -r /usr/share/easy-rsa/ /etc/openvpn/
cd /etc/openvpn/easy-rsa/

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
./easyrsa init-pki
echo -e "\n\n" | ./easyrsa build-ca nopass

# Генерируем серверный сертификат
./easyrsa gen-req server nopass
echo "yes" | ./easyrsa sign-req server server

# Генерируем DH параметры и TLS ключ
./easyrsa gen-dh
openvpn --genkey --secret pki/ta.key

# Создаем конфигурацию сервера
cat > /etc/openvpn/server.conf << EOF
port 1194
proto udp
dev tun
ca /etc/openvpn/easy-rsa/pki/ca.crt
cert /etc/openvpn/easy-rsa/pki/issued/server.crt
key /etc/openvpn/easy-rsa/pki/private/server.key
dh /etc/openvpn/easy-rsa/pki/dh.pem
server 10.8.0.0 255.255.255.0
push "redirect-gateway def1 bypass-dhcp"
push "dhcp-option DNS 8.8.8.8"
push "dhcp-option DNS 8.8.4.4"
keepalive 10 120
tls-auth /etc/openvpn/easy-rsa/pki/ta.key 0
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
iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o eth0 -j MASQUERADE
apt install -y iptables-persistent
iptables-save > /etc/iptables/rules.v4

# Создаем директорию для клиентских конфигов
mkdir -p /etc/openvpn/client-configs/

# Настройка Python окружения
log "Настройка Python окружения..."
cd $INSTALL_DIR
python3 -m venv venv
source venv/bin/activate
pip install python-telegram-bot requests

# Создаем базу данных
log "Создание базы данных..."
sqlite3 $INSTALL_DIR/vpn_bot.db "CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"
sqlite3 $INSTALL_DIR/vpn_bot.db "CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER PRIMARY KEY, client_name TEXT, config_path TEXT, start_date TIMESTAMP, end_date TIMESTAMP);"
sqlite3 $INSTALL_DIR/vpn_bot.db "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);"

# Добавляем настройки по умолчанию
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings VALUES ('dns1', '8.8.8.8');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings VALUES ('dns2', '8.8.4.4');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings VALUES ('port', '1194');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings VALUES ('price', '50');"

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
ExecStart=$INSTALL_DIR/venv/bin/python3 $BOT_FILE
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Даем права
chmod 644 $SERVICE_FILE
chmod +x $BOT_FILE
chmod +x $INSTALL_DIR/admin_panel.sh

# Запускаем сервисы
log "Запуск сервисов..."
systemctl daemon-reload
systemctl enable openvpn@server
systemctl start openvpn@server
systemctl enable coffee-coma-vpn
systemctl start coffee-coma-vpn

# Получаем IP сервера
SERVER_IP=$(curl -s ifconfig.me)

log "Установка завершена!"
echo -e "${YELLOW}=================================================${NC}"
echo -e "${GREEN}✅ OpenVPN сервер настроен и запущен${NC}"
echo -e "${GREEN}✅ Telegram бот установлен${NC}"
echo -e "${GREEN}✅ Systemd service создан${NC}"
echo -e "${YELLOW}=================================================${NC}"
echo -e "${BLUE}Следующие шаги:${NC}"
echo "1. Получите токен бота у @BotFather"
echo "2. Отредактируйте конфиг: nano $CONFIG_FILE"
echo "3. Укажите ваш Telegram ID в config.py"
echo "4. Перезапустите бота: systemctl restart coffee-coma-vpn"
echo -e "${YELLOW}=================================================${NC}"
echo -e "${GREEN}IP вашего сервера: $SERVER_IP${NC}"
echo -e "${GREEN}Порт OpenVPN: 1194${NC}"
echo -e "${YELLOW}=================================================${NC}"

# Проверяем статусы
echo -e "${BLUE}Статус сервисов:${NC}"
systemctl status openvpn@server --no-pager -l
echo ""
systemctl status coffee-coma-vpn --no-pager -l