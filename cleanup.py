#!/usr/bin/env python3
import sqlite3
import os
import subprocess
from datetime import datetime

DB_PATH = "/opt/coffee-coma-vpn/vpn_bot.db"
OVPN_KEYS_DIR = "/etc/openvpn/easy-rsa/pki/"
OVPN_CLIENT_DIR = "/etc/openvpn/client-configs/"

def cleanup_expired():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Находим просроченные подписки
    cursor.execute('SELECT client_name FROM subscriptions WHERE end_date < datetime("now")')
    expired = cursor.fetchall()
    
    for (client_name,) in expired:
        try:
            print(f"Удаление просроченного клиента: {client_name}")
            
            # Отзываем сертификат
            subprocess.run([
                '/bin/bash', '-c', 
                f'cd /etc/openvpn/easy-rsa && echo "yes" | ./easyrsa --batch revoke {client_name}'
            ], check=True, timeout=30)
            
            subprocess.run([
                '/bin/bash', '-c', 
                f'cd /etc/openvpn/easy-rsa && ./easyrsa --batch gen-crl'
            ], check=True, timeout=30)
            
            # Перезапускаем OpenVPN
            subprocess.run(['systemctl', 'restart', 'openvpn@server'], timeout=30)
            
            # Удаляем конфиг
            config_path = f"{OVPN_CLIENT_DIR}{client_name}.ovpn"
            if os.path.exists(config_path):
                os.remove(config_path)
                
            # Удаляем из базы
            cursor.execute('DELETE FROM subscriptions WHERE client_name = ?', (client_name,))
            
        except Exception as e:
            print(f"Ошибка очистки {client_name}: {e}")
    
    conn.commit()
    conn.close()
    print("✅ Очистка завершена!")

if __name__ == "__main__":
    cleanup_expired()