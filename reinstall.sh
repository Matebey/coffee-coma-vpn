#!/bin/bash

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}"
echo "   ______          __           ______                 ________    ____"
echo "  / ____/___  ____/ /_  _______/ ____/___  ____  _____/  _/   |  / __ \\"
echo " / /   / __ \/ __  / / / / ___/ /   / __ \/ __ \/ ___// // /| | / /_/ /"
echo "/ /___/ /_/ / /_/ / /_/ / /__/ /___/ /_/ / / / / /  _/ // ___ |/ ____/"
echo "\____/\____/\__,_/\__,_/\___/\____/\____/_/ /_/_/  /___/_/  |_/_/"
echo -e "${NC}"
echo -e "${BLUE}=== Coffee Coma VPN Reinstaller ===${NC}"

# Проверка на root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Пожалуйста, запустите скрипт с правами root: sudo ./reinstall.sh${NC}"
    exit 1
fi

INSTALL_DIR="/opt/coffee-coma-vpn"

log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# Останавливаем сервисы
log "Остановка сервисов..."
systemctl stop coffee-coma-vpn
systemctl stop openvpn@server

# Удаляем старую установку
log "Удаление старой установки..."
rm -rf $INSTALL_DIR
rm -f /etc/systemd/system/coffee-coma-vpn.service
rm -f /usr/local/bin/vpn-admin
rm -f /usr/local/bin/vpn-reinstall
rm -f /usr/local/bin/vpn-update

# Запускаем установку
log "Запуск новой установки..."
./install.sh

log "Переустановка завершена!"
