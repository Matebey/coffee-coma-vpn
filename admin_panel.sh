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
    echo ""
    echo "1. 📊 Показать статистику"
    echo "2. 👥 Список пользователей"
    echo "3. 🔧 Управление подписками"
    echo "4. ⚙️  Настройки системы"
    echo "5. 🔄 Перезапустить сервисы"
    echo "6. 📝 Редактировать конфиг"
    echo "7. 🚪 Выход"
    echo ""
}

show_stats() {
    echo -e "${YELLOW}📊 Статистика системы:${NC}"
    sqlite3 $DB_PATH "SELECT COUNT(*) FROM users" | read total_users
    sqlite3 $DB_PATH "SELECT COUNT(*) FROM subscriptions WHERE end_date > datetime('now')" | read active_subs
    sqlite3 $DB_PATH "SELECT COUNT(*) FROM referrals" | read total_refs
    
    echo "• Всего пользователей: $total_users"
    echo "• Активных подписок: $active_subs"
    echo "• Всего рефералов: $total_refs"
    echo ""
    
    # Информация о системе
    echo -e "${YELLOW}💻 Загрузка системы:${NC}"
    echo "• Load average: $(uptime | awk -F'load average:' '{print $2}')"
    echo "• Диск: $(df -h / | awk 'NR==2{print $5}')"
    echo "• Память: $(free -h | awk 'NR==2{print $3"/"$2}')"
    echo ""
}

show_users() {
    echo -e "${YELLOW}👥 Последние пользователи:${NC}"
    sqlite3 -header -column $DB_PATH "
        SELECT user_id, first_name, username, registration_date 
        FROM users 
        ORDER BY registration_date DESC 
        LIMIT 10
    "
    echo ""
}

manage_subscriptions() {
    echo -e "${YELLOW}🔧 Активные подписки:${NC}"
    sqlite3 -header -column $DB_PATH "
        SELECT u.user_id, u.first_name, s.client_name, s.end_date, s.speed_limit
        FROM subscriptions s
        JOIN users u ON s.user_id = u.user_id
        WHERE s.end_date > datetime('now')
        ORDER BY s.end_date DESC
        LIMIT 10
    "
    echo ""
}

system_settings() {
    echo -e "${YELLOW}⚙️ Текущие настройки:${NC}"
    sqlite3 -header -column $DB_PATH "SELECT * FROM settings"
    echo ""
    
    echo -e "${YELLOW}🛠 Изменить настройку:${NC}"
    echo "1. Изменить цену подписки"
    echo "2. Изменить лимит скорости"
    echo "3. Изменить DNS серверы"
    echo "4. Назад"
    echo ""
    
    read -p "Выберите действие: " setting_choice
    
    case $setting_choice in
        1)
            read -p "Новая цена (руб): " new_price
            sqlite3 $DB_PATH "UPDATE settings SET value='$new_price' WHERE key='price'"
            echo "✅ Цена обновлена"
            ;;
        2)
            read -p "Новый лимит скорости (Мбит/с): " new_speed
            sqlite3 $DB_PATH "UPDATE settings SET value='$new_speed' WHERE key='speed_limit'"
            echo "✅ Лимит скорости обновлен"
            ;;
        3)
            read -p "DNS 1: " dns1
            read -p "DNS 2: " dns2
            sqlite3 $DB_PATH "UPDATE settings SET value='$dns1' WHERE key='dns1'"
            sqlite3 $DB_PATH "UPDATE settings SET value='$dns2' WHERE key='dns2'"
            echo "✅ DNS серверы обновлены"
            ;;
    esac
}

restart_services() {
    echo -e "${YELLOW}🔄 Перезапуск сервисов...${NC}"
    systemctl restart openvpn@server
    systemctl restart coffee-coma-vpn
    echo "✅ Сервисы перезапущены"
    echo ""
}

edit_config() {
    nano $INSTALL_DIR/config.py
    echo "✅ Конфиг обновлен. Перезапустите бота для применения изменений."
    echo ""
}

# Основной цикл
while true; do
    show_menu
    read -p "Выберите действие: " choice
    
    case $choice in
        1) show_stats ;;
        2) show_users ;;
        3) manage_subscriptions ;;
        4) system_settings ;;
        5) restart_services ;;
        6) edit_config ;;
        7) 
            echo -e "${GREEN}До свидания!${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}Неверный выбор${NC}"
            ;;
    esac
    
    echo ""
    read -p "Нажмите Enter для продолжения..."
    clear
done
