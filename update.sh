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
echo -e "${BLUE}=== Coffee Coma VPN Update System ===${NC}"

# Проверка на root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Пожалуйста, запустите скрипт с правами root: sudo ./update.sh${NC}"
    exit 1
fi

INSTALL_DIR="/opt/coffee-coma-vpn"
BACKUP_DIR="/opt/coffee-coma-vpn-backup"

log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# Создаем бэкап
log "Создание резервной копии..."
mkdir -p $BACKUP_DIR
cp -r $INSTALL_DIR/* $BACKUP_DIR/ 2>/dev/null || true
cp /etc/systemd/system/coffee-coma-vpn.service $BACKUP_DIR/ 2>/dev/null || true

# Останавливаем сервисы
log "Остановка сервисов..."
systemctl stop coffee-coma-vpn

# Копируем новые файлы
log "Копирование обновленных файлов..."
cp -f *.py $INSTALL_DIR/
cp -f *.sh $INSTALL_DIR/
cp -f requirements.txt $INSTALL_DIR/
chmod +x $INSTALL_DIR/*.sh

# Обновляем Python зависимости
log "Обновление Python зависимостей..."
cd $INSTALL_DIR
source venv/bin/activate
pip install -r requirements.txt

# Перезапускаем сервисы
log "Перезапуск сервисов..."
systemctl daemon-reload
systemctl start coffee-coma-vpn

log "Обновление завершено! Проверьте работу системы."
echo -e "${YELLOW}Бэкап сохранен в: $BACKUP_DIR${NC}"
