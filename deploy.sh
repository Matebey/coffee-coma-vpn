#!/bin/bash

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}"
echo "   ______          __           ______                 ________    ____"
echo "  / ____/___  ____/ /_  _______/ ____/___  ____  _____/ 极/   |  / __ \\"
echo " / /   / __ \/ __  / / / / ___/ /   / __ \/ __ \/ ___// // /| | / /_/ /"
echo "/ /___/ /_/ / /_/ / /_/ / /__/ /___/ /_/ / / / / /  _/ // ___ |/ ____/"
echo "\____/\____/\__,_/\__,_/\___/\____/\____/_/ /_/_/  /___/_/  |_/_/"
echo -e "${NC}"
echo -e "${BLUE}=== Coffee Coma VPN Auto Deploy ===${NC}"

# Проверка на root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Пожалуйста, запустите скрипт с правами root: sudo ./deploy.sh${NC}"
    exit 1
fi

# Переменные
INSTALL_DIR="/opt/coffee-coma-vpn"
REPO_URL="https://github.com/Matebey/coffee-coma-vpn.git"

log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# Обновление системы
log "Обновление системы..."
apt update && apt upgrade -y

# Установка git если не установлен
if ! command -v git &> /dev/null; then
    log "Установка git..."
    apt install -y git
fi

# Клонирование репозитория
log "Клонирование репозитория..."
if [ -d "$INSTALL_DIR" ]; then
    log "Директория уже существует, обновляем..."
    cd $INSTALL_DIR
    git pull origin main
else
    git clone $REPO_URL $INSTALL_DIR
    cd $INSTALL_DIR
fi

# Делаем скрипты исполняемыми
chmod +x install.sh
chmod +x setup_yoomoney.py

# Запускаем установку
log "Запуск установки..."
./install.sh

log "Деплой завершен!"
echo -e "${YELLOW}=================================================${NC}"
echo -e "${GREEN}✅ Система успешно установлена и настроена${NC}"
echo -e "${YELLOW}=================================================${NC}"
echo -e "${BLUE}Следующие шаги:${NC}"
echo "1. Настройте ЮMoney:"
echo "   cd /opt/coffee-coma-vpn"
echo "   python3 setup_yoomoney.py YOUR_YOOMONEY_WALLET YOUR_YOOMONEY_TOKEN"
echo "2. Проверьте статус бота: systemctl status coffee-coma-vpn"
echo "3. Используйте админ панель: vpn-admin"
echo -e "${YELLOW}=================================================${NC}"