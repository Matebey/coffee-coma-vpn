#!/bin/bash
echo "☕ Установка Coffee Coma VPN Master Server"

# Обновление системы
apt update && apt upgrade -y

# Установка зависимостей
apt install -y git python3 python3-pip redis-server

# Настройка Redis
sed -i 's/bind 127.0.0.1/bind 0.0.0.0/' /etc/redis/redis.conf
echo "protected-mode no" >> /etc/redis/redis.conf
systemctl restart redis
systemctl enable redis

# Установка Python зависимостей
pip3 install python-telegram-bot pyyaml redis python-dateutil requests

# Создание директорий
mkdir -p /etc/openvpn/client-configs/
mkdir -p /opt/coffee-coma-vpn

echo "✅ Master сервер настроен!"
echo "➡️ Далее: Настройте config.yaml и запустите бота"