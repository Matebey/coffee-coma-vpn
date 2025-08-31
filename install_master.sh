#!/bin/bash
echo "☕ Установка MASTER сервера Coffee Coma VPN"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}1. Обновление системы...${NC}"
apt update && apt upgrade -y

echo -e "${YELLOW}2. Установка пакетов...${NC}"
apt install -y git python3 python3-pip python3.12-venv redis-server openssl easy-rsa

echo -e "${YELLOW}3. Настройка Redis...${NC}"
sed -i 's/bind 127.0.0.1/bind 0.0.0.0/' /etc/redis/redis.conf
sed -i 's/protected-mode yes/protected-mode no/' /etc/redis/redis.conf
systemctl restart redis-server
systemctl enable redis-server

echo -e "${YELLOW}4. Клонирование репозитория...${NC}"
cd /opt
git clone https://github.com/Matebey/coffee-coma-vpn.git
cd coffee-coma-vpn

echo -e "${YELLOW}5. Создание виртуального окружения...${NC}"
python3 -m venv venv
source venv/bin/activate

echo -e "${YELLOW}6. Установка зависимостей...${NC}"
pip install --break-system-packages "python-telegram-bot==20.7"
pip install --break-system-packages pyyaml redis requests python-dateutil

echo -e "${YELLOW}7. Создание директорий...${NC}"
mkdir -p /etc/openvpn/client-configs/

echo -e "${YELLOW}8. Генерация сертификатов...${NC}"
make-cadir ~/openvpn-ca
cd ~/openvpn-ca

cat > vars << 'EOF'
export KEY_COUNTRY="RU"
export KEY_PROVINCE="Moscow"
export KEY_CITY="Moscow"
export KEY_ORG="Coffee Coma VPN"
export KEY_EMAIL="admin@coffeecoma.vpn"
export KEY_OU="IT"
export KEY_NAME="server"
EOF

source vars
./clean-all
echo -e "\n\n\n\n\n\n\n" | ./build-ca
echo -e "\n\n\n\n\n\n\n" | ./build-key-server server
./build-dh
openvpn --genkey secret ta.key

cp pki/ca.crt pki/issued/server.crt pki/private/server.key pki/dh.pem ta.key /etc/openvpn/

echo -e "${GREEN}✅ MASTER сервер установлен!${NC}"
echo -e "${YELLOW}Запустите ботов:${NC}"
echo -e "cd /opt/coffee-coma-vpn && source venv/bin/activate"
echo -e "nohup python3 main.py > bot.log 2>&1 &"
echo -e "nohup python3 admin.py > admin.log 2>&1 &"