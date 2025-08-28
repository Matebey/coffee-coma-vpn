#!/usr/bin/env python3
import os
import redis
from datetime import datetime
import yaml

with open('/opt/coffee-coma-vpn/config.yaml') as f:
    config = yaml.safe_load(f)

r = redis.Redis(host=config['redis']['host'], port=config['redis']['port'])

# Очистка просроченных ключей
for key in r.scan_iter("user:*"):
    user_data = r.hgetall(key)
    if user_data.get(b'active') == b'true':
        expiry_date = datetime.fromisoformat(user_data[b'expires'].decode())
        if datetime.now() > expiry_date:
            user_id = key.decode().split(':')[1]
            client_name = f"client_{user_id}"
            
            # Удаление файлов
            for ext in ['.ovpn', '.key', '.crt']:
                try:
                    os.remove(f"{config['vpn']['dir']}/{client_name}{ext}")
                except FileNotFoundError:
                    pass
            
            # Обновление статуса
            r.hset(key, 'active', 'false')
            print(f"Удален ключ пользователя {user_id}")