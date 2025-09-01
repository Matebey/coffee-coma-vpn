#!/bin/bash

echo "🔍 Диагностика OpenVPN..."
echo ""

# Проверяем сервис
echo "📋 Статус сервиса:"
systemctl status openvpn-server@server.service --no-pager -l

echo ""
echo "📋 Логи OpenVPN:"
journalctl -u openvpn-server@server.service -n 20 --no-pager

echo ""
echo "📋 Проверка файлов:"
ls -la /etc/openvpn/easy-rsa/pki/private/server.key
ls -la /etc/openvpn/easy-rsa/pki/issued/server.crt
ls -la /etc/openvpn/easy-rsa/pki/ca.crt
ls -la /etc/openvpn/easy-rsa/pki/dh.pem
ls -la /etc/openvpn/easy-rsa/ta.key

echo ""
echo "📋 Проверка конфига:"
cat /etc/openvpn/server.conf | grep -E "^(ca|cert|key|dh|tls-crypt)"

echo ""
echo "🔧 Исправление прав доступа..."
chmod 644 /etc/openvpn/easy-rsa/pki/private/server.key
chmod 644 /etc/openvpn/easy-rsa/pki/issued/server.crt
chmod 644 /etc/openvpn/easy-rsa/pki/ca.crt
chmod 644 /etc/openvpn/easy-rsa/pki/dh.pem
chmod 644 /etc/openvpn/easy-rsa/ta.key

echo "✅ Права доступа исправлены"