from aiogram import Dispatcher, types
from aiogram.dispatcher import FSMContext
from aiogram.types import Message, CallbackQuery, InputFile

from bot.utils.config import Config
from bot.database.models import Payment, User
from bot.services.payment import PaymentService
from bot.services.vpn import VPNService
from bot.keyboards.main import get_payment_keyboard

async def buy_command(message: Message):
    """Покупка VPN"""
    await message.answer(
        "🎯 <b>Выберите тариф:</b>\n\n"
        "• 1 месяц - 100 руб.\n"
        "• 3 месяца - 250 руб. (экономия 50 руб.)\n"
        "• 6 месяцев - 450 руб. (экономия 150 руб.)\n"
        "• 1 год - 800 руб. (экономия 400 руб.)\n\n"
        "💳 Оплата: карты, криптовалюта",
        reply_markup=get_payment_keyboard(),
        parse_mode=types.ParseMode.HTML
    )

async def process_payment(callback: CallbackQuery):
    """Обработка выбора тарифа"""
    tariff = callback.data.split('_')[1]
    prices = {
        '1month': 100,
        '3months': 250,
        '6months': 450,
        '1year': 800
    }
    
    amount = prices.get(tariff)
    if not amount:
        await callback.answer("❌ Неверный тариф")
        return
    
    # Создание платежа
    payment_data = await PaymentService.create_yookassa_payment(
        amount, 
        callback.from_user.id,
        f"VPN подписка {tariff}"
    )
    
    if payment_data:
        # Сохранение платежа в БД
        await PaymentService.create_payment_record(
            callback.from_user.id,
            amount,
            payment_data['id']
        )
        
        await callback.message.answer(
            f"💳 <b>Оплата</b>\n\n"
            f"Сумма: {amount} руб.\n"
            f"Тариф: {tariff}\n\n"
            f"🔗 <a href='{payment_data['confirmation']['confirmation_url']}'>Оплатить</a>\n\n"
            "После оплаты нажмите /check для проверки",
            parse_mode=types.ParseMode.HTML
        )
    else:
        await callback.message.answer("❌ Ошибка создания платежа")

async def check_payment(message: Message):
    """Проверка платежа"""
    user_id = message.from_user.id
    payment = await Payment.query.where(
        (Payment.user_id == user_id) & 
        (Payment.status == 'pending')
    ).gino.first()
    
    if not payment:
        await message.answer("❌ Платежи не найдены")
        return
    
    status = await PaymentService.check_payment_status(payment.payment_id)
    
    if status == 'succeeded':
        await payment.update(status='succeeded').apply()
        
        # Активация VPN
        vpn_service = VPNService()
        config_text = await vpn_service.create_vpn_config(user_id, 1)  # 1 месяц
        
        if config_text:
            # Отправка конфига
            with open(f"config_{user_id}.ovpn", "w") as f:
                f.write(config_text)
            
            await message.answer_document(
                InputFile(f"config_{user_id}.ovpn"),
                caption="✅ VPN активирован! Файл конфигурации прикреплен."
            )
        else:
            await message.answer("❌ Ошибка создания VPN конфигурации")
            
    elif status == 'pending':
        await message.answer("⏳ Платеж еще обрабатывается")
    else:
        await message.answer("❌ Платеж не прошел")

def register_payment_handlers(dp: Dispatcher):
    dp.register_message_handler(buy_command, commands=['buy'])
    dp.register_message_handler(check_payment, commands=['check'])
    dp.register_callback_query_handler(process_payment, lambda c: c.data.startswith('pay_'))
