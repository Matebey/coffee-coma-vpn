import json
import os

CONFIG_FILE = "config.json"

def init_config():
    if not os.path.exists(CONFIG_FILE):
        default_config = {
            "bot_token": "8439963327:AAHDIJQuP611mfBtcFSZyDwO4-mBANPArAk",
            "admin_ids": [5631675412],
            "openvpn_dir": "/etc/openvpn",
            "easy_rsa_dir": "/etc/openvpn/easy-rsa",
            "pki_dir": "/etc/openvpn/easy-rsa/pki",
            "keys_dir": "/etc/openvpn/easy-rsa/pki/private",
            "issued_dir": "/etc/openvpn/easy-rsa/pki/issued",
            "server_config": "/etc/openvpn/server.conf",
            "db_path": "vpn_bot.db",
            "trial_days": 7,
            "max_configs_per_user": 3,
            "server_ip": "77.239.105.14",
            "server_port": 8443,
            "protocol": "udp",
            "price": 50,
            "sbp_link": "https://yoomoney.ru/to/4100119260614239/0",
            "wallet_number": "https://yoomoney.ru/to/4100119260614239/0",
            "dns_servers": "1.1.1.1,8.8.8.8",
            "ca_cert_path": "/etc/openvpn/easy-rsa/pki/ca.crt",
            "ta_key_path": "/etc/openvpn/easy-rsa/ta.key",
            "openvpn_management_ip": "127.0.0.1",
            "openvpn_management_port": 7505,
            "client_config_template": "/etc/openvpn/client-template.ovpn"
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(default_config, f, indent=4)
        return default_config
    return load_config()

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            
            # Добавляем недостающие параметры
            config.setdefault('openvpn_dir', '/etc/openvpn')
            config.setdefault('easy_rsa_dir', '/etc/openvpn/easy-rsa')
            config.setdefault('pki_dir', '/etc/openvpn/easy-rsa/pki')
            config.setdefault('keys_dir', '/etc/openvpn/easy-rsa/pki/private')
            config.setdefault('issued_dir', '/etc/openvpn/easy-rsa/pki/issued')
            config.setdefault('server_config', '/etc/openvpn/server.conf')
            config.setdefault('db_path', 'vpn_bot.db')
            config.setdefault('max_configs_per_user', 3)
            config.setdefault('client_config_template', '/etc/openvpn/client-template.ovpn')
            
            return config
    except FileNotFoundError:
        return init_config()

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

def is_admin(user_id):
    config = load_config()
    return user_id in config['admin_ids']
