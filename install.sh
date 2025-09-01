#!/bin/bash

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Функции для вывода сообщений
log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

echo -e "${GREEN}"
cat << "EOF"
   ______          __           ______                 ________    ____
  / ____/___  ____/ /_  _______/ ____/___  ____  _____/  _/   |  / __ \
 / /   / __ \/ __  / / / / ___/ /   / __ \/ __ \/ ___// // /| | / /_/ /
/ /___/ /_/ / /_/ / /_/ / /__/ /___/ /_/ / / / / /  _/ // ___ |/ ____/
\____/\____/\__,_/\__,_/\___/\____/\____/_/ /_/_/  /___/_/  |_/_/
EOF
echo -e "${NC}"
echo -e "${BLUE}=== Coffee Coma VPN Auto Installer ===${NC}"
echo -e "${CYAN}Начинается процесс установки...${NC}"

# Проверка на root
if [ "$EUID" -ne 0 ]; then
    error "Пожалуйста, запустите скрипт с правами root: sudo ./install.sh"
fi

# Переменные
INSTALL_DIR="/opt/coffee-coma-vpn"
SERVICE_FILE="/etc/systemd/system/coffee-coma-vpn.service"
EASYRSA_DIR="/etc/openvpn/easy-rsa"
OVPN_DIR="/etc/openvpn"
SERVER_CONF="$OVPN_DIR/server.conf"

# Определяем сетевой интерфейс по умолчанию
DEFAULT_INTERFACE=$(ip route | grep default | awk '{print $5}' | head -n1)
if [ -z "$DEFAULT_INTERFACE" ]; then
    DEFAULT_INTERFACE="eth0"
    warn "Не удалось определить сетевой интерфейс, используем '$DEFAULT_INTERFACE'"
fi

# Обновление системы
log "Обновление списка пакетов..."
apt-get update > /dev/null 2>&1 || warn "Не удалось обновить список пакетов"

log "Обновление системы (это может занять время)..."
apt-get upgrade -y > /dev/null 2>&1 || warn "Не удалось обновить пакеты"

# Установка необходимых пакетов
log "Установка необходимых пакетов..."
apt-get install -y openvpn easy-rsa python3 python3-pip python3-venv git sqlite3 curl iptables-persistent net-tools > /dev/null 2>&1 || error "Не удалось установить пакеты"

# Создание рабочей директории
log "Создание рабочей директории: $INSTALL_DIR"
mkdir -p $INSTALL_DIR
cd $INSTALL_DIR || error "Не удалось перейти в директорию $INSTALL_DIR"

# Копирование файлов (предполагается, что скрипт запускается из директории с файлами проекта)
log "Копирование файлов проекта..."
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
    cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR"/ > /dev/null 2>&1 || warn "Не удалось скопировать некоторые файлы"
fi
chmod +x $INSTALL_DIR/*.sh > /dev/null 2>&1

# Настройка OpenVPN и Easy-RSA
log "Настройка OpenVPN сервера..."

# Копируем easy-rsa в /etc/openvpn/
if [ -d "/usr/share/easy-rsa/" ]; then
    rm -rf $EASYRSA_DIR > /dev/null 2>&1
    cp -r /usr/share/easy-rsa/ $EASYRSA_DIR > /dev/null 2>&1 || error "Не удалось скопировать easy-rsa"
else
    error "Директория /usr/share/easy-rsa/ не найдена. Установите пакет easy-rsa."
fi

cd $EASYRSA_DIR || error "Не удалось перейти в $EASYRSA_DIR"

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

# Инициализируем PKI и генерируем CA
log "Инициализация PKI и генерация CA..."
./easyrsa --batch init-pki > /dev/null 2>&1 || error "Ошибка инициализации PKI"
./easyrsa --batch build-ca nopass > /dev/null 2>&1 || error "Ошибка генерации CA"

# Генерируем серверный сертификат
log "Генерация серверного сертификата..."
./easyrsa --batch gen-req server nopass > /dev/null 2>&1 || error "Ошибка генерации запроса сертификата"
./easyrsa --batch sign-req server server > /dev/null 2>&1 || error "Ошибка подписи сертификата"

# Генерируем DH параметры
log "Генерация DH параметров (это займет время)..."
./easyrsa --batch gen-dh > /dev/null 2>&1 || error "Ошибка генерации DH параметров"

# Генерируем TLS ключ
log "Генерация TLS ключа..."
openvpn --genkey --secret $EASYRSA_DIR/pki/ta.key > /dev/null 2>&1 || error "Ошибка генерации TLS ключа"

# Создаем конфигурацию сервера (ПРАВИЛЬНАЯ ВЕРСИЯ)
log "Создание конфигурации OpenVPN сервера..."
cat > $SERVER_CONF << EOF
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
tls-crypt $EASYRSA_DIR/pki/ta.key
cipher AES-256-CBC
auth SHA256
user nobody
group nogroup
persist-key
persist-tun
status /var/log/openvpn-status.log
log /var/log/openvpn.log
verb 3
explicit-exit-notify 1
EOF

# Включаем IP forwarding
log "Включение IP forwarding..."
sed -i '/net.ipv4.ip_forward=1/d' /etc/sysctl.conf
echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
sysctl -p > /dev/null 2>&1

# Настраиваем iptables
log "Настройка iptables..."
iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o $DEFAULT_INTERFACE -j MASQUERADE

# Сохраняем правила iptables
log "Сохранение правил iptables..."
mkdir -p /etc/iptables/
iptables-save > /etc/iptables/rules.v4

# Создаем директорию для клиентских конфигов
mkdir -p /etc/openvpn/client-configs/

# Настройка Python окружения
log "Настройка Python окружения..."
cd $INSTALL_DIR || error "Не удалось перейти в $INSTALL_DIR"
python3 -m venv venv > /dev/null 2>&1 || error "Ошибка создания виртуального окружения"
source venv/bin/activate

# Устанавливаем зависимости Python
if [ -f "requirements.txt" ]; then
    log "Установка зависимых Python пакетов из requirements.txt..."
    pip install -r requirements.txt > /dev/null 2>&1 || warn "Не удалось установить некоторые зависимости"
else
    log "Установка основных Python пакетов..."
    pip install python-telegram-bot requests > /dev/null 2>&1 || warn "Не удалось установить некоторые зависимости"
fi

# Создаем базу данных
log "Создание и настройка базы данных..."
sqlite3 $INSTALL_DIR/vpn_bot.db "CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, referral_code TEXT UNIQUE, referred_by INTEGER, trial_used INTEGER DEFAULT 0);" || error "Ошибка создания таблицы users"
sqlite3 $INSTALL_DIR/vpn_bot.db "CREATE TABLE IF NOT EXISTS subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, client_name TEXT UNIQUE, config_path TEXT, start_date TIMESTAMP, end_date TIMESTAMP, speed_limit INTEGER DEFAULT 10, is_trial INTEGER DEFAULT 0, FOREIGN KEY (user_id) REFERENCES users (user_id));" || error "Ошибка создания таблицы subscriptions"
sqlite3 $INSTALL_DIR/vpn_bot.db "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);" || error "Ошибка создания таблицы settings"
sqlite3 $INSTALL_DIR/vpn_bot.db "CREATE TABLE IF NOT EXISTS referrals (referral_id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER, referred_id INTEGER, reward_claimed INTEGER DEFAULT 0, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (referrer_id) REFERENCES users (user_id), FOREIGN KEY (referred_id) REFERENCES users (user_id));" || error "Ошибка создания таблицы referrals"

# Добавляем настройки по умолчанию
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings (key, value) VALUES ('dns1', '8.8.8.8');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings (key, value) VALUES ('dns2', '8.8.4.4');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings (key, value) VALUES ('port', '1194');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings (key, value) VALUES ('price', '50');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings (key, value) VALUES ('speed_limit', '10');"
sqlite3 $INSTALL_DIR/vpn_bot.db "INSERT OR IGNORE INTO settings (key, value) VALUES ('yoomoney_wallet', '4100117852673007');"

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
chmod +x $INSTALL_DIR/*.sh > /dev/null 2>&1

# Создаем симлинки для удобства
ln -sf $INSTALL_DIR/admin_panel.sh /usr/local/bin/vpn-admin
ln -sf $INSTALL_DIR/reinstall.sh /usr/local/bin/vpn-reinstall
ln -sf $INSTALL_DIR/update.sh /usr/local/bin/vpn-update
chmod +x /usr/local/bin/vpn-*

# Запускаем сервисы
log "Запуск сервисов..."
systemctl daemon-reload
systemctl enable openvpn > /dev/null 2>&1
systemctl start openvpn > /dev/null 2>&1
systemctl enable coffee-coma-vpn > /dev/null 2>&1
systemctl start coffee-coma-vpn

# Проверяем статус OpenVPN
if systemctl is-active --quiet openvpn; then
    log "OpenVPN сервер успешно запущен"
else
    warn "OpenVPN сервер не запустился. Проверьте конфигурацию: $SERVER_CONF"
fi

# Проверяем статус бота
if systemctl is-active --quiet coffee-coma-vpn; then
    log "Telegram бот успешно запущен"
else
    warn "Telegram бот не запустился. Проверьте конфигурацию."
fi

# Получаем IP сервера
SERVER_IP=$(curl -s -4 ifconfig.me || hostname -I | awk '{print $1}' | head -n1)

log "Установка завершена!"
echo -e "${YELLOW}=================================================${NC}"
echo -e "${GREEN}✅ OpenVPN сервер настроен и запущен${NC}"
echo -e "${GREEN}✅ Telegram бот установлен${NC}"
echo -e "${GREEN}✅ Systemd service создан${NC}"
echo -e "${YELLOW}=================================================${NC}"
echo -e "${BLUE}Следующие шаги:${NC}"
echo "1. Отредактируйте конфиг: nano $INSTALL_DIR/config.py"
echo "2. Укажите ваш Telegram ID и токен бота"
echo "3. Перезапустите бота: systemctl restart coffee-coma-vpn"
echo -e "${YELLOW}=================================================${NC}"
echo -e "${GREEN}IP вашего сервера: $SERVER_IP${NC}"
echo -e "${GREEN}Порт OpenVPN: 1194${NC}"
echo -e "${GREEN}Сетевой интерфейс: $DEFAULT_INTERFACE${NC}"
echo -e "${YELLOW}=================================================${NC}"

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

echo -e "${CYAN}"
echo "Проверьте статус сервисов:"
echo "  systemctl status openvpn"
echo "  systemctl status coffee-coma-vpn"
echo -e "${NC}"
