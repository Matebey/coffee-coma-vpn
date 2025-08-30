from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
import yaml
import redis
import subprocess

with open('config.yaml') as f:
    config = yaml.safe_load(f)

r = redis.Redis(
    host=config['redis']['host'],
    port=config['redis']['port'],
    decode_responses=True
)

def admin_start(update: Update, context: CallbackContext):
    if update.message.from_user.id != config['admin_id']:
        update.message.reply_text("❌ Доступ запрещен!")
        return
    
    keyboard = [
        ["➕ Добавить сервер", "🗑️ Удалить сервер"],
        ["📊 Статистика серверов", "👥 Статистика пользователей"],
        ["🔄 Перезапустить сервер", "🧹 Очистка"],
        ["🌐 Список серверов", "🚦 Управление скоростью"]
    ]
    
    update.message.reply_text(
        "⚙️ *Админ-панель Coffee Coma VPN*",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode='Markdown'
    )

def handle_admin_command(update: Update, context: CallbackContext):
    if update.message.from_user.id != config['admin_id']:
        return
    
    text = update.message.text
    
    if text == "➕ Добавить сервер":
        update.message.reply_text("Введите данные сервера:\n`Название;IP;Порт;Логин;Пароль;Ключ_SSH`")
        context.user_data['awaiting_server'] = True
    
    elif text == "🌐 Список серверов":
        show_servers_list(update)
    
    elif text == "🗑️ Удалить сервер":
        show_servers_for_deletion(update)
    
    elif text == "📊 Статистика серверов":
        show_servers_stats(update)
    
    elif text == "👥 Статистика пользователей":
        show_users_stats(update)
    
    elif text == "🔄 Перезапустить сервер":
        show_servers_for_restart(update)
    
    elif text == "🚦 Управление скоростью":
        keyboard = [["🚀 Включить ограничения", "🐢 Выключить ограничения"]]
        update.message.reply_text(
            "🚦 Управление ограничениями скорости",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
    
    elif text == "🚀 Включить ограничения":
        for server_id in r.smembers('servers'):
            server_data = r.hgetall(f"server:{server_id}")
            setup_traffic_control(server_data)
        update.message.reply_text("✅ Ограничения скорости включены")
    
    elif text == "🐢 Выключить ограничения":
        for server_id in r.smembers('servers'):
            server_data = r.hgetall(f"server:{server_id}")
            disable_traffic_control(server_data)
        update.message.reply_text("✅ Ограничения скорости выключены")

def setup_traffic_control(server_data):
    try:
        ssh_cmd = ['ssh']
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
        ssh_cmd = ['ssh']
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

def show_servers_list(update: Update):
    servers = []
    for server_id in r.smembers('servers'):
        server_data = r.hgetall(f"server:{server_id}")
        status = "🟢" if server_data.get('status') == 'active' else "🔴"
        users = server_data.get('users', '0')
        servers.append(f"{status} {server_data.get('name')} - {users} пользователей")
    
    update.message.reply_text("🌐 Серверы:\n" + "\n".join(servers) if servers else "❌ Серверы не найдены")

def show_servers_stats(update: Update):
    total_servers = len(r.smembers('servers'))
    active_servers = sum(1 for sid in r.smembers('servers') if r.hget(f"server:{sid}", 'status') == 'active')
    total_users = sum(int(r.hget(f"server:{sid}", 'users') or 0) for sid in r.smembers('servers'))
    
    update.message.reply_text(
        f"📊 Статистика:\nСерверов: {total_servers}\nАктивных: {active_servers}\nПользователей: {total_users}"
    )

def show_users_stats(update: Update):
    total_users = len(r.keys("user:*"))
    active_users = sum(1 for key in r.keys("user:*") if r.hget(key, 'active') == 'true')
    paid_users = sum(1 for key in r.keys("user:*") if r.hget(key, 'is_trial') == 'False')
    
    update.message.reply_text(
        f"👥 Пользователи:\nВсего: {total_users}\nАктивных: {active_users}\nПлатных: {paid_users}"
    )

def show_servers_for_deletion(update: Update):
    servers = []
    for server_id in r.smembers('servers'):
        server_data = r.hgetall(f"server:{server_id}")
        servers.append([InlineKeyboardButton(
            f"{server_data.get('name')} ({server_data.get('ip')})",
            callback_data=f"delete_server:{server_id}"
        )])
    
    if servers:
        update.message.reply_text("🗑️ Выберите сервер для удаления:", reply_markup=InlineKeyboardMarkup(servers))
    else:
        update.message.reply_text("❌ Серверы не найдены")

def show_servers_for_restart(update: Update):
    servers = []
    for server_id in r.smembers('servers'):
        server_data = r.hgetall(f"server:{server_id}")
        servers.append([InlineKeyboardButton(
            f"{server_data.get('name')} ({server_data.get('ip')})",
            callback_data=f"restart_server:{server_id}"
        )])
    
    if servers:
        update.message.reply_text("🔄 Выберите сервер для перезагрузки:", reply_markup=InlineKeyboardMarkup(servers))
    else:
        update.message.reply_text("❌ Серверы не найдены")

def handle_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    if query.data.startswith('delete_server:'):
        server_id = query.data.split(':')[1]
        server_data = r.hgetall(f"server:{server_id}")
        r.delete(f"server:{server_id}")
        r.srem('servers', server_id)
        query.edit_message_text(f"✅ Сервер {server_data.get('name')} удален!")
    
    elif query.data.startswith('restart_server:'):
        server_id = query.data.split(':')[1]
        server_data = r.hgetall(f"server:{server_id}")
        try:
            ssh_cmd = ['ssh']
            if server_data.get('ssh_key'):
                ssh_cmd.extend(['-i', server_data['ssh_key']])
            ssh_cmd.extend([
                f"{server_data['user']}@{server_data['ip']}",
                'systemctl restart openvpn@server'
            ])
            subprocess.run(ssh_cmd, check=True)
            query.edit_message_text(f"✅ Сервер {server_data.get('name')} перезагружен!")
        except:
            query.edit_message_text(f"❌ Ошибка перезагрузки сервера")

def handle_server_input(update: Update, context: CallbackContext):
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
            
            update.message.reply_text(f"✅ Сервер {server_name} добавлен!")
            del context.user_data['awaiting_server']
            
        except Exception as e:
            update.message.reply_text(f"❌ Ошибка: {e}")

def main():
    updater = Updater(config['tokens']['admin'])
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler('admin', admin_start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_admin_command))
    dp.add_handler(MessageHandler(Filters.text, handle_server_input))
    dp.add_handler(CallbackQueryHandler(handle_callback))
    
    print("Админ-бот запущен!")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()