#!/usr/bin/env python3
import sqlite3
import sys

def setup_yoomoney(wallet, token):
    db_path = "/opt/coffee-coma-vpn/vpn_bot.db"
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Обновляем настройки ЮMoney
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('yoomoney_wallet', ?)", (wallet,))
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('yoomoney_token', ?)", (token,))
        
        conn.commit()
        conn.close()
        
        print("✅ Настройки ЮMoney успешно обновлены!")
        print(f"   Кошелек: {wallet}")
        print(f"   Токен: {token}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Использование: python3 setup_yoomoney.py <номер_кошелька> <токен>")
        sys.exit(1)
    
    wallet = sys.argv[1]
    token = sys.argv[2]
    setup_yoomoney(wallet, token)