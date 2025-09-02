from .start import router as start_router
from .admin import router as admin_router
from .payment import router as payment_router
from .referral import router as referral_router

def register_handlers(dp):
    """Регистрация всех обработчиков"""
    dp.include_router(start_router)
    dp.include_router(admin_router)
    dp.include_router(payment_router)
    dp.include_router(referral_router)
