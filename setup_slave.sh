#!/bin/bash
echo "☕ Установка Slave сервера Coffee Coma VPN"

apt update && apt upgrade -y
apt install -y openvpn easy-rsa ufw iproute2 sshpass

# Настройка firewall
ufw allow OpenSSH
ufw allow 1194/udp
ufw --force enable

# Включение IP forwarding
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -p

# Создание директорий для скриптов
mkdir -p /etc/openvpn/scripts/

echo "✅ Slave сервер готов!"
echo "➡️ Скопируйте сертификаты и скрипты с Master сервера"