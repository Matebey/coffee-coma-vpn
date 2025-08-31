# ☕ Coffee Coma VPN

Полная система управления VPN с телеграм ботом, ограничением скорости и реферальной программой.

## 🚀 Быстрый старт

### 1. Настройка Master сервера (77.239.105.14)

```bash
ssh root@77.239.105.14
git clone https://github.com/yourusername/coffee-coma-vpn.git
cd coffee-coma-vpn

# Установка
chmod +x scripts/setup_master.sh
./scripts/setup_master.sh

# Настройка зависимостей
python3 -m venv venv
source venv/bin/activate
pip install --break-system-packages -r requirements.txt

# Генерация сертификатов
apt install -y easy-rsa
make-cadir ~/openvpn-ca
cd ~/openvpn-ca

# Заполните vars файл и выполните:
source vars
./clean-all
./build-ca
./build-key-server server
./build-dh
openvpn --genkey --secret keys/ta.key

# Копирование сертификатов
cp keys/{ca.crt,server.crt,server.key,ta.key,dh2048.pem} /etc/openvpn/