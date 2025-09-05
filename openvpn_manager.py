import os
import subprocess
import datetime
import logging
from cryptography.fernet import Fernet
from config import load_config
from utils import extract_certificate_content, extract_private_key_content

logger = logging.getLogger(__name__)

# Шифрование ключей
KEY = Fernet.generate_key()
cipher_suite = Fernet(KEY)

def create_ovpn_client_certificate(username):
    try:
        config = load_config()
        easy_rsa_dir = config.get('easy_rsa_dir', '/etc/openvpn/easy-rsa/')
        keys_dir = config.get('keys_dir', '/etc/openvpn/easy-rsa/pki/private')
        issued_dir = config.get('issued_dir', '/etc/openvpn/easy-rsa/pki/issued')
        
        # Генерируем уникальное имя для клиента
        client_name = f"client_{username}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Переходим в директорию easy-rsa
        original_dir = os.getcwd()
        os.chdir(easy_rsa_dir)
        
        logger.info(f"Создание сертификата для: {client_name}")
        
        # Создаем клиентский сертификат
        process = subprocess.Popen([
            './easyrsa', 'build-client-full', client_name, 'nopass'
        ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        stdout, stderr = process.communicate(input='yes\n')
        
        if process.returncode != 0:
            logger.error(f"Certificate generation error: {stderr}")
            os.chdir(original_dir)
            return None, None, None
        
        # Читаем приватный ключ
        private_key_path = os.path.join(keys_dir, f"{client_name}.key")
        if os.path.exists(private_key_path):
            with open(private_key_path, 'r') as f:
                private_key_content = f.read()
                private_key = extract_private_key_content(private_key_content)
        else:
            logger.error(f"Private key not found: {private_key_path}")
            os.chdir(original_dir)
            return None, None, None
        
        # Читаем сертификат
        cert_path = os.path.join(issued_dir, f"{client_name}.crt")
        if os.path.exists(cert_path):
            with open(cert_path, 'r') as f:
                certificate_content = f.read()
                certificate = extract_certificate_content(certificate_content)
        else:
            logger.error(f"Certificate not found: {cert_path}")
            os.chdir(original_dir)
            return None, None, None
        
        os.chdir(original_dir)
        return client_name, private_key, certificate
        
    except Exception as e:
        logger.error(f"OpenVPN certificate error: {e}")
        return None, None, None

def generate_ovpn_client_config(client_name, private_key, certificate):
    config = load_config()
    
    try:
        # Читаем CA сертификат
        with open(config['ca_cert_path'], 'r') as f:
            ca_cert_content = f.read()
            ca_cert = extract_certificate_content(ca_cert_content)
        
        # Читаем TLS ключ
        ta_key = ""
        if os.path.exists(config['ta_key_path']):
            with open(config['ta_key_path'], 'r') as f:
                ta_key_content = f.read()
                ta_key = ta_key_content
        
        # Генерируем чистый конфиг
        client_config = f"""client
dev tun
proto {config['protocol']}
remote {config['server_ip']} {config['server_port']}
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
cipher AES-256-GCM
auth SHA256
verb 3

<ca>
{ca_cert}
</ca>

<cert>
{certificate}
</cert>

<key>
{private_key}
</key>
"""
    
        if ta_key:
            client_config += f"""
<tls-crypt>
{ta_key}
</tls-crypt>
"""
    
        return client_config
        
    except Exception as e:
        logger.error(f"Config generation error: {e}")
        return None

def encrypt_data(data):
    return cipher_suite.encrypt(data.encode())

def decrypt_data(encrypted_data):
    return cipher_suite.decrypt(encrypted_data).decode()
