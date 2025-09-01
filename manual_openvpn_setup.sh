#!/bin/bash

echo "🛠 Ручная настройка OpenVPN..."

# Останавливаем сервис
systemctl stop openvpn-server@server.service

# Пересоздаем сертификаты
cd /etc/openvpn/easy-rsa/

# Очищаем старые файлы
rm -f ta.key
rm -f pki/issued/server.crt
rm -f pki/private/server.key

# Создаем новые сертификаты
./easyrsa --batch gen-req server nopass
./easyrsa --batch sign-req server server
openvpn --genkey --secret ta.key

# Копируем файлы в правильные места
cp ta.key /etc/openvpn/
cp pki/ca.crt /etc/openvpn/
cp pki/private/server.key /etc/openvpn/
cp pki/issued/server.crt /etc/openvpn/
cp pki/dh.pem /etc/openvpn/

# Исправляем конфиг
cat > /etc/openvpn/server.conf << 'EOF'
port 1194
proto udp
dev tun
ca /etc/openvpn/ca.crt
cert /etc/openvpn/server.crt
key /etc/openvpn/server.key
dh /etc/openvpn/dh.pem
server 10.8.0.0 255.255.255.0
push "redirect-gateway def1 bypass-dhcp"
push "dhcp-option DNS 8.8.8.8"
push "dhcp-option DNS 8.8.4.4"
keepalive 10 120
tls-auth /etc/openvpn/ta.key 0
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

# Правим права доступа
chmod 644 /etc/openvpn/*.crt
chmod 644 /etc/openvpn/*.key
chmod 644 /etc/openvpn/*.pem

# Запускаем сервис
systemctl start openvpn-server@server.service
systemctl status openvpn-server@server.service --no-pager -l

echo "✅ Ручная настройка завершена"