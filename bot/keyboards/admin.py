from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_admin_keyboard():
    """Админ клавиатура"""
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
        InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")
    )
    keyboard.add(
        InlineKeyboardButton("💳 Платежи", callback_data="admin_payments"),
        InlineKeyboardButton("🔗 VPN", callback_data="admin_vpn")
    )
    keyboard.add(
        InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")
    )
    return keyboard
