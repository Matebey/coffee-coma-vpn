"""Admin handlers for VPN Telegram Bot"""

import logging
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import func, desc

from bot.models.database import DatabaseManager, User, Subscription, Payment
from bot.config.settings import Config
from bot.utils.helpers import (
    is_admin, 
    log_admin_action, 
    format_datetime, 
    format_date,
    format_time_ago,
    StatsCalculator
)
from locales.ru import get_message

logger = logging.getLogger(__name__)

db_manager = DatabaseManager(Config.DATABASE_URL)

# Admin conversation states
WAITING_BROADCAST_MESSAGE = 1


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin panel"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text(get_message('admin_not_authorized'))
        return
    
    session = db_manager.get_session()
    try:
        # Get comprehensive statistics
        total_users = session.query(User).count()
        active_users = session.query(User).filter(
            User.last_activity >= datetime.utcnow() - timedelta(days=7)
        ).count()
        
        active_subscriptions = session.query(Subscription).filter(
            Subscription.is_active == True,
            Subscription.end_date > datetime.utcnow()
        ).count()
        
        # Daily revenue
        today = datetime.utcnow().date()
        daily_revenue = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.completed_at >= today
        ).scalar() or 0
        daily_revenue = daily_revenue / 100  # Convert from kopecks
        
        # Monthly revenue
        start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_revenue = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.completed_at >= start_of_month
        ).scalar() or 0
        monthly_revenue = monthly_revenue / 100  # Convert from kopecks
        
        # New users today
        new_users = session.query(User).filter(
            User.created_at >= today
        ).count()
        
        admin_text = get_message('admin_panel',
            total_users=total_users,
            active_subscriptions=active_subscriptions,
            daily_revenue=int(daily_revenue),
            monthly_revenue=int(monthly_revenue),
            new_users=new_users,
            last_update=format_datetime(datetime.utcnow())
        )
        
        keyboard = [
            [
                InlineKeyboardButton("👥 Пользователи", callback_data='admin_users'),
                InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')
            ],
            [
                InlineKeyboardButton("💰 Платежи", callback_data='admin_payments'),
                InlineKeyboardButton("📢 Рассылка", callback_data='admin_broadcast')
            ],
            [
                InlineKeyboardButton("🔄 Обновить", callback_data='admin_refresh')
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text=admin_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        log_admin_action(user_id, "accessed_admin_panel")
        
    finally:
        session.close()


async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin callback queries"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await query.edit_message_text(get_message('admin_not_authorized'))
        return
    
    action = query.data.replace('admin_', '')
    
    if action == 'refresh':
        await admin_panel_refresh(update, context)
    elif action == 'users':
        await admin_users_list(update, context)
    elif action == 'stats':
        await admin_detailed_stats(update, context)
    elif action == 'payments':
        await admin_payments_list(update, context)
    elif action == 'broadcast':
        await admin_broadcast_start(update, context)
    elif action == 'back':
        await admin_back_to_panel(update, context)
    else:
        await query.edit_message_text(f"❌ Неизвестное действие: {action}")


async def admin_panel_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Refresh admin panel"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    session = db_manager.get_session()
    try:
        # Get fresh statistics
        total_users = session.query(User).count()
        active_subscriptions = session.query(Subscription).filter(
            Subscription.is_active == True,
            Subscription.end_date > datetime.utcnow()
        ).count()
        
        today = datetime.utcnow().date()
        daily_revenue = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.completed_at >= today
        ).scalar() or 0
        daily_revenue = daily_revenue / 100
        
        start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_revenue = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.completed_at >= start_of_month
        ).scalar() or 0
        monthly_revenue = monthly_revenue / 100
        
        new_users = session.query(User).filter(User.created_at >= today).count()
        
        admin_text = get_message('admin_panel',
            total_users=total_users,
            active_subscriptions=active_subscriptions,
            daily_revenue=int(daily_revenue),
            monthly_revenue=int(monthly_revenue),
            new_users=new_users,
            last_update=format_datetime(datetime.utcnow())
        )
        
        keyboard = [
            [
                InlineKeyboardButton("👥 Пользователи", callback_data='admin_users'),
                InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')
            ],
            [
                InlineKeyboardButton("💰 Платежи", callback_data='admin_payments'),
                InlineKeyboardButton("📢 Рассылка", callback_data='admin_broadcast')
            ],
            [
                InlineKeyboardButton("🔄 Обновлено ✅", callback_data='admin_refresh')
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=admin_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        log_admin_action(user_id, "refreshed_admin_panel")
        
    finally:
        session.close()


async def admin_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show users list for admin"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    session = db_manager.get_session()
    try:
        # Get recent users with pagination
        page = context.user_data.get('admin_users_page', 0)
        limit = 10
        offset = page * limit
        
        users = session.query(User).order_by(desc(User.created_at)).offset(offset).limit(limit).all()
        total_users = session.query(User).count()
        
        users_text = f"👥 Пользователи (стр. {page + 1}):\n\n"
        
        for user in users:
            status_emoji = "✅" if user.has_active_subscription else "❌"
            last_activity = format_time_ago(user.last_activity)
            
            users_text += f"{status_emoji} <b>{user.full_name}</b>\n"
            users_text += f"   🆔 ID: <code>{user.telegram_id}</code>\n"
            users_text += f"   👤 @{user.username or 'None'}\n"
            users_text += f"   📅 Регистрация: {format_date(user.created_at)}\n"
            users_text += f"   🕐 Активность: {last_activity}\n"
            users_text += f"   💰 Потрачено: {user.total_spent} ₽\n"
            users_text += f"   🎁 Рефералов: {user.total_referrals}\n\n"
        
        users_text += f"📊 Всего пользователей: {total_users}"
        
        # Navigation buttons
        keyboard = []
        nav_row = []
        
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️ Назад", callback_data=f'admin_users_page_{page-1}'))
        
        if (page + 1) * limit < total_users:
            nav_row.append(InlineKeyboardButton("Вперед ➡️", callback_data=f'admin_users_page_{page+1}'))
        
        if nav_row:
            keyboard.append(nav_row)
        
        keyboard.extend([
            [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=users_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
    finally:
        session.close()


async def admin_detailed_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed statistics"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    session = db_manager.get_session()
    try:
        # Calculate comprehensive stats
        stats = StatsCalculator.calculate_daily_stats()
        
        # User statistics
        total_users = session.query(User).count()
        active_users_week = session.query(User).filter(
            User.last_activity >= datetime.utcnow() - timedelta(days=7)
        ).count()
        active_users_month = session.query(User).filter(
            User.last_activity >= datetime.utcnow() - timedelta(days=30)
        ).count()
        
        # Subscription statistics
        subs_by_plan = session.query(
            Subscription.plan_type,
            func.count(Subscription.id)
        ).filter(
            Subscription.is_active == True,
            Subscription.end_date > datetime.utcnow()
        ).group_by(Subscription.plan_type).all()
        
        # Payment statistics
        total_revenue = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed'
        ).scalar() or 0
        total_revenue = total_revenue / 100
        
        # Weekly revenue
        week_ago = datetime.utcnow() - timedelta(days=7)
        weekly_revenue = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.completed_at >= week_ago
        ).scalar() or 0
        weekly_revenue = weekly_revenue / 100
        
        stats_text = f"📊 <b>Подробная статистика</b>\n\n"
        
        stats_text += f"👥 <b>Пользователи:</b>\n"
        stats_text += f"   • Всего: {total_users}\n"
        stats_text += f"   • Новых сегодня: {stats['new_users']}\n"
        stats_text += f"   • Активных за неделю: {active_users_week}\n"
        stats_text += f"   • Активных за месяц: {active_users_month}\n\n"
        
        stats_text += f"📱 <b>Подписки:</b>\n"
        stats_text += f"   • Активных: {stats['active_subscriptions']}\n"
        for plan_type, count in subs_by_plan:
            plan_name = plan_type.replace('_', ' ').title()
            stats_text += f"   • {plan_name}: {count}\n"
        stats_text += "\n"
        
        stats_text += f"💰 <b>Доходы:</b>\n"
        stats_text += f"   • Сегодня: {stats['daily_revenue']:.0f} ₽\n"
        stats_text += f"   • За неделю: {weekly_revenue:.0f} ₽\n"
        stats_text += f"   • Всего: {total_revenue:.0f} ₽\n"
        stats_text += f"   • Платежей сегодня: {stats['successful_payments']}\n\n"
        
        stats_text += f"🔄 <b>Обновлено:</b> {format_datetime(datetime.utcnow())}"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Обновить", callback_data='admin_stats')],
            [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=stats_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        log_admin_action(user_id, "viewed_detailed_stats")
        
    finally:
        session.close()


async def admin_payments_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show recent payments"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    session = db_manager.get_session()
    try:
        # Get recent payments
        payments = session.query(Payment).order_by(desc(Payment.created_at)).limit(20).all()
        
        payments_text = f"💰 <b>Последние платежи</b>\n\n"
        
        for payment in payments:
            user = session.query(User).filter_by(id=payment.user_id).first()
            status_emoji = {
                'completed': '✅',
                'pending': '⏳',
                'failed': '❌',
                'cancelled': '🚫'
            }.get(payment.status, '❓')
            
            payments_text += f"{status_emoji} <b>{payment.amount_rubles:.0f} ₽</b>\n"
            payments_text += f"   👤 {user.full_name if user else 'Unknown'}\n"
            payments_text += f"   📦 {payment.plan_type.replace('_', ' ').title()}\n"
            payments_text += f"   💳 {payment.payment_method.upper()}\n"
            payments_text += f"   📅 {format_datetime(payment.created_at)}\n\n"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Обновить", callback_data='admin_payments')],
            [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=payments_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
    finally:
        session.close()


async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start broadcast message creation"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    session = db_manager.get_session()
    try:
        total_users = session.query(User).count()
        active_users = session.query(User).filter(
            User.last_activity >= datetime.utcnow() - timedelta(days=30)
        ).count()
        
        broadcast_text = get_message('broadcast_start',
            total_users=total_users,
            active_users=active_users
        )
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=broadcast_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        # Set state for waiting broadcast message
        context.user_data['waiting_broadcast'] = True
        
    finally:
        session.close()


async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle broadcast message from admin"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id) or not context.user_data.get('waiting_broadcast'):
        return
    
    broadcast_message = update.message.text
    context.user_data['waiting_broadcast'] = False
    context.user_data['broadcast_message'] = broadcast_message
    
    session = db_manager.get_session()
    try:
        total_users = session.query(User).count()
        
        confirm_text = get_message('broadcast_confirm',
            recipients=total_users,
            message=broadcast_message
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Отправить всем", callback_data='admin_broadcast_confirm'),
                InlineKeyboardButton("❌ Отмена", callback_data='admin_back')
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text=confirm_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
    finally:
        session.close()


async def admin_broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm and execute broadcast"""
    query = update.callback_query
    await query.answer("📢 Начинаем рассылку...")
    
    user_id = update.effective_user.id
    broadcast_message = context.user_data.get('broadcast_message')
    
    if not broadcast_message:
        await query.edit_message_text("❌ Сообщение для рассылки не найдено")
        return
    
    session = db_manager.get_session()
    try:
        users = session.query(User).all()
        total_users = len(users)
        sent_count = 0
        failed_count = 0
        
        # Update message to show progress
        await query.edit_message_text(
            f"📢 Рассылка запущена...\n\n"
            f"👥 Всего получателей: {total_users}\n"
            f"✅ Отправлено: 0\n"
            f"❌ Ошибок: 0"
        )
        
        # Send messages with progress updates
        for i, user in enumerate(users):
            try:
                await context.bot.send_message(
                    chat_id=user.telegram_id,
                    text=broadcast_message,
                    parse_mode='HTML'
                )
                sent_count += 1
                
                # Update progress every 50 messages
                if (i + 1) % 50 == 0:
                    await query.edit_message_text(
                        f"📢 Рассылка в процессе...\n\n"
                        f"👥 Всего получателей: {total_users}\n"
                        f"✅ Отправлено: {sent_count}\n"
                        f"❌ Ошибок: {failed_count}\n"
                        f"📊 Прогресс: {((i + 1) / total_users * 100):.1f}%"
                    )
                
                # Small delay to avoid rate limits
                await asyncio.sleep(0.1)
                
            except Exception as e:
                failed_count += 1
                logger.warning(f"Failed to send broadcast to user {user.telegram_id}: {e}")
        
        # Final result
        success_text = get_message('broadcast_success', sent=sent_count, total=total_users)
        if failed_count > 0:
            success_text += f"\n❌ Не удалось отправить: {failed_count}"
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=success_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        log_admin_action(user_id, "broadcast_sent", details=f"Sent to {sent_count}/{total_users} users")
        
    finally:
        session.close()


async def admin_back_to_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to admin panel"""
    query = update.callback_query
    await query.answer()
    
    # Clear any admin states
    context.user_data.pop('waiting_broadcast', None)
    context.user_data.pop('broadcast_message', None)
    
    # Show fresh admin panel
    await admin_panel_refresh(update, context)
