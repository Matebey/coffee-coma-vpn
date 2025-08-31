#!/bin/bash
echo "☕ Установка Master сервера Coffee Coma VPN"

apt update && apt upgrade -y
apt install -y git python3 python3-pip redis-server openssl

# Настройка Redis
sed -i 's/bind 127.0.0.1/bind 0.0.0.0/' /etc/redis/redis.conf
sed -i 's/protected-mode yes/protected-mode no/' /etc/redis/redis.conf

systemctl restart redis-server
systemctl enable redis-server

# Создание директорий
mkdir -p /etc/openvpn/client-configs/
mkdir -p /opt/coffee-coma-vpn

echo "✅ Master сервер настроен!"
echo "➡️ Не забудьте сгенерировать сертификаты и настроить config.yaml"