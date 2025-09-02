import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
import config

def handle_payment_selection(update: Update, context: CallbackContext, period: int):
    query = update.callback_query
    price = config.PRICE * period
    
    keyboard = [
        [InlineKeyboardButton("ЮMoney", callback_data=f'pay_yoomoney_{period}')],
        [InlineKeyboardButton("CloudTips", callback_data=f'pay_cloudtips_{period}')],
        [InlineKeyboardButton("Назад", callback_data='buy')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(
        text=f"Вы выбрали тариф на {period} месяц(ев) за {price} руб.\nВыберите способ оплаты:",
        reply_markup=reply_markup
    )

def create_yoomoney_payment(update: Update, context: CallbackContext, period: int):
    # Здесь будет код для создания платежа в ЮMoney
    pass

def create_cloudtips_payment(update: Update, context: CallbackContext, period: int):
    # Здесь будет код для создания платежа в CloudTips
    pass

def check_payment_status(update: Update, context: CallbackContext):
    # Здесь будет код для проверки статуса платежа
    pass
