import sqlite3
import os

def init_database():
    db_path = 'vpn_bot.db'
    
    # Удаляем старую базу если существует
    if os.path.exists(db_path):
        print("Удаляем старую базу данных...")
        os.remove(db_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Создаем таблицу пользователей
    cursor.execute('''
    CREATE TABLE users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Создаем таблицу конфигов
    cursor.execute('''
    CREATE TABLE configs (
        config_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        config_name TEXT,
        config_file TEXT,
        creation_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expiry_date TIMESTAMP,
        is_active BOOLEAN DEFAULT TRUE,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    conn.commit()
    conn.close()
    print("База данных успешно инициализирована!")

if __name__ == "__main__":
    init_database()
