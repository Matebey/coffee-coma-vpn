#!/bin/bash
echo "☕ Установка Slave сервера Coffee Coma VPN"

apt update && apt upgrade -y
apt install -y openvpn easy-rsa ufw iproute2

mkdir -p /etc/openvpn/scripts/

ufw allow OpenSSH
ufw allow 1194/udp
ufw --force enable

echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -p

echo "✅ Slave сервер готов!"
echo "➡️ Скопируйте сертификаты и скрипты с Master сервера"