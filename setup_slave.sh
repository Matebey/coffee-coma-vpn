#!/bin/bash
echo "☕ Установка Coffee Coma VPN Slave Server"

# Обновление системы
apt update && apt upgrade -y

# Установка OpenVPN
apt install -y openvpn easy-rsa

# Настройка OpenVPN
make-cadir ~/openvpn-ca
cd ~/openvpn-ca

# Копирование сертификатов (выполнить после генерации на Master)
echo "➡️ Скопируйте сертификаты с Master сервера:"
echo "scp root@master_ip:/etc/openvpn/* /etc/openvpn/"

systemctl enable openvpn@server
systemctl start openvpn@server

# Включение IP forwarding
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -p

# Настройка firewall
ufw allow OpenSSH
ufw allow 1194/udp
ufw enable

echo "✅ Slave сервер настроен!"