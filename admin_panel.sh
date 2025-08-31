#!/bin/bash

# Coffee Coma VPN Admin Panel

CONFIG_FILE="/opt/coffee-coma-vpn/config.py"
DB_FILE="/opt/coffee-coma-vpn/vpn_bot.db"

echo "Coffee Coma VPN Admin Panel"
echo "============================"

case "$1" in
    change-dns)
        if [ -z "$2" ] || [ -z "$3" ]; then
            echo "Usage: $0 change-dns <dns1> <dns2>"
            exit 1
        fi
        sqlite3 $DB_FILE "UPDATE settings SET value='$2' WHERE key='dns1';"
        sqlite3 $DB_FILE "UPDATE settings SET value='$3' WHERE key='dns2';"
        echo "DNS серверы изменены: $2, $3"
        systemctl restart coffee-coma-vpn
        ;;
    change-port)
        if [ -z "$2" ]; then
            echo "Usage: $0 change-port <port>"
            exit 1
        fi
        sqlite3 $DB_FILE "UPDATE settings SET value='$2' WHERE key='port';"
        echo "Порт изменен: $2"
        systemctl restart coffee-coma-vpn
        ;;
    change-price)
        if [ -z "$2" ]; then
            echo "Usage: $0 change-price <price>"
            exit 1
        fi
        sqlite3 $DB_FILE "UPDATE settings SET value='$2' WHERE key='price';"
        echo "Цена изменена: $2 руб"
        systemctl restart coffee-coma-vpn
        ;;
    stats)
        echo "Статистика:"
        sqlite3 $DB_FILE "SELECT COUNT(*) as 'Пользователей' FROM users;"
        sqlite3 $DB_FILE "SELECT COUNT(*) as 'Активных подписок' FROM subscriptions;"
        ;;
    *)
        echo "Доступные команды:"
        echo "  change-dns <dns1> <dns2>  - Изменить DNS серверы"
        echo "  change-port <port>        - Изменить порт OpenVPN"
        echo "  change-price <price>      - Изменить цену подписки"
        echo "  stats                     - Показать статистику"
        ;;
esac