import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Telegram
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
    
    # Payments
    PAYMENT_PROVIDER = os.getenv('PAYMENT_PROVIDER', 'yookassa')
    PAYMENT_TOKEN = os.getenv('PAYMENT_TOKEN')
    
    # OpenVPN API
    OPENVPN_API_URL = os.getenv('OPENVPN_API_URL')
    OPENVPN_API_KEY = os.getenv('OPENVPN_API_KEY')
    
    # Database
    DB_URL = os.getenv('DB_URL', 'sqlite:///bot.db')
    
    # Referral
    REFERRAL_PERCENT = float(os.getenv('REFERRAL_PERCENT', 0.1))
    
    # JWT
    JWT_SECRET = os.getenv('JWT_SECRET', 'default-secret-key')
    
    # Prices
    VPN_PRICES = {
        '1_month': 100,
        '3_months': 250,
        '6_months': 450,
        '1_year': 800
    }
