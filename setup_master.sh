#!/bin/bash
echo "☕ Установка Master сервера Coffee Coma VPN"

apt update && apt upgrade -y
apt install -y git python3 python3-pip redis-server

sed -i 's/bind 127.0.0.1/bind 0.0.0.0/' /etc/redis/redis.conf
sed -i 's/protected-mode yes/protected-mode no/' /etc/redis/redis.conf

systemctl restart redis
systemctl enable redis

cd /opt
git clone https://github.com/ВАШ_ЛОГИН/coffee-coma-vpn.git
cd coffee-coma-vpn

pip3 install -r requirements.txt

mkdir -p /etc/openvpn/client-configs/

echo "✅ Master сервер настроен!"
echo "➡️ Отредактируйте config.yaml и настройте сертификаты"