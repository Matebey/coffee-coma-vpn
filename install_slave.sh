#!/bin/bash
echo "☕ Установка SLAVE сервера Coffee Coma VPN"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}1. Обновление системы...${NC}"
apt update && apt upgrade -y

echo -e "${YELLOW}2. Установка пакетов...${NC}"
apt install -y openvpn easy-rsa ufw iproute2 sshpass

echo -e "${YELLOW}3. Настройка firewall...${NC}"
ufw allow OpenSSH
ufw allow 1194/udp
ufw --force enable

echo -e "${YELLOW}4. Включение IP forwarding...${NC}"
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -p

echo -e "${YELLOW}5. Создание директорий...${NC}"
mkdir -p /etc/openvpn/scripts/

echo -e "${YELLOW}6. Копирование сертификатов с MASTER...${NC}"
MASTER_IP="77.239.105.14"
scp root@$MASTER_IP:/etc/openvpn/* /etc/openvpn/

echo -e "${YELLOW}7. Копирование скриптов...${NC}"
scp root@$MASTER_IP:/opt/coffee-coma-vpn/traffic_control.sh /etc/openvpn/scripts/
scp root@$MASTER_IP:/opt/coffee-coma-vpn/client-connect.sh /etc/openvpn/scripts/
scp root@$MASTER_IP:/opt/coffee-coma-vpn/client-disconnect.sh /etc/openvpn/scripts/
chmod +x /etc/openvpn/scripts/*.sh

echo -e "${YELLOW}8. Настройка OpenVPN...${NC}"
cp /usr/share/doc/openvpn/examples/sample-config-files/server.conf /etc/openvpn/

echo "script-security 2" >> /etc/openvpn/server.conf
echo "client-connect /etc/openvpn/scripts/client-connect.sh" >> /etc/openvpn/server.conf
echo "client-disconnect /etc/openvpn/scripts/client-disconnect.sh" >> /etc/openvpn/server.conf

echo -e "${YELLOW}9. Запуск OpenVPN...${NC}"
systemctl enable openvpn@server
systemctl start openvpn@server

echo -e "${GREEN}✅ SLAVE сервер установлен!${NC}"