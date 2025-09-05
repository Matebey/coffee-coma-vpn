import sqlite3
import logging
from config import load_config

logger = logging.getLogger(__name__)

def init_db():
    try:
        config = load_config()
        db_path = config.get('db_path', 'vpn_bot.db')
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Таблица users
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                username TEXT,
                config_name TEXT,
                private_key TEXT,
                certificate TEXT,
                status TEXT DEFAULT 'active',
                is_trial INTEGER DEFAULT 0,
                is_paid INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME
            )
        ''')
        
        # Таблица payments
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                amount INTEGER,
                payment_method TEXT,
                status TEXT DEFAULT 'pending',
                screenshot_path TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных успешно инициализирована!")
        
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        raise

def get_connection():
    config = load_config()
    return sqlite3.connect(config.get('db_path', 'vpn_bot.db'))

def execute_query(query, params=()):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(query, params)
    conn.commit()
    result = cursor.fetchall()
    conn.close()
    return result

def get_user_configs(user_id):
    return execute_query("""
        SELECT config_name, status, expires_at, is_trial, is_paid 
        FROM users WHERE user_id = ? ORDER BY created_at DESC
    """, (user_id,))

def add_user(user_id, username, config_name, private_key, certificate, 
             is_trial, is_paid, expires_at):
    execute_query("""
        INSERT INTO users (user_id, username, config_name, private_key, certificate, 
        is_trial, is_paid, expires_at, status) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
    """, (user_id, username, config_name, private_key, certificate, 
          is_trial, is_paid, expires_at))

def add_payment(user_id, amount, payment_method, status='completed'):
    execute_query("""
        INSERT INTO payments (user_id, amount, payment_method, status) 
        VALUES (?, ?, ?, ?)
    """, (user_id, amount, payment_method, status))

def get_user_config_count(user_id):
    result = execute_query("SELECT COUNT(*) FROM users WHERE user_id = ?", (user_id,))
    return result[0][0] if result else 0

def has_trial_used(user_id):
    result = execute_query("SELECT id FROM users WHERE user_id = ? AND is_trial = 1", (user_id,))
    return len(result) > 0

def get_stats():
    stats = {}
    
    result = execute_query("SELECT COUNT(*) FROM users")
    stats['total_users'] = result[0][0] if result else 0
    
    result = execute_query("SELECT COUNT(*) FROM users WHERE is_trial = 1")
    stats['trial_users'] = result[0][0] if result else 0
    
    result = execute_query("SELECT COUNT(*) FROM users WHERE is_paid = 1")
    stats['paid_users'] = result[0][0] if result else 0
    
    result = execute_query("SELECT COUNT(*) FROM users WHERE status = 'active'")
    stats['active_users'] = result[0][0] if result else 0
    
    result = execute_query("SELECT SUM(amount) FROM payments WHERE status = 'completed'")
    stats['total_revenue'] = result[0][0] or 0
    
    return stats
