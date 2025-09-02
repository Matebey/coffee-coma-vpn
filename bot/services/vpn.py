import logging
from typing import Optional
from datetime import datetime, timedelta
from bot.services.openvpn_api import OpenVPNAPI
from bot.database.models import VPNConfig, User
from bot.utils.helpers import calculate_expiry_date

logger = logging.getLogger(__name__)

class VPNService:
    def __init__(self):
        self.openvpn_api = OpenVPNAPI()
    
    async def create_vpn_config(self, user_id: int, duration_months: int = 1) -> Optional[str]:
        """Создание VPN конфигурации для пользователя"""
        try:
            user = await User.get(user_id)
            if not user:
                logger.error(f"User {user_id} not found")
                return None
            
            # Создание клиента в OpenVPN
            client_data = await self.openvpn_api.create_client(
                user_id, 
                user.username or f"user_{user_id}",
                duration_months * 30
            )
            
            if not client_data:
                return None
            
            # Получение конфига
            config_text = await self.openvpn_api.get_client_config(client_data['id'])
            
            if not config_text:
                return None
            
            # Сохранение в БД
            expires_at = calculate_expiry_date(duration_months)
            
            vpn_config = await VPNConfig.create(
                user_id=user_id,
                config_data=config_text,
                expires_at=expires_at,
                is_active=True
            )
            
            return config_text
            
        except Exception as e:
            logger.error(f"Failed to create VPN config: {e}")
            return None
    
    async def get_user_config(self, user_id: int) -> Optional[VPNConfig]:
        """Получение активного конфига пользователя"""
        return await VPNConfig.query.where(
            (VPNConfig.user_id == user_id) & 
            (VPNConfig.is_active == True) &
            (VPNConfig.expires_at > datetime.now())
        ).gino.first()
    
    async def deactivate_config(self, config_id: int) -> bool:
        """Деактивация конфигурации"""
        config = await VPNConfig.get(config_id)
        if config:
            await config.update(is_active=False).apply()
            return True
        return False
