from aiogram import Dispatcher, types
from aiogram.types import Message

from bot.utils.config import Config
from bot.database.models import Referral, User
from bot.utils.helpers import generate_random_string

async def referral_command(message: Message):
    """Реферальная программа"""
    user_id = message.from_user.id
    user = await User.get(user_id)
    
    if not user:
        await message.answer("❌ Пользователь не найден")
        return
    
    # Статистика рефералов
    referrals = await Referral.query.where(
        Referral.referrer_id == user_id
    ).gino.all()
    
    total_earned = sum(ref.earned for ref in referrals)
    
    referral_link = f"https://t.me/{(await message.bot.me).username}?start=ref{user_id}"
    
    await message.answer(
        f"👥 <b>Реферальная программа</b>\n\n"
        f"🔗 Ваша ссылка: <code>{referral_link}</code>\n\n"
        f"📊 Статистика:\n"
        f"• Рефералов: {len(referrals)}\n"
        f"• Заработано: {total_earned} руб.\n\n"
        f"💵 Вы получаете {Config.REFERRAL_PERCENT * 100}% "
        f"от каждой покупки вашего реферала\n\n"
        f"💰 Баланс: {user.balance} руб.",
        parse_mode=types.ParseMode.HTML
    )

def register_referral_handlers(dp: Dispatcher):
    dp.register_message_handler(referral_command, commands=['referral', 'ref'])
