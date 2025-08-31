import os
import logging
import secrets
import random
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import TelegramError
import yaml
from datetime import datetime, timedelta
import redis
import subprocess

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

with open('config.yaml') as f:
    config = yaml.safe_load(f)

r = redis.Redis(
    host=config['redis']['host'],
    port=config['redis']['port'],
    decode_responses=True
)

def generate_referral_code(user_id: int) -> str:
    code = secrets.token_hex(4).upper()[:8]
    r.set(f"ref:{code}", user_id, ex=2592000)
    r.sadd(f"user:{user_id}:ref_codes", code)
    return code

def get_available_server():
    servers = []
    for server_id in r.smembers('servers'):
        server_data = r.hgetall(f"server:{server_id}")
        if server_data.get('status') == 'active':
            servers.append(server_data)
    return random.choice(servers) if servers else None

def assign_user_to_server(user_id: int, server_id: str):
    r.hset(f"user:{user_id}", 'server_id', server_id)
    current_users = int(r.hget(f"server:{server_id}", 'users') or 0)
    r.hset(f"server:{server_id}", 'users', current_users + 1)

def setup_traffic_control(server_data):
    try:
        ssh_cmd = ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'BatchMode=yes']
        if server_data.get('ssh_key'):
            ssh_cmd.extend(['-i', server_data['ssh_key']])
        elif server_data.get('password'):
            ssh_cmd = ['sshpass', '-p', server_data['password']] + ssh_cmd
        
        ssh_cmd.extend([
            f"{server_data['user']}@{server_data['ip']}",
            '/etc/openvpn/scripts/traffic_control.sh setup'
        ])
        
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=30)
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Ошибка настройки TC: {e}")
        return False

def add_client_speed_limit(server_data, client_ip):
    try:
        ssh_cmd = ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'BatchMode=yes']
        if server_data.get('ssh_key'):
            ssh_cmd.extend(['-i', server_data['ssh_key']])
        elif server_data.get('password'):
            ssh_cmd = ['sshpass', '-p', server_data['password']] + ssh_cmd
        
        client_id = hash(client_ip) % 1000
        ssh_cmd.extend([
            f"{server_data['user']}@{server_data['ip']}",
            f"/etc/openvpn/scripts/traffic_control.sh add-client {client_ip} {client_id}"
        ])
        
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=30)
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Ошибка добавления ограничения: {e}")
        return False

def create_vpn_config(user_id: int, is_trial: bool = False, days: int = 30) -> str:
    server = get_available_server()
    if not server:
        raise Exception("Нет доступных серверов")
    
    server_ip = server['ip']
    server_port = server['port']
    server_id = server['id']
    
    client_name = f"client_{user_id}"
    expiry_date = datetime.now() + timedelta(days=days)
    client_ip = f"10.8.0.{100 + (user_id % 100)}"
    
    os.makedirs(config['vpn']['dir'], exist_ok=True)
    
    subprocess.run([
        'openssl', 'req', '-new', '-newkey', 'rsa:2048', '-days', str(days),
        '-nodes', '-x509', '-keyout', f"{config['vpn']['dir']}/{client_name}.key",
        '-out', f"{config['vpn']['dir']}/{client_name}.crt",
        '-subj', f'/CN={client_name}'
    ], check=True)
    
    config_content = f"""client
dev tun
proto udp
remote {server_ip} {server_port}
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
cipher AES-256-CBC
verb 3
<ca>
{open('/etc/openvpn/ca.crt').read()}
</ca>
<cert>
{open(f"{config['vpn']['dir']}/{client_name}.crt").read()}
</cert>
<key>
{open(f"{config['vpn']['dir']}/{client_name}.key").read()}
</key>
<tls-auth>
{open('/etc/openvpn/ta.key').read()}
</tls-auth>
key-direction 1
"""
    
    with open(f"{config['vpn']['dir']}/{client_name}.ovpn", 'w') as f:
        f.write(config_content)
    
    r.hset(f"user:{user_id}", mapping={
        'created': datetime.now().isoformat(),
        'expires': expiry_date.isoformat(),
        'active': 'true',
        'is_trial': str(is_trial),
        'days': str(days),
        'server_id': server_id,
        'client_ip': client_ip
    })
    
    assign_user_to_server(user_id, server_id)
    add_client_speed_limit(server, client_ip)
    
    return f"{config['vpn']['dir']}/{client_name}.ovpn"

def extend_user_subscription(user_id: int, additional_days: int):
    user_data = r.hgetall(f"user:{user_id}")
    if user_data:
        current_expiry = datetime.fromisoformat(user_data['expires'])
        new_expiry = current_expiry + timedelta(days=additional_days)
        r.hset(f"user:{user_id}", 'expires', new_expiry.isoformat())
        return new_expiry
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.first_name
    
    if context.args:
        ref_code = context.args[0]
        referrer_id = r.get(f"ref:{ref_code}")
        
        if referrer_id and referrer_id != str(user_id):
            if not r.exists(f"user:{user_id}"):
                create_vpn_config(user_id, is_trial=True, days=config['referral']['trial_days'])
                new_expiry = extend_user_subscription(int(referrer_id), config['referral']['bonus_days'])
                
                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=f"🎉 Новый пользователь по вашей ссылке!\nПодпиscription продлена на {config['referral']['bonus_days']} дней."
                    )
                except TelegramError:
                    pass
                
                await update.message.reply_text(f"🎉 Пробный период на {config['referral']['trial_days']} дней!")
                return
    
    if r.exists(f"user:{user_id}"):
        user_data = r.hgetall(f"user:{user_id}")
        expiry_date = datetime.fromisoformat(user_data['expires'])
        days_left = (expiry_date - datetime.now()).days
        
        keyboard = [
            [InlineKeyboardButton("🔑 Мой ключ", callback_data='my_key')],
            [InlineKeyboardButton("👥 Реферальная программа", callback_data='referral')],
            [InlineKeyboardButton("🛒 Купить VPN", callback_data='buy_vpn')]
        ]
        
        await update.message.reply_text(
            f"☕ С возвращением, {username}!\nПодписка активна еще {days_left} дней",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        keyboard = [
            [InlineKeyboardButton("🎁 Получить пробный период", callback_data='get_trial')],
            [InlineKeyboardButton("👥 Реферальная программа", callback_data='referral_info')]
        ]
        
        await update.message.reply_text(
            f"☕ Добро пожаловать в Coffee Coma VPN, {username}!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    if query.data == 'get_trial':
        if not r.exists(f"user:{user_id}"):
            create_vpn_config(user_id, is_trial=True, days=config['referral']['trial_days'])
            file_path = f"{config['vpn']['dir']}/client_{user_id}.ovpn"
            
            with open(file_path, 'rb') as f:
                await query.bot.send_document(
                    chat_id=user_id,
                    document=f,
                    caption=f"🎁 Пробный ключ на {config['referral']['trial_days']} дней!"
                )
            
            await query.edit_message_text("✅ Ключ отправлен!")
        else:
            await query.edit_message_text("⚠️ У вас уже есть подписка!")
    
    elif query.data == 'my_key':
        if r.exists(f"user:{user_id}"):
            file_path = f"{config['vpn']['dir']}/client_{user_id}.ovpn"
            if os.path.exists(file_path):
                with open(file_path, 'rb') as f:
                    await query.bot.send_document(chat_id=user_id, document=f, caption="🔑 Ваш VPN конфиг")
                await query.edit_message_text("✅ Конфиг отправлен!")
            else:
                await query.edit_message_text("❌ Файл не найден")
        else:
            await query.edit_message_text("❌ Нет активной подписки")
    
    elif query.data in ['referral_info', 'referral']:
        ref_code = generate_referral_code(user_id)
        ref_link = f"https://t.me/{query.bot.username}?start={ref_code}"
        
        await query.edit_message_text(
            f"👥 *Реферальная программа*\n\n🔗 Ваша ссылка:\n`{ref_link}`\n\n💎 Пригласите друзей и получайте бонусы!",
            parse_mode='Markdown'
        )
    
    elif query.data == 'buy_vpn':
        payment_url = f"https://yoomoney.ru/quickpay/confirm.xml?receiver={config['payment']['yoomoney']['wallet']}&quickpay-form=small&targets=VPN+1+month&paymentType=AC&sum={config['vpn']['price']}&label={user_id}"
        
        keyboard = [
            [InlineKeyboardButton("💳 Оплатить", url=payment_url)],
            [InlineKeyboardButton("✅ Я оплатил", callback_data='check_payment')]
        ]
        
        await query.edit_message_text(
            f"💳 Оплата VPN на 30 дней\nСтоимость: {config['vpn']['price']} руб.\n\n{payment_url}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data == 'check_payment':
        try:
            create_vpn_config(user_id, is_trial=False, days=30)
            file_path = f"{config['vpn']['dir']}/client_{user_id}.ovpn"
            
            with open(file_path, 'rb') as f:
                await query.bot.send_document(
                    chat_id=user_id,
                    document=f,
                    caption="✅ Оплата подтверждена! VPN на 30 дней."
                )
            
            await query.edit_message_text("✅ Оплата подтверждена!")
        except Exception as e:
            await query.edit_message_text("❌ Ошибка создания ключа")

async def check_expired_keys(context: ContextTypes.DEFAULT_TYPE):
    for key in r.scan_iter("user:*"):
        user_data = r.hgetall(key)
        if user_data.get('active') == 'true':
            expiry_date = datetime.fromisoformat(user_data['expires'])
            if datetime.now() > expiry_date:
                user_id = key.split(':')[1]
                client_name = f"client_{user_id}"
                
                if 'server_id' in user_data:
                    server_id = user_data['server_id']
                    current_users = int(r.hget(f"server:{server_id}", 'users') or 1)
                    r.hset(f"server:{server_id}", 'users', max(0, current_users - 1))
                
                for ext in ['.ovpn', '.key', '.crt']:
                    try:
                        os.remove(f"{config['vpn']['dir']}/{client_name}{ext}")
                    except FileNotFoundError:
                        pass
                
                r.hset(key, 'active', 'false')
                
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="⚠️ Ваша подписка истекла. Используйте /start"
                    )
                except TelegramError:
                    pass

async def main():
    application = Application.builder().token(config['tokens']['main']).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    job_queue = application.job_queue
    job_queue.run_repeating(check_expired_keys, interval=86400)
    
    logger.info("Бот запущен!")
    await application.run_polling()

if __name__ == '__main__':
    asyncio.run(main())