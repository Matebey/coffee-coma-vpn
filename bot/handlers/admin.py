from aiogram import Dispatcher, types
from aiogram.dispatcher import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.utils.config import Config
from bot.database.models import User, Payment, VPNConfig
from bot.keyboards.admin import get_admin_keyboard

async def admin_command(message: Message):
    """Панель администратора"""
    if message.from_user.id != Config.ADMIN_ID:
        await message.answer("❌ Доступ запрещен")
        return
    
    # Статистика
    total_users = await User.query.gino.count()
    total_payments = await Payment.query.gino.count()
    active_vpns = await VPNConfig.query.where(
        VPNConfig.is_active == True
    ).gino.count()
    
    await message.answer(
        f"👑 <b>Админ панель</b>\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"💳 Платежей: {total_payments}\n"
        f"🔗 Активных VPN: {active_vpns}\n\n"
        "⚡ <b>Действия:</b>",
        reply_markup=get_admin_keyboard(),
        parse_mode=types.ParseMode.HTML
    )

async def admin_stats(callback: CallbackQuery):
    """Статистика"""
    total_users = await User.query.gino.count()
    total_payments = await Payment.query.gino.count()
    total_earned = await db.select([db.func.sum(Payment.amount)]).where(
        Payment.status == 'succeeded'
    ).gino.scalar() or 0
    
    await callback.message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"💳 Платежей: {total_payments}\n"
        f"💰 Заработано: {total_earned} руб.\n"
        f"🔗 Активных VPN: {await VPNConfig.query.where(VPNConfig.is_active == True).gino.count()}",
        parse_mode=types.ParseMode.HTML
    )

def register_admin_handlers(dp: Dispatcher):
    dp.register_message_handler(admin_command, commands=['admin'])
    dp.register_callback_query_handler(admin_stats, lambda c: c.data == 'admin_stats')
