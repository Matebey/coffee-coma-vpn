import os
import logging
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import yaml
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

async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != config['admin_id']:
        await update.message.reply_text("❌ Доступ запрещен!")
        return
    
    keyboard = [
        ["➕ Добавить сервер", "🗑️ Удалить сервер"],
        ["📊 Статистика серверов", "👥 Статистика пользователей"],
        ["🔄 Перезапустить сервер", "🧹 Очистка"],
        ["🌐 Список серверов", "🚦 Управление скоростью"]
    ]
    
    await update.message.reply_text(
        "⚙️ *Админ-панель Coffee Coma VPN*",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode='Markdown'
    )

async def handle_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != config['admin_id']:
        return
    
    text = update.message.text
    
    if text == "➕ Добавить сервер":
        await update.message.reply_text("Введите данные сервера:\n`Название;IP;Порт;Логин;Пароль;Ключ_SSH`")
        context.user_data['awaiting_server'] = True
    
    elif text == "🌐 Список серверов":
        await show_servers_list(update)
    
    elif text == "🗑️ Удалить сервер":
        await show_servers_for_deletion(update)
    
    elif text == "📊 Статистика серверов":
        await show_servers_stats(update)
    
    elif text == "👥 Статистика пользователей":
        await show_users_stats(update)
    
    elif text == "🔄 Перезапустить сервер":
        await show_servers_for_restart(update)
    
    elif text == "🚦 Управление скоростью":
        keyboard = [["🚀 Включить ограничения", "🐢 Выключить ограничения"]]
        await update.message.reply_text(
            "🚦 Управление ограничениями скорости",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
    
    elif text == "🚀 Включить ограничения":
        for server_id in r.smembers('servers'):
            server_data = r.hgetall(f"server:{server_id}")
            setup_traffic_control(server_data)
        await update.message.reply_text("✅ Ограничения скорости включены")
    
    elif text == "🐢 Выключить ограничения":
        for server_id in r.smembers('servers'):
            server_data = r.hgetall(f"server:{server_id}")
            disable_traffic_control(server_data)
        await update.message.reply_text("✅ Ограничения скорости выключены")

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
        subprocess.run(ssh_cmd, capture_output=True, timeout=30)
        return True
    except:
        return False

def disable_traffic_control(server_data):
    try:
        ssh_cmd = ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'BatchMode=yes']
        if server_data.get('ssh_key'):
            ssh_cmd.extend(['-i', server_data['ssh_key']])
        elif server_data.get('password'):
            ssh_cmd = ['sshpass', '-p', server_data['password']] + ssh_cmd
        
        ssh_cmd.extend([
            f"{server_data['user']}@{server_data['ip']}",
            '/etc/openvpn/scripts/traffic_control.sh clean'
        ])
        subprocess.run(ssh_cmd, capture_output=True, timeout=30)
        return True
    except:
        return False

async def show_servers_list(update: Update):
    servers = []
    for server_id in r.smembers('servers'):
        server_data = r.hgetall(f"server:{server_id}")
        status = "🟢" if server_data.get('status') == 'active' else "🔴"
        users = server_data.get('users', '0')
        servers.append(f"{status} {server_data.get('name')} - {users} пользователей")
    
    await update.message.reply_text("🌐 Серверы:\n" + "\n".join(servers) if servers else "❌ Серверы не найдены")

async def show_servers_stats(update: Update):
    total_servers = len(r.smembers('servers'))
    active_servers = sum(1 for sid in r.smembers('servers') if r.hget(f"server:{sid}", 'status') == 'active')
    total_users = sum(int(r.hget(f"server:{sid}", 'users') or 0) for sid in r.smembers('servers'))
    
    await update.message.reply_text(
        f"📊 Статистика:\nСерверов: {total_servers}\nАктивных: {active_servers}\nПользователей: {total_users}"
    )

async def show_users_stats(update: Update):
    total_users = len(r.keys("user:*"))
    active_users = sum(1 for key in r.keys("user:*") if r.hget(key, 'active') == 'true')
    paid_users = sum(1 for key in r.keys("user:*") if r.hget(key, 'is_trial') == 'False')
    
    await update.message.reply_text(
        f"👥 Пользователи:\nВсего: {total_users}\nАктивных: {active_users}\nПлатных: {paid_users}"
    )

async def show_servers_for_deletion(update: Update):
    servers = []
    for server_id in r.smembers('servers'):
        server_data = r.hgetall(f"server:{server_id}")
        servers.append([InlineKeyboardButton(
            f"{server_data.get('name')} ({server_data.get('ip')})",
            callback_data=f"delete_server:{server_id}"
        )])
    
    if servers:
        await update.message.reply_text("🗑️ Выберите сервер для удаления:", reply_markup=InlineKeyboardMarkup(servers))
    else:
        await update.message.reply_text("❌ Серверы не найдены")

async def show_servers_for_restart(update: Update):
    servers = []
    for server_id in r.smembers('servers'):
        server_data = r.hgetall(f"server:{server_id}")
        servers.append([InlineKeyboardButton(
            f"{server_data.get('name')} ({server_data.get('ip')})",
            callback_data=f"restart_server:{server_id}"
        )])
    
    if servers:
        await update.message.reply_text("🔄 Выберите сервер для перезагрузки:", reply_markup=InlineKeyboardMarkup(servers))
    else:
        await update.message.reply_text("❌ Серверы не найдены")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith('delete_server:'):
        server_id = query.data.split(':')[1]
        server_data = r.hgetall(f"server:{server_id}")
        r.delete(f"server:{server_id}")
        r.srem('servers', server_id)
        await query.edit_message_text(f"✅ Сервер {server_data.get('name')} удален!")
    
    elif query.data.startswith('restart_server:'):
        server_id = query.data.split(':')[1]
        server_data = r.hgetall(f"server:{server_id}")
        try:
            ssh_cmd = ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'BatchMode=yes']
            if server_data.get('ssh_key'):
                ssh_cmd.extend(['-i', server_data['ssh_key']])
            ssh_cmd.extend([
                f"{server_data['user']}@{server_data['ip']}",
                'systemctl restart openvpn@server'
            ])
            subprocess.run(ssh_cmd, check=True)
            await query.edit_message_text(f"✅ Сервер {server_data.get('name')} перезагружен!")
        except:
            await query.edit_message_text(f"❌ Ошибка перезагрузки сервера")

async def handle_server_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'awaiting_server' in context.user_data:
        try:
            data = update.message.text.split(';')
            server_name, server_ip, server_port, server_user = data[0], data[1], data[2], data[3]
            server_password = data[4] if len(data) > 4 else ""
            ssh_key = data[5] if len(data) > 5 else ""
            
            server_id = f"server_{len(r.smembers('servers')) + 1}"
            server_data = {
                'id': server_id, 'name': server_name, 'ip': server_ip, 'port': server_port,
                'user': server_user, 'password': server_password, 'ssh_key': ssh_key,
                'status': 'active', 'users': '0'
            }
            
            r.hset(f"server:{server_id}", mapping=server_data)
            r.sadd('servers', server_id)
            setup_traffic_control(server_data)
            
            await update.message.reply_text(f"✅ Сервер {server_name} добавлен!")
            del context.user_data['awaiting_server']
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")

async def main():
    application = Application.builder().token(config['tokens']['admin']).build()
    
    application.add_handler(CommandHandler('admin', admin_start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_command))
    application.add_handler(MessageHandler(filters.TEXT, handle_server_input))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    logger.info("Админ-бот запущен!")
    await application.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())