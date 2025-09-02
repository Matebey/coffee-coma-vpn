import string
import random
from datetime import datetime, timedelta

def generate_random_string(length=16):
    """Генерация случайной строки"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def format_date(date):
    """Форматирование даты"""
    if isinstance(date, datetime):
        return date.strftime("%d.%m.%Y %H:%M")
    return date

def calculate_expiry_date(months=1):
    """Расчет даты истечения срока"""
    return datetime.now() + timedelta(days=30 * months)

def format_currency(amount, currency='RUB'):
    """Форматирование валюты"""
    return f"{amount:.2f} {currency}"
