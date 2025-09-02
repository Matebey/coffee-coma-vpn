import logging
import aiohttp
import json
from typing import Optional, Dict
from bot.utils.config import Config
from bot.database.models import Payment

logger = logging.getLogger(__name__)

class PaymentService:
    @staticmethod
    async def create_yookassa_payment(amount: float, user_id: int, description: str) -> Optional[Dict]:
        """Создание платежа в ЮKassa"""
        try:
            headers = {
                'Authorization': f'Bearer {Config.PAYMENT_TOKEN}',
                'Content-Type': 'application/json',
                'Idempotence-Key': f'{user_id}_{int(amount)}'
            }
            
            payload = {
                "amount": {
                    "value": f"{amount:.2f}",
                    "currency": "RUB"
                },
                "capture": True,
                "confirmation": {
                    "type": "redirect",
                    "return_url": f"https://t.me/{Config.BOT_TOKEN.split(':')[0]}"
                },
                "description": description,
                "metadata": {
                    "user_id": user_id
                }
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    'https://api.yookassa.ru/v3/payments',
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data
                    else:
                        logger.error(f"Yookassa error: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"Payment creation failed: {e}")
            return None
    
    @staticmethod
    async def check_payment_status(payment_id: str) -> Optional[str]:
        """Проверка статуса платежа"""
        try:
            headers = {
                'Authorization': f'Bearer {Config.PAYMENT_TOKEN}',
                'Content-Type': 'application/json'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f'https://api.yookassa.ru/v3/payments/{payment_id}',
                    headers=headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('status')
                    return None
                    
        except Exception as e:
            logger.error(f"Payment check failed: {e}")
            return None
    
    @staticmethod
    async def create_payment_record(user_id: int, amount: float, payment_id: str) -> Payment:
        """Создание записи о платеже в БД"""
        return await Payment.create(
            user_id=user_id,
            amount=amount,
            payment_id=payment_id,
            status='pending'
        )
