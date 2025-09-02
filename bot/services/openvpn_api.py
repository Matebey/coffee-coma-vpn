import requests
import json
import logging
from typing import Optional, Dict
from bot.utils.config import Config

logger = logging.getLogger(__name__)

class OpenVPNAPIError(Exception):
    pass

class OpenVPNAPI:
    def __init__(self):
        self.api_url = Config.OPENVPN_API_URL
        self.api_key = Config.OPENVPN_API_KEY
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
    
    async def create_client(self, user_id: int, username: str, duration_days: int = 30) -> Optional[Dict]:
        """Создание нового VPN клиента"""
        payload = {
            "user_id": user_id,
            "username": username,
            "duration": duration_days
        }
        
        try:
            response = requests.post(
                f"{self.api_url}/clients",
                headers=self.headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 201:
                return response.json()
            else:
                logger.error(f"OpenVPN API error: {response.status_code} - {response.text}")
                return None
                
        except requests.RequestException as e:
            logger.error(f"OpenVPN API request failed: {e}")
            return None
    
    async def get_client_config(self, client_id: str) -> Optional[str]:
        """Получение конфигурационного файла"""
        try:
            response = requests.get(
                f"{self.api_url}/clients/{client_id}/config",
                headers=self.headers,
                timeout=30
            )
            
            if response.status_code == 200:
                return response.text
            else:
                logger.error(f"OpenVPN config error: {response.status_code}")
                return None
                
        except requests.RequestException as e:
            logger.error(f"OpenVPN config request failed: {e}")
            return None
    
    async def revoke_client(self, client_id: str) -> bool:
        """Отзыв клиентского сертификата"""
        try:
            response = requests.delete(
                f"{self.api_url}/clients/{client_id}",
                headers=self.headers,
                timeout=30
            )
            
            return response.status_code == 200
            
        except requests.RequestException as e:
            logger.error(f"OpenVPN revoke failed: {e}")
            return False
