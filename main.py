import os
import logging
import secrets
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext
import yaml
from datetime import datetime, timedelta
import redis
import subprocess

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка конфига
with open('config.yaml') as f:
    config = yaml.safe_load(f)

# Подключение к Redis
r = redis.Redis(
    host=config['redis']['host'],
    port=config['redis']['port'],
    decode_responses=True
)

def generate_referral_code(user_id: int) -> str:
    """Генерация реферального кода"""
    code = secrets.token_hex(4).upper()[:8]
    r.set(f"ref:{code}", user_id, ex=2592000)  # 30 дней
    r.sadd(f"user:{user_id}:ref_codes", code)
    return code

def create_vpn_config(user_id: int, is_trial: bool = False, days: int = 30) -> str:
    """Создание VPN конфига"""
    client_name = f"client_{user_id}"
    expiry_date = datetime.now() + timedelta(days=days)
    
    # Создание директории если нет
    os.makedirs(config['vpn']['dir'], exist_ok=True)
    
    # Генерация сертификатов
    subprocess.run([
        'openssl', 'req', '-new', '-newkey', 'rsa:2048', '-days', str(days),
        '-nodes', '-x509', '-keyout', f"{config['vpn']['dir']}/{client_name}.key",
        '-out', f"{config['vpn']['dir']}/{client_name}.crt",
        '-subj', f'/CN={client_name}'
    ], check=True)
    
    # Создание .ovpn файла
    config_content = f"""client
dev tun
proto udp
remote {config['vpn']['server_ip']} {config['vpn']['default_port']}
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
    
    # Сохранение в Redis
    r.hset(f"user:{user_id}", mapping={
        'created': datetime.now().isoformat(),
        'expires': expiry_date.isoformat(),
        'active': 'true',
        'is_trial': str(is_trial),
        'days': str(days)
    })
    
    return f"{config['vpn']['dir']}/{client_name}.ovpn"

def extend_user_subscription(user_id: int, additional_days: int):
    """Продление подписки пользователя"""
    user_data = r.hgetall(f"user:{user_id}")
    if user_data:
        current_expiry = datetime.fromisoformat(user_data['expires'])
        new_expiry = current_expiry + timedelta(days=additional_days)
        r.hset(f"user:{user_id}", 'expires', new_expiry.isoformat())
        return new_expiry
    return None

def start(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    username = update.effective_user.first_name
    
    # Проверка реферального кода
    if context.args:
        ref_code = context.args[0]
        referrer_id = r.get(f"ref:{ref_code}")
        
        if referrer_id and referrer_id != str(user_id):
            # Проверяем, новый ли пользователь
            if not r.exists(f"user:{user_id}"):
                # Создание пробного ключа для нового пользователя
                create_vpn_config(user_id, is_trial=True, days=config['referral']['trial_days'])
                
                # Продление подписки реферера
                new_expiry = extend_user_subscription(int(referrer_id), config['referral']['bonus_days'])
                
                # Уведомление реферера
                try:
                    context.bot.send_message(
                        chat_id=referrer_id,
                        text=f"🎉 По вашей реферальной ссылке зарегистрировался новый пользователь!\n"
                             f"Ваша подписка продлена на {config['referral']['bonus_days']} дней.\n"
                             f"Новая дата окончания: {new_expiry.strftime('%d.%m.%Y')}"
                    )
                except:
                    logger.warning(f"Не удалось уведомить реферера {referrer_id}")
                
                update.message.reply_text(
                    f"🎉 Добро пожаловать! Вы получили пробный период на {config['referral']['trial_days']} дней!\n"
                    f"Используйте /mykey чтобы получить конфиг VPN."
                )
                return
    
    # Обычный старт для существующих пользователей
    if r.exists(f"user:{user_id}"):
        user_data = r.hgetall(f"user:{user_id}")
        expiry_date = datetime.fromisoformat(user_data['expires'])
        days_left = (expiry_date - datetime.now()).days
        
        keyboard = [
            [InlineKeyboardButton("🔑 Мой ключ", callback_data='my_key')],
            [InlineKeyboardButton("👥 Реферальная программа", callback_data='referral')],
            [InlineKeyboardButton("🛒 Купить VPN", callback_data='buy_vpn')]
        ]
        
        update.message.reply_text(
            f"☕ С возвращением, {username}!\n"
            f"Ваша подписка активна еще {days_left} дней\n\n"
            f"Что хотите сделать?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        # Новый пользователь
        keyboard = [
            [InlineKeyboardButton("🎁 Получить пробный период", callback_data='get_trial')],
            [InlineKeyboardButton("👥 Реферальная программа", callback_data='referral_info')]
        ]
        
        update.message.reply_text(
            f"☕ Добро пожаловать в Coffee Coma VPN, {username}!\n\n"
            f"Получите пробный период на {config['referral']['trial_days']} дней "
            f"или пригласите друга и получите дополнительно {config['referral']['bonus_days']} дней!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

def handle_callback(update: Update, context: CallbackContext) -> None:
    """Обработчик callback кнопок"""
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    
    if query.data == 'get_trial':
        if not r.exists(f"user:{user_id}"):
            create_vpn_config(user_id, is_trial=True, days=config['referral']['trial_days'])
            file_path = f"{config['vpn']['dir']}/client_{user_id}.ovpn"
            
            with open(file_path, 'rb') as f:
                query.bot.send_document(
                    chat_id=user_id,
                    document=f,
                    caption=f"🎁 Ваш пробный ключ на {config['referral']['trial_days']} дней!\n"
                            f"Установите файл в OpenVPN клиент для подключения."
                )
            
            query.edit_message_text("✅ Пробный ключ отправлен в личные сообщения!")
        else:
            query.edit_message_text("⚠️ У вас уже есть активная подписка!")
    
    elif query.data == 'my_key':
        if r.exists(f"user:{user_id}"):
            file_path = f"{config['vpn']['dir']}/client_{user_id}.ovpn"
            if os.path.exists(file_path):
                with open(file_path, 'rb') as f:
                    query.bot.send_document(
                        chat_id=user_id,
                        document=f,
                        caption="🔑 Ваш VPN конфиг"
                    )
                query.edit_message_text("✅ Конфиг отправлен в личные сообщения!")
            else:
                query.edit_message_text("❌ Файл конфига не найден. Обратитесь к администратору.")
        else:
            query.edit_message_text("❌ У вас нет активной подписки. Получите пробный период!")
    
    elif query.data == 'referral_info':
        ref_code = generate_referral_code(user_id)
        ref_link = f"https://t.me/{query.bot.username}?start={ref_code}"
        
        query.edit_message_text(
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
        
        query.edit_message_text(
            f"💳 *Оплата VPN на 30 дней*\n\n"
            f"Стоимость: {config['vpn']['price']} руб.\n"
            f"Ссылка для оплаты: {payment_url}\n\n"
            f"После оплаты нажмите '✅ Я оплатил'",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

def check_expired_keys(context: CallbackContext):
    """Проверка и удаление просроченных ключей"""
    for key in r.scan_iter("user:*"):
        user_data = r.hgetall(key)
        if user_data.get('active') == 'true':
            expiry_date = datetime.fromisoformat(user_data['expires'])
            if datetime.now() > expiry_date:
                user_id = key.split(':')[1]
                client_name = f"client_{user_id}"
                
                # Удаление файлов
                for ext in ['.ovpn', '.key', '.crt']:
                    try:
                        os.remove(f"{config['vpn']['dir']}/{client_name}{ext}")
                    except FileNotFoundError:
                        pass
                
                # Обновление статуса
                r.hset(key, 'active', 'false')
                
                # Уведомление пользователя
                try:
                    context.bot.send_message(
                        chat_id=user_id,
                        text="⚠️ Ваша VPN подписка истекла. Для продления используйте /start"
                    )
                except:
                    pass

def main():
    """Запуск бота"""
    updater = Updater(config['tokens']['main'])
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CallbackQueryHandler(handle_callback))
    
    # Планировщик задач
    jq = updater.job_queue
    jq.run_repeating(check_expired_keys, interval=86400)  # Ежедневно
    
    logger.info("Бот запущен!")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()