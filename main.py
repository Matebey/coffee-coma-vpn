import os
import logging
import secrets
import random
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import yaml
from datetime import datetime, timedelta
import redis
import subprocess

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('/var/log/coffeecoma-bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

try:
    with open('/opt/coffee-coma-vpn/config.yaml') as f:
        config = yaml.safe_load(f)
except Exception as e:
    logger.error(f"Ошибка загрузки config.yaml: {e}")
    exit(1)

try:
    r = redis.Redis(
        host=config['redis']['host'],
        port=config['redis']['port'],
        decode_responses=True,
        socket_timeout=5
    )
    r.ping()
except Exception as e:
    logger.error(f"Ошибка подключения к Redis: {e}")
    exit(1)

def generate_referral_code(user_id: int) -> str:
    code = secrets.token_hex(4).upper()[:8]
    r.set(f"ref:{code}", user_id, ex=2592000)
    r.sadd(f"user:{user_id}:ref_codes", code)
    return code

def get_available_server():
    try:
        servers = []
        for server_id in r.smembers('servers'):
            server_data = r.hgetall(f"server:{server_id}")
            if server_data and server_data.get('status') == 'active':
                servers.append(server_data)
        return random.choice(servers) if servers else None
    except Exception as e:
        logger.error(f"Ошибка получения серверов: {e}")
        return None

def assign_user_to_server(user_id: int, server_id: str):
    try:
        r.hset(f"user:{user_id}", 'server_id', server_id)
        current_users = int(r.hget(f"server:{server_id}", 'users') or 0)
        r.hset(f"server:{server_id}", 'users', current_users + 1)
    except Exception as e:
        logger.error(f"Ошибка привязки пользователя к серверу: {e}")

def setup_traffic_control(server_data):
    try:
        ssh_cmd = ['ssh', '-o', 'StrictHostKeyChecking=no']
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

def create_vpn_config(user_id: int, is_trial: bool = False, days: int = 30) -> str:
    try:
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
        
        # Генерация сертификатов
        subprocess.run([
            'openssl', 'req', '-new', '-newkey', 'rsa:2048', '-days', str(days),
            '-nodes', '-x509', '-keyout', f"{config['vpn']['dir']}/{client_name}.key",
            '-out', f"{config['vpn']['dir']}/{client_name}.crt",
            '-subj', f'/CN={client_name}'
        ], check=True, capture_output=True)
        
        # Чтение CA сертификата
        with open('/etc/openvpn/ca.crt', 'r') as ca_file:
            ca_content = ca_file.read()
        
        # Чтение сертификатов клиента
        with open(f"{config['vpn']['dir']}/{client_name}.crt", 'r') as cert_file:
            cert_content = cert_file.read()
        
        with open(f"{config['vpn']['dir']}/{client_name}.key", 'r') as key_file:
            key_content = key_file.read()
        
        with open('/etc/openvpn/ta.key', 'r') as ta_file:
            ta_content = ta_file.read()
        
        # Создание .ovpn файла
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
{ca_content}
</ca>
<cert>
{cert_content}
</cert>
<key>
{key_content}
</key>
<tls-auth>
{ta_content}
</tls-auth>
key-direction 1
"""
        
        with open(f"{config['vpn']['dir']}/{client_name}.ovpn", 'w') as f:
            f.write(config_content)
        
        # Сохранение в Redis
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
        
        logger.info(f"Создан конфиг для пользователя {user_id} на сервере {server_ip}")
        return f"{config['vpn']['dir']}/{client_name}.ovpn"
        
    except Exception as e:
        logger.error(f"Ошибка создания конфига: {e}")
        raise

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        username = update.effective_user.first_name
        
        logger.info(f"Команда /start от пользователя {user_id} ({username})")
        
        # Проверка реферального кода
        if context.args:
            ref_code = context.args[0]
            referrer_id = r.get(f"ref:{ref_code}")
            
            if referrer_id and referrer_id != str(user_id):
                if not r.exists(f"user:{user_id}"):
                    try:
                        create_vpn_config(user_id, is_trial=True, days=config['referral']['trial_days'])
                        await update.message.reply_text(
                            f"🎉 Добро пожаловать! Вы получили пробный период на {config['referral']['trial_days']} дней!\n"
                            f"Используйте /mykey чтобы получить конфиг VPN."
                        )
                        return
                    except Exception as e:
                        logger.error(f"Ошибка создания пробного конфига: {e}")
                        await update.message.reply_text("❌ Ошибка создания пробного ключа. Попробуйте позже.")
                        return
        
        # Проверка существующего пользователя
        user_exists = r.exists(f"user:{user_id}")
        
        if user_exists:
            user_data = r.hgetall(f"user:{user_id}")
            if user_data.get('active') == 'true':
                expiry_date = datetime.fromisoformat(user_data['expires'])
                days_left = (expiry_date - datetime.now()).days
                
                keyboard = [
                    [InlineKeyboardButton("🔑 Получить ключ", callback_data='my_key')],
                    [InlineKeyboardButton("👥 Реферальная программа", callback_data='referral')],
                    [InlineKeyboardButton("🛒 Купить VPN", callback_data='buy_vpn')]
                ]
                
                await update.message.reply_text(
                    f"☕ С возвращением, {username}!\n"
                    f"Ваша подписка активна еще {days_left} дней\n\n"
                    f"Что хотите сделать?",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                # Подписка истекла
                keyboard = [
                    [InlineKeyboardButton("🛒 Купить VPN", callback_data='buy_vpn')],
                    [InlineKeyboardButton("🎁 Получить пробный период", callback_data='get_trial')]
                ]
                
                await update.message.reply_text(
                    f"⚠️ Ваша подписка истекла.\n\n"
                    f"Вы можете купить VPN или получить пробный период:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        else:
            # Новый пользователь
            keyboard = [
                [InlineKeyboardButton("🎁 Получить пробный период", callback_data='get_trial')],
                [InlineKeyboardButton("👥 Реферальная программа", callback_data='referral_info')]
            ]
            
            await update.message.reply_text(
                f"☕ Добро пожаловать в Coffee Coma VPN, {username}!\n\n"
                f"Получите пробный период на {config['referral']['trial_days']} дней "
                f"или пригласите друга и получите дополнительно {config['referral']['bonus_days']} дней!",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
    except Exception as e:
        logger.error(f"Ошибка в команде /start: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user_id = query.from_user.id
        await query.answer()
        
        logger.info(f"Callback от пользователя {user_id}: {query.data}")
        
        if query.data == 'get_trial':
            if not r.exists(f"user:{user_id}"):
                try:
                    create_vpn_config(user_id, is_trial=True, days=config['referral']['trial_days'])
                    file_path = f"{config['vpn']['dir']}/client_{user_id}.ovpn"
                    
                    with open(file_path, 'rb') as f:
                        await query.bot.send_document(
                            chat_id=user_id,
                            document=f,
                            caption=f"🎁 Ваш пробный ключ на {config['referral']['trial_days']} дней!\n"
                                    f"Установите файл в OpenVPN клиент для подключения."
                        )
                    
                    await query.edit_message_text("✅ Пробный ключ отправлен в личные сообщения!")
                except Exception as e:
                    logger.error(f"Ошибка создания пробного ключа: {e}")
                    await query.edit_message_text("❌ Ошибка создания ключа. Попробуйте позже.")
            else:
                await query.edit_message_text("⚠️ У вас уже есть активная подписка!")
        
        elif query.data == 'my_key':
            if r.exists(f"user:{user_id}"):
                file_path = f"{config['vpn']['dir']}/client_{user_id}.ovpn"
                if os.path.exists(file_path):
                    with open(file_path, 'rb') as f:
                        await query.bot.send_document(
                            chat_id=user_id,
                            document=f,
                            caption="🔑 Ваш VPN конфиг"
                        )
                    await query.edit_message_text("✅ Конфиг отправлен в личные сообщения!")
                else:
                    await query.edit_message_text("❌ Файл конфига не найден. Обратитесь к администратору.")
            else:
                await query.edit_message_text("❌ У вас нет активной подписки. Получите пробный период!")
        
        elif query.data in ['referral_info', 'referral']:
            ref_code = generate_referral_code(user_id)
            ref_link = f"https://t.me/{query.bot.username}?start={ref_code}"
            
            await query.edit_message_text(
                f"👥 *Реферальная программа*\n\n"
                f"🔗 Ваша реферальная ссылка:\n`{ref_link}`\n\n"
                f"💎 Пригласите друзей и получайте:\n"
                f"• +{config['referral']['bonus_days']} дней за каждого приглашенного\n"
                f"• Приглашенный получает {config['referral']['trial_days']} дней пробного периода\n\n"
                f"📊 Приглашено: {r.scard(f'user:{user_id}:ref_codes') or 0} человек",
                parse_mode='Markdown'
            )
        
        elif query.data == 'buy_vpn':
            payment_url = f"https://yoomoney.ru/quickpay/confirm.xml?receiver={config['payment']['yoomoney']['wallet']}&quickpay-form=small&targets=VPN+1+month&paymentType=AC&sum={config['vpn']['price']}&label={user_id}"
            
            keyboard = [
                [InlineKeyboardButton("💳 Оплатить", url=payment_url)],
                [InlineKeyboardButton("✅ Я оплатил", callback_data='check_payment')]
            ]
            
            await query.edit_message_text(
                f"💳 *Оплата VPN на 30 дней*\n\n"
                f"Стоимость: {config['vpn']['price']} руб.\n"
                f"Ссылка для оплаты: {payment_url}\n\n"
                f"После оплаты нажмите '✅ Я оплатил'",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        
        elif query.data == 'check_payment':
            await query.edit_message_text("🔄 Проверяем оплату...")
            
            # Здесь должна быть реализация проверки платежа через ЮMoney API
            # Временно сразу выдаем ключ
            try:
                create_vpn_config(user_id, is_trial=False, days=30)
                file_path = f"{config['vpn']['dir']}/client_{user_id}.ovpn"
                
                with open(file_path, 'rb') as f:
                    await query.bot.send_document(
                        chat_id=user_id,
                        document=f,
                        caption="✅ Оплата подтверждена! Ваш VPN ключ на 30 дней."
                    )
                
                await query.edit_message_text("✅ Оплата подтверждена! Ключ отправлен в личные сообщения.")
            except Exception as e:
                logger.error(f"Ошибка создания платного ключа: {e}")
                await query.edit_message_text("❌ Ошибка создания ключа. Обратитесь к администратору.")
                
    except Exception as e:
        logger.error(f"Ошибка в callback обработчике: {e}")
        try:
            await query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")
        except:
            pass

async def main():
    try:
        logger.info("Запуск основного бота...")
        
        application = Application.builder().token(config['tokens']['main']).build()
        
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("mykey", start))  # Альias для /start
        application.add_handler(CallbackQueryHandler(handle_callback))
        
        logger.info("Бот успешно запущен!")
        await application.run_polling()
        
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")

if __name__ == '__main__':
    asyncio.run(main())
