#!/bin/bash

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

INSTALL_DIR="/opt/coffee-coma-vpn"
DB_PATH="$INSTALL_DIR/vpn_bot.db"

show_menu() {
    echo -e "${GREEN}"
    echo "   ______          __           ______                 ________    ____"
    echo "  / ____/___  ____/ /_  _______/ ____/___  ____  _____/  _/   |  / __ \\"
    echo " / /   / __ \/ __  / / / / ___/ /   / __ \/ __ \/ ___// // /| | / /_/ /"
    echo "/ /___/ /_/ / /_/ / /_/ / /__/ /___/ /_/ / / / / /  _/ // ___ |/ ____/"
    echo "\____/\____/\__,_/\__,_/\___/\____/\____/_/ /_/_/  /___/_/  |_/_/"
    echo -e "${NC}"
    echo -e "${BLUE}=== Coffee Coma VPN Admin Panel ===${NC}"
    echo "1. 📊 Показать статистику"
    echo "2. 👥 Список пользователей"
    echo "3. 🔑 Управление ключами"
    echo "4. ⚙️  Настройки сервера"
    echo "5. 🔄 Перезапустить бота"
    echo "6. 🚪 Выход"
    echo -n "Выберите опцию: "
}

show_stats() {
    echo -e "${YELLOW}📊 Статистика системы:${NC}"
    users_count=$(sqlite3 $DB_PATH "SELECT COUNT(*) FROM users;")
    subs_count=$(sqlite3 $DB_PATH "SELECT COUNT(*) FROM subscriptions;")
    active_subs=$(sqlite3 $DB_PATH "SELECT COUNT(*) FROM subscriptions WHERE end_date > datetime('now');")
    
    echo -e "👥 Всего пользователей: ${GREEN}$users_count${NC}"
    echo -e "🔗 Всего подписок: ${GREEN}$subs_count${NC}"
    echo -e "✅ Активных подписок: ${GREEN}$active_subs${NC}"
    
    # Показываем использование диска
    echo -e "💾 Использование диска:"
    du -sh $INSTALL_DIR
    echo ""
}

list_users() {
    echo -e "${YELLOW}👥 Список пользователей:${NC}"
    sqlite3 -header -column $DB_PATH "SELECT user_id, username, first_name, registration_date FROM users ORDER BY registration_date DESC LIMIT 10;"
    echo ""
}

manage_keys() {
    echo -e "${YELLOW}🔑 Управление ключами:${NC}"
    sqlite3 -header -column $DB_PATH "SELECT client_name, user_id, start_date, end_date FROM subscriptions ORDER BY end_date DESC;"
    
    echo -n "Введите имя ключа для отзыва (или 'назад'): "
    read key_name
    
    if [ "$key_name" == "назад" ]; then
        return
    fi
    
    # Отзыв ключа
    cd /etc/openvpn/easy-rsa/
    echo "yes" | ./easyrsa revoke $key_name
    ./easyrsa gen-crl
    systemctl restart openvpn@server
    
    # Удаляем из базы
    sqlite3 $DB_PATH "DELETE FROM subscriptions WHERE client_name='$key_name';"
    
    echo -e "${GREEN}✅ Ключ $key_name отозван и удален!${NC}"
    echo ""
}

server_settings() {
    echo -e "${YELLOW}⚙️  Настройки сервера:${NC}"
    sqlite3 -header -column $DB_PATH "SELECT * FROM settings;"
    
    echo "1. Изменить DNS"
    echo "2. Изменить порт"
    echo "3. Изменить цену"
    echo "4. Назад"
    echo -n "Выберите опцию: "
    read option
    
    case $option in
        1)
            echo -n "Введите primary DNS: "
            read dns1
            echo -n "Введите secondary DNS: "
            read dns2
            sqlite3 $DB_PATH "UPDATE settings SET value='$dns1' WHERE key='dns1';"
            sqlite3 $DB_PATH "UPDATE settings SET value='$dns2' WHERE key='dns2';"
            echo -e "${GREEN}✅ DNS серверы обновлены!${NC}"
            ;;
        2)
            echo -n "Введите новый порт: "
            read port
            sqlite3 $DB_PATH "UPDATE settings SET value='$port' WHERE key='port';"
            echo -e "${GREEN}✅ Порт обновлен!${NC}"
            ;;
        3)
            echo -n "Введите новую цену: "
            read price
            sqlite3 $DB_PATH "UPDATE settings SET value='$price' WHERE key='price';"
            echo -e "${GREEN}✅ Цена обновлена!${NC}"
            ;;
    esac
    echo ""
}

while true; do
    show_menu
    read choice
    
    case $choice in
        1) show_stats ;;
        2) list_users ;;
        3) manage_keys ;;
        4) server_settings ;;
        5)
            systemctl restart coffee-coma-vpn
            echo -e "${GREEN}✅ Бот перезапущен!${NC}"
            ;;
        6) exit 0 ;;
        *) echo -e "${RED}Неверный выбор!${NC}" ;;
    esac
    
    echo -n "Нажмите Enter для продолжения..."
    read
    clear
done
