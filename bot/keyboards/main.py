from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def get_main_keyboard():
    """Основная клавиатура"""
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton('💰 Купить VPN'))
    keyboard.add(KeyboardButton('🔗 Мой VPN'), KeyboardButton('👥 Рефералы'))
    keyboard.add(KeyboardButton('ℹ️ Помощь'))
    return keyboard

def get_payment_keyboard():
    """Клавиатура выбора тарифа"""
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("1 месяц - 100 руб.", callback_data="pay_1month"),
        InlineKeyboardButton("3 месяца - 250 руб.", callback_data="pay_3months")
    )
    keyboard.add(
        InlineKeyboardButton("6 месяцев - 450 руб.", callback_data="pay_6months"),
        InlineKeyboardButton("1 год - 800 руб.", callback_data="pay_1year")
    )
    return keyboard
