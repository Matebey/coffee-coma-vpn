#!/bin/bash
echo "Админ-панель Coffee Coma VPN"
echo "1. Статус сервисов"
echo "2. Перезапустить бота"
echo "3. Остановить бота"
echo "4. Показать логи"
read -p "Выберите: " choice

case $choice in
    1) systemctl status coffee-coma-vpn.service ;;
    2) systemctl restart coffee-coma-vpn.service ;;
    3) systemctl stop coffee-coma-vpn.service ;;
    4) journalctl -u coffee-coma-vpn.service -f ;;
    *) echo "Неверный выбор" ;;
esac