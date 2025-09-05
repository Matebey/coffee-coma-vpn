from config import load_config
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, MessageHandler, filters
import datetime
import tempfile
import logging
from config import load_config, is_admin
from database import (
    init_db, get_user_configs, add_user, add_payment, 
    get_user_config_count, has_trial_used, get_stats
)
from openvpn_manager import create_ovpn_client_certificate, generate_ovpn_client_config, encrypt_data
from utils import generate_config_name, generate_qr_code, calculate_expiration_date

logger = logging.getLogger(__name__)

# Состояния для обработки скриншотов оплаты
PAYMENT_VERIFICATION = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "Unknown"
        
        # Инициализация БД если нужно
        init_db()
        
        keyboard = [
            [InlineKeyboardButton("💰 Купить доступ (50 руб.)", callback_data='buy')],
            [InlineKeyboardButton("🎁 Бесплатный пробный период (7 дней)", callback_data='trial')],
            [InlineKeyboardButton("📱 Мои конфиги", callback_data='my_configs')],
            [InlineKeyboardButton("❓ Помощь", callback_data='help')]
        ]
        
        if is_admin(user_id):
            keyboard.append([InlineKeyboardButton("👑 Админ панель", callback_data='admin')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🔒 Добро пожаловать в OpenVPN сервис!\n\n"
            "✅ Защита вашего соединения\n"
            "🌍 Доступ к любым ресурсам\n"
            "⚡ Высокая скорость\n\n"
            "Выберите действие:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Start command error: {e}")

async def show_my_configs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        configs = get_user_configs(user_id)
        
        if configs:
            text = "📱 Ваши конфигурации:\n\n"
            for config in configs:
                status_emoji = "✅" if config[1] == 'active' else "❌"
                config_type = "🎁 Пробный" if config[3] == 1 else "💳 Платный"
                text += f"{status_emoji} {config_type} - {config[0]}\n"
                if config[2]:
                    text += f"⏰ До: {config[2]}\n"
                text += "\n"
        else:
            text = "У вас пока нет конфигураций.\n\nИспользуйте пробный период или купите доступ!"
        
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"My configs error: {e}")
        await update.message.reply_text("❌ Ошибка при загрузке конфигураций")

async def show_payment_methods(query, context):
    try:
        config = load_config()
        user_id = query.from_user.id
        
        PAYMENT_VERIFICATION[user_id] = {'status': 'waiting_screenshot'}
        
        payment_text = f"""
💳 Оплата доступа

Стоимость: {config['price']} руб.
Срок действия: 30 дней

📲 Оплата по СБП:
1. Переведите {config['price']} руб. на наш счет
2. Сделайте скриншот перевода
3. Отправьте скриншот в этот чат

💳 Реквизиты для перевода:
{config['wallet_number']}

После проверки оплаты вы получите конфиг файл.
        """
        
        await context.bot.send_message(chat_id=user_id, text=payment_text)
        
    except Exception as e:
        logger.error(f"Payment methods error: {e}")

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "Unknown"
        
        if user_id not in PAYMENT_VERIFICATION or PAYMENT_VERIFICATION[user_id]['status'] != 'waiting_screenshot':
            return
        
        if update.message.photo:
            photo = update.message.photo[-1]
            file_id = photo.file_id
            
            file = await context.bot.get_file(file_id)
            screenshot_path = f"payment_{user_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            await file.download_to_drive(screenshot_path)
            
            PAYMENT_VERIFICATION[user_id] = {
                'status': 'verifying',
                'screenshot_path': screenshot_path,
                'timestamp': datetime.datetime.now()
            }
            
            result = await create_user_config(user_id, username, is_trial=False)
            
            if result['success']:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"✅ Оплата подтверждена! Доступ активирован на 30 дней.\n\n"
                         f"🔧 Имя конфига: {result['config_name']}\n"
                         f"⏰ Действует до: {result['expires_at']}"
                )
                
                if result['qr_buffer']:
                    await context.bot.send_photo(
                        chat_id=user_id,
                        photo=result['qr_buffer'],
                        caption="QR код для импорта в OpenVPN"
                    )
                
                with tempfile.NamedTemporaryFile(mode='w+', suffix='.ovpn', delete=False) as temp_file:
                    temp_file.write(result['config'])
                    temp_file.flush()
                    
                    with open(temp_file.name, 'rb') as config_file:
                        await context.bot.send_document(
                            chat_id=user_id,
                            document=config_file,
                            filename=f"{result['config_name']}.ovpn",
                            caption="Конфигурационный файл OpenVPN"
                        )
                
                config = load_config()
                for admin_id in config['admin_ids']:
                    try:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=f"💰 Новый платеж!\n\n"
                                 f"👤 User ID: {user_id}\n"
                                 f"👤 Username: @{username}\n"
                                 f"💳 Сумма: {config['price']} руб.\n"
                                 f"📅 Время: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        )
                    except Exception as admin_error:
                        logger.error(f"Admin notification error: {admin_error}")
                
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="❌ Ошибка при создании конфига. Свяжитесь с администратором."
                )
            
            if user_id in PAYMENT_VERIFICATION:
                del PAYMENT_VERIFICATION[user_id]
                
    except Exception as e:
        logger.error(f"Screenshot handler error: {e}")

async def create_trial_config(query, context):
    try:
        user_id = query.from_user.id
        username = query.from_user.username or "Unknown"
        
        if has_trial_used(user_id):
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Вы уже использовали пробный период"
            )
            return
        
        result = await create_user_config(user_id, username, is_trial=True)
        
        if result['success']:
            config = load_config()
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎁 Пробный период активирован на {config['trial_days']} дней!\n\n"
                     f"🔧 Имя конфига: {result['config_name']}\n"
                     f"⏰ Действует до: {result['expires_at']}"
            )
            
            if result['qr_buffer']:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=result['qr_buffer'],
                    caption="QR код для импорта в OpenVPN"
                )
            
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.ovpn', delete=False) as temp_file:
                temp_file.write(result['config'])
                temp_file.flush()
                
                with open(temp_file.name, 'rb') as config_file:
                    await context.bot.send_document(
                        chat_id=user_id,
                        document=config_file,
                        filename=f"{result['config_name']}.ovpn",
                        caption="Конфигурационный файл OpenVPN"
                    )
                    
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Ошибка при создании пробного конфига"
            )
            
    except Exception as e:
        logger.error(f"Trial config error: {e}")
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="❌ Произошла ошибка при создании конфига"
        )

async def help_command(query, context):
    help_text = """
🤖 **OpenVPN Bot - Помощь**

📋 **Доступные команды:**
/start - Главное меню
/myconfigs - Мои конфигурации

💡 **Как использовать:**
1. Нажмите «Бесплатный пробный период»
2. Получите конфиг и QR код
3. Импортируйте в приложение OpenVPN

📱 **Приложения:**
- OpenVPN Connect (iOS/Android)
- OpenVPN GUI (Windows)
- Tunnelblick (macOS)

💳 **Оплата:**
- Оплата по СБП
- Отправьте скриншот перевода
- Получите конфиг после проверки

❓ **Проблемы?** Свяжитесь с администратором
"""
    await context.bot.send_message(chat_id=query.from_user.id, text=help_text)

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Доступ запрещен")
        return
    
    config = load_config()
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("⚙️ Настройки", callback_data='admin_settings')],
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👑 Админ панель\n\n"
        f"🌐 Сервер: {config['server_ip']}:{config['server_port']}\n"
        f"💰 Цена: {config['price']} руб.\n"
        f"🎁 Пробный: {config['trial_days']} дней",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        if query.data == 'buy':
            await show_payment_methods(query, context)
        elif query.data == 'trial':
            await create_trial_config(query, context)
        elif query.data == 'my_configs':
            await show_my_configs_callback(query, context)
        elif query.data == 'help':
            await help_command(query, context)
        elif query.data == 'admin':
            await admin_command_callback(query, context)
        elif query.data == 'admin_stats':
            await admin_stats(query, context)
            
    except Exception as e:
        logger.error(f"Button handler error: {e}")

async def show_my_configs_callback(query, context):
    try:
        user_id = query.from_user.id
        configs = get_user_configs(user_id)
        
        if configs:
            text = "📱 Ваши конфигурации:\n\n"
            for config in configs:
                status_emoji = "✅" if config[1] == 'active' else "❌"
                config_type = "🎁 Пробный" if config[3] == 1 else "💳 Платный"
                text += f"{status_emoji} {config_type} - {config[0]}\n"
                if config[2]:
                    text += f"⏰ До: {config[2]}\n"
                text += "\n"
        else:
            text = "У вас пока нет конфигураций.\n\nИспользуйте пробный период или купите доступ!"
        
        await context.bot.send_message(chat_id=user_id, text=text)
    except Exception as e:
        logger.error(f"My configs callback error: {e}")

async def admin_command_callback(query, context):
    if not is_admin(query.from_user.id):
        await context.bot.send_message(chat_id=query.from_user.id, text="❌ Доступ запрещен")
        return
    
    config = load_config()
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("⚙️ Настройки", callback_data='admin_settings')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=f"👑 Админ панель\n\nСервер: {config['server_ip']}:{config['server_port']}",
        reply_markup=reply_markup
    )

async def admin_stats(query, context):
    if not is_admin(query.from_user.id):
        return
    
    try:
        stats = get_stats()
        config = load_config()
        
        stats_text = f"""
📊 Статистика бота:

👥 Всего пользователей: {stats['total_users']}
🎁 Пробных: {stats['trial_users']}
💳 Платных: {stats['paid_users']}
✅ Активных: {stats['active_users']}
💰 Общая выручка: {stats['total_revenue']} руб.

⚙️ Настройки:
💰 Цена: {config['price']} руб.
⏰ Пробный период: {config['trial_days']} дней
🌐 Сервер: {config['server_ip']}:{config['server_port']}
        """
        
        await context.bot.send_message(chat_id=query.from_user.id, text=stats_text)
    except Exception as e:
        logger.error(f"Admin stats error: {e}")

async def create_user_config(user_id, username, is_trial=False):
    try:
        config = load_config()
        
        # Проверяем максимальное количество конфигов
        user_config_count = get_user_config_count(user_id)
        max_configs = config.get('max_configs_per_user', 3)
        
        if user_config_count >= max_configs:
            return {'success': False, 'error': f'Превышено максимальное количество конфигов ({max_configs}) на пользователя'}
        
        # Создаем сертификат и ключи
        client_name, private_key, certificate = create_ovpn_client_certificate(username)
        if not private_key or not certificate:
            return {'success': False, 'error': 'Certificate generation failed'}
        
        # Расчет даты окончания
        expires_at = calculate_expiration_date(is_trial)
        config_name = generate_config_name(user_id)
        
        # Шифрование и сохранение
        encrypted_private_key = encrypt_data(private_key)
        encrypted_certificate = encrypt_data(certificate)
        
        add_user(user_id, username, config_name, encrypted_private_key, 
                encrypted_certificate, int(is_trial), int(not is_trial), expires_at)
        
        if not is_trial:
            add_payment(user_id, config['price'], 'sbp', 'completed')
        
        # Генерация конфига
        client_config = generate_ovpn_client_config(client_name, private_key, certificate)
        qr_buffer = generate_qr_code(client_config, config_name)
        
        return {
            'success': True,
            'config': client_config,
            'qr_buffer': qr_buffer,
            'config_name': config_name,
            'expires_at': expires_at,
            'client_name': client_name
        }
            
    except Exception as e:
        logger.error(f"Create config error: {e}")
        return {'success': False, 'error': str(e)}
