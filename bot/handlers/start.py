from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import Message

from bot.database.models import User, Referral
from bot.keyboards.main import get_main_keyboard

router = Router()

@router.message(Command("start"))
async def start_command(message: Message):
    """Обработка команды /start"""
    user_id = message.from_user.id
    user = await User.get(user_id)
    
    if not user:
        user = await User.create(
            id=user_id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name
        )
        
        if len(message.text.split()) > 1:
            ref_code = message.text.split()[1]
            if ref_code.startswith('ref'):
                try:
                    referrer_id = int(ref_code[3:])
                    await Referral.create(
                        referrer_id=referrer_id,
                        referred_id=user_id
                    )
                except ValueError:
                    pass
    
    await message.answer(
        f"👋 Добро пожаловать, {message.from_user.first_name}!\n\n"
        "🚀 Это VPN бот для безопасного и анонимного серфинга.\n\n"
        "📋 Доступные команды:\n"
        "• /buy - Купить VPN\n"
        "• /my - Мои подписки\n"
        "• /referral - Реферальная программа\n"
        "• /help - Помощь",
        reply_markup=get_main_keyboard()
    )

@router.message(Command("help"))
async def help_command(message: Message):
    """Обработка команды /help"""
    await message.answer(
        "🤖 <b>VPN Bot Help</b>\n\n"
        "🔐 <b>Как использовать:</b>\n"
        "1. Купите подписку командой /buy\n"
        "2. После оплаты получите конфиг файл\n"
        "3. Установите OpenVPN клиент\n"
        "4. Импортируйте конфиг файл\n"
        "5. Подключайтесь к VPN!\n\n"
        "💳 <b>Оплата:</b> Принимаем карты, крипту\n"
        "👥 <b>Рефералы:</b> Получайте 10% с покупок"
    )
