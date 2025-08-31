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
echo -e "${BLUE}=== Coffee Coma VPN Reinstall/Update ===${NC}"

# Проверка на root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Пожалуйста, запустите скрипт с правами root: sudo ./reinstall.sh${NC}"
    exit 1
fi

# Переменные
INSTALL_DIR="/opt/coffee-coma-vpn"
BACKUP_DIR="/tmp/vpn_backup"
SERVICE_FILE="/etc/systemd/system/coffee-coma-vpn.service"

# Функция для вывода сообщений
log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# Создаем backup текущих настроек
log "Создание backup текущих настроек..."
mkdir -p $BACKUP_DIR

# Backup базы данных
if [ -f "$INSTALL_DIR/vpn_bot.db" ]; then
    cp $INSTALL_DIR/vpn_bot.db $BACKUP_DIR/
    log "База данных сохранена в backup"
fi

# Backup конфига
if [ -f "$INSTALL_DIR/config.py" ]; then
    cp $INSTALL_DIR/config.py $BACKUP_DIR/
    log "Конфиг сохранен в backup"
fi

# Останавливаем сервис
log "Остановка сервиса..."
systemctl stop coffee-coma-vpn 2>/dev/null || true

# Удаляем старую директорию
log "Удаление старой версии..."
rm -rf $INSTALL_DIR

# Скачиваем свежую версию с GitHub
log "Скачивание новой версии с GitHub..."
cd /root
if [ -d "coffee-coma-vpn" ]; then
    rm -rf coffee-coma-vpn
fi

git clone https://github.com/Matebey/coffee-coma-vpn.git
cd coffee-coma-vpn

# Запускаем установку
log "Запуск установки..."
chmod +x install.sh
./install.sh

# Восстанавливаем backup
log "Восстановление backup..."
if [ -f "$BACKUP_DIR/config.py" ]; then
    cp $BACKUP_DIR/config.py $INSTALL_DIR/
    log "Конфиг восстановлен из backup"
fi

if [ -f "$BACKUP_DIR/vpn_bot.db" ]; then
    cp $BACKUP_DIR/vpn_bot.db $INSTALL_DIR/
    log "База данных восстановлена из backup"
fi

# Чистим backup
rm -rf $BACKUP_DIR

log "Переустановка завершена!"
echo -e "${YELLOW}=================================================${NC}"
echo -e "${GREEN}✅ Бот обновлен до последней версии${NC}"
echo -e "${GREEN}✅ Настройки восстановлены из backup${NC}"
echo -e "${YELLOW}=================================================${NC}"
echo -e "${BLUE}Статус сервиса:${NC}"
systemctl status coffee-coma-vpn --no-pager -l
