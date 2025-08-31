#!/bin/bash
echo "☕ Автоматическая установка Coffee Coma VPN"

# Обновление системы
apt update && apt upgrade -y

# Установка необходимых пакетов
apt install -y git python3 python3-pip python3.12-venv redis-server openssl easy-rsa

# Настройка Redis
sed -i 's/bind 127.0.0.1/bind 0.0.0.0/' /etc/redis/redis.conf
sed -i 's/protected-mode yes/protected-mode no/' /etc/redis/redis.conf
systemctl restart redis-server
systemctl enable redis-server

# Создание директорий
mkdir -p /opt/coffee-coma-vpn
mkdir -p /etc/openvpn/client-configs/

# Переход в директорию
cd /opt/coffee-coma-vpn

# Создание виртуального окружения
python3 -m venv venv
source venv/bin/activate

# Установка Python зависимостей
pip install --break-system-packages "python-telegram-bot==20.7"
pip install --break-system-packages pyyaml redis requests python-dateutil

echo "✅ Установка завершена!"
echo "➡️ Не забудьте настроить config.yaml и сгенерировать сертификаты"