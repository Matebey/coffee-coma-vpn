import qrcode
import io
import random
import string
import datetime
import logging

logger = logging.getLogger(__name__)

def generate_config_name(user_id):
    random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"user_{user_id}_{random_suffix}"

def extract_certificate_content(cert_content):
    """Извлекает только содержимое сертификата между BEGIN и END"""
    lines = cert_content.split('\n')
    certificate_lines = []
    in_certificate = False
    
    for line in lines:
        if '-----BEGIN CERTIFICATE-----' in line:
            in_certificate = True
            certificate_lines.append(line)
            continue
        elif '-----END CERTIFICATE-----' in line:
            certificate_lines.append(line)
            break
        elif in_certificate:
            certificate_lines.append(line)
    
    return '\n'.join(certificate_lines)

def extract_private_key_content(key_content):
    """Извлекает только содержимое приватного ключа между BEGIN и END"""
    lines = key_content.split('\n')
    key_lines = []
    in_key = False
    
    for line in lines:
        if '-----BEGIN PRIVATE KEY-----' in line:
            in_key = True
            key_lines.append(line)
            continue
        elif '-----END PRIVATE KEY-----' in line:
            key_lines.append(line)
            break
        elif in_key:
            key_lines.append(line)
    
    return '\n'.join(key_lines)

def generate_qr_code(config_text, config_name):
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(config_text)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        
        return img_buffer
    except Exception as e:
        logger.error(f"QR generation error: {e}")
        return None

def calculate_expiration_date(is_trial=False):
    config = load_config()
    days = config['trial_days'] if is_trial else 30
    return (datetime.datetime.now() + datetime.timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
