from .start import register_start_handlers
from .admin import register_admin_handlers
from .payment import register_payment_handlers
from .referral import register_referral_handlers

def register_handlers(dp):
    """Регистрация всех обработчиков"""
    register_start_handlers(dp)
    register_admin_handlers(dp)
    register_payment_handlers(dp)
    register_referral_handlers(dp)
