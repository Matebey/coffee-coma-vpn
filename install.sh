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
echo " / /   / __ \/ __  / / / / ___/ /   / __ \/ __ \/ ___// / /| | / /_/ /"
echo "/ /___/ /_/ / /_/ / /_/ / /__/ /___/ /_/ / / / / /  / / ___ |/ ____/"
echo "\____/\____/\__,_/\__,_/\___/\____/\____/_/ /_/_/  /_/_/  |_/_/"
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
BOT_TOKEN="7953514140:AAGg-AgyL6Y2mvzfyKesnpouJkU6p_B8Zeo"
ADMIN_ID="5631675412"
SERVER_IP="77.239.105.17"

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
apt install -y openvpn easy-rsa python3 python3-pip python3-venv git sqlite3 curl iptables-persistent

# Создание директории
log "Создание рабочей директории..."
mkdir -p $INSTALL_DIR
cd $INSTALL_DIR

# Клонирование репозитория
log "Клонирование репозитория..."
git clone https://github.com/Matebey/coffee-coma-vpn.git .
chmod +x *.sh

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
iptables -A INPUT -p udp --dport 1194 -j ACCEPT
iptables -A FORWARD -s 10.8.0.0/24 -j ACCEPT
iptables -A FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables-save > /etc/iptables/rules.v4

# Создаем директорию для клиентских конфигов
mkdir -p /etc/openvpn/client-configs/

# Настройка Python окружения
log "Настройка Python окружения..."
cd $INSTALL_DIR
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Создаем базу данных
log "Создание базы данных..."
sqlite3 $INSTALL_DIR/vpn_bot.db "CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, referral_code TEXT UNIQUE, referred_by INTEGER, trial_used INTEGER DEFAULT 0);"
sqlite3 $INSTALL_DIR/vpn_bot.db "CREATE TABLE IF NOT EXISTS subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, client_name TEXT UNIQUE, config_path TEXT, start_date TIMESTAMP, end_date TIMESTAMP, speed_limit INTEGER DEFAULT 10, is_trial INTEGER DEFAULT 0);"
sqlite3 $INSTALL_DIR/vpn_bot.db "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);"
sqlite3 $INSTALL_DIR/vpn_bot.db "CREATE TABLE IF NOT EXISTS referrals (referral_id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER, referred_id INTEGER, reward_claimed INTEGER DEFAULT 0, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"

# Добавляем настройки по умолчанию
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings VALUES ('dns1', '8.8.8.8');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings VALUES ('dns2', '8.8.4.4');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings VALUES ('port', '1194');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings VALUES ('price', '50');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings VALUES ('speed_limit', '10');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings VALUES ('yoomoney_wallet', '4100117852673007');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings VALUES ('yoomoney_token', '');"

# Обновляем конфиг бота с вашими настройками
sed -i "s/BOT_TOKEN = \"ВАШ_ТОКЕН_БОТА\"/BOT_TOKEN = \"$BOT_TOKEN\"/g" vpn_bot.py
sed -i "s/ADMINS = \[ВАШ_TELEGRAM_ID\]/ADMINS = [$ADMIN_ID]/g" vpn_bot.py

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
systemctl enable openvpn@server
systemctl start openvpn@server
systemctl enable coffee-coma-vpn
systemctl start coffee-coma-vpn

# Создаем директорию для скриптов ограничения скорости
mkdir -p /etc/openvpn/client-speed/

# Добавляем задание cron для очистки просроченных подписок
(crontab -l 2>/dev/null; echo "0 3 * * * $INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/cleanup_expired.py") | crontab -

log "Установка завершена!"
echo -e "${YELLOW}=================================================${NC}"
echo -e "${GREEN}✅ OpenVPN сервер настроен и запущен${NC}"
echo -e "${GREEN}✅ Telegram бот установлен${NC}"
echo -e "${GREEN}✅ Systemd service создан${NC}"
echo -e "${YELLOW}=================================================${NC}"
echo -e "${BLUE}Следующие шаги:${NC}"
echo "1. Проверьте статус бота: systemctl status coffee-coma-vpn"
echo "2. Используйте админ панель: vpn-admin"
echo "3. Настройте ЮMoney в админ-панели бота"
echo -e "${YELLOW}=================================================${NC}"
echo -e "${GREEN}IP вашего сервера: $SERVER_IP${NC}"
echo -e "${GREEN}Порт OpenVPN: 1194${NC}"
echo -e "${YELLOW}=================================================${NC}"

# Проверяем статусы
echo -e "${BLUE}Статус сервисов:${NC}"
systemctl status openvpn@server --no-pager -l
echo ""
systemctl status coffee-coma-vpn --no-pager -l
