#!/bin/bash

# Цвета для вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Coffee Coma VPN Update ===${NC}"

# Проверка на root
if [ "$EUID" -ne 0 ]; then
    echo "Пожалуйста, запустите скрипт с правами root: sudo ./update.sh"
    exit 1
fi

INSTALL_DIR="/opt/coffee-coma-vpn"

# Останавливаем сервис
echo "Остановка сервиса..."
systemctl stop coffee-coma-vpn

# Скачиваем обновления
echo "Скачивание обновлений..."
cd /root/coffee-coma-vpn
git pull origin main

# Копируем новые файлы
echo "Копирование новых файлов..."
cp -f *.py $INSTALL_DIR/
cp -f *.sh $INSTALL_DIR/
chmod +x $INSTALL_DIR/*.sh

# Перезапускаем сервис
echo "Перезапуск сервиса..."
systemctl start coffee-coma-vpn

echo -e "${GREEN}✅ Обновление завершено!${NC}"
echo "Статус:"
systemctl status coffee-coma-vpn --no-pager -l
