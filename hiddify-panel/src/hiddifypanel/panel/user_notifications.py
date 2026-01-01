"""
User Notification System
Sends automatic Telegram notifications to users for:
1. Expiry warning (X days before)
2. Usage warning (80% consumed)
3. Subscription ended
"""

import datetime
from celery import shared_task
from loguru import logger

from hiddifypanel.database import db
from hiddifypanel.models import User, hconfig, ConfigEnum
from hiddifypanel import hutils


@shared_task(ignore_result=False)
def check_user_notifications():
    """
    Celery task to check and send notifications to users.
    Only sends to users with telegram_id connected.
    """
    if not hconfig(ConfigEnum.telegram_bot_token):
        return {"status": "skipped", "reason": "No Telegram bot token configured"}
    
    results = {
        "expiry_notifications": 0,
        "usage_notifications": 0,
        "finished_notifications": 0,
        "errors": []
    }
    
    try:
        # Get notification settings
        notify_expiry_enable = hconfig(ConfigEnum.notify_expiry_enable)
        notify_usage_enable = hconfig(ConfigEnum.notify_usage_enable)
        notify_finished_enable = hconfig(ConfigEnum.notify_finished_enable)
        
        try:
            notify_expiry_days = int(hconfig(ConfigEnum.notify_expiry_days) or "3")
        except (ValueError, TypeError):
            notify_expiry_days = 3
        
        try:
            notify_usage_percent = int(hconfig(ConfigEnum.notify_usage_percent) or "80")
        except (ValueError, TypeError):
            notify_usage_percent = 80
        
        # Query users with telegram_id (connected to Telegram)
        users_with_telegram = db.session.query(User).filter(
            User.telegram_id != None,
            User.telegram_id != 0
        ).all()
        
        for user in users_with_telegram:
            try:
                # 1. Check expiry notification
                if notify_expiry_enable and not user.notified_expiry:
                    if user.is_active and 0 < user.remaining_days <= notify_expiry_days:
                        send_expiry_notification(user, user.remaining_days)
                        user.notified_expiry = True
                        results["expiry_notifications"] += 1
                
                # 2. Check usage notification (80%)
                if notify_usage_enable and not user.notified_usage_80:
                    if user.usage_limit > 0:
                        usage_percent = (user.current_usage / user.usage_limit) * 100
                        if usage_percent >= notify_usage_percent:
                            send_usage_notification(user, usage_percent)
                            user.notified_usage_80 = True
                            results["usage_notifications"] += 1
                
                # 3. Check subscription finished notification
                if notify_finished_enable and not user.notified_finished:
                    if not user.is_active and user.start_date is not None:
                        send_finished_notification(user)
                        user.notified_finished = True
                        results["finished_notifications"] += 1
                
                # Reset notification flags when user becomes active again
                if user.is_active:
                    if user.notified_finished:
                        user.notified_finished = False
                    # Reset usage notification if usage is reset
                    if user.usage_limit > 0:
                        usage_percent = (user.current_usage / user.usage_limit) * 100
                        if usage_percent < 50:  # Reset when below 50%
                            user.notified_usage_80 = False
                    # Reset expiry notification if days increased
                    if user.remaining_days > notify_expiry_days:
                        user.notified_expiry = False
                        
            except Exception as e:
                logger.error(f"Error processing notifications for user {user.uuid}: {e}")
                results["errors"].append(f"{user.name}: {str(e)}")
        
        db.session.commit()
        
    except Exception as e:
        logger.exception(f"Error in check_user_notifications: {e}")
        results["errors"].append(str(e))
    
    return results


def send_expiry_notification(user: User, days_remaining: int):
    """Send expiry warning notification to user"""
    from flask_babel import lazy_gettext as _
    from hiddifypanel.panel.commercial.telegrambot import bot, Usage
    
    try:
        msg = _("⚠️ Subscription Expiry Warning") + "\n\n"
        msg += _("Your subscription will expire in %(days)s days.", days=days_remaining) + "\n\n"
        msg += Usage.get_usage_msg(user.uuid)
        
        keyboard = Usage.user_keyboard(user.uuid)
        bot.send_message(user.telegram_id, msg, reply_markup=keyboard)
        logger.info(f"Sent expiry notification to user {user.name} ({user.telegram_id})")
    except Exception as e:
        logger.error(f"Failed to send expiry notification to {user.name}: {e}")
        raise


def send_usage_notification(user: User, usage_percent: float):
    """Send usage warning notification to user"""
    from flask_babel import lazy_gettext as _
    from hiddifypanel.panel.commercial.telegrambot import bot, Usage
    
    try:
        msg = _("📊 Usage Warning") + "\n\n"
        msg += _("You have used %(percent).1f%% of your data allowance.", percent=usage_percent) + "\n\n"
        msg += Usage.get_usage_msg(user.uuid)
        
        keyboard = Usage.user_keyboard(user.uuid)
        bot.send_message(user.telegram_id, msg, reply_markup=keyboard)
        logger.info(f"Sent usage notification to user {user.name} ({user.telegram_id})")
    except Exception as e:
        logger.error(f"Failed to send usage notification to {user.name}: {e}")
        raise


def send_finished_notification(user: User):
    """Send subscription ended notification to user"""
    from flask_babel import lazy_gettext as _
    from hiddifypanel.panel.commercial.telegrambot import bot, Usage
    
    try:
        msg = _("❌ Subscription Ended") + "\n\n"
        
        # Determine why subscription ended
        if user.usage_limit > 0 and user.current_usage >= user.usage_limit:
            msg += _("Your data allowance has been exhausted.") + "\n"
        elif user.remaining_days < 0:
            msg += _("Your subscription time has expired.") + "\n"
        else:
            msg += _("Your subscription has ended.") + "\n"
        
        msg += "\n" + _("Please renew your subscription to continue using the service.") + "\n\n"
        msg += Usage.get_usage_msg(user.uuid)
        
        keyboard = Usage.user_keyboard(user.uuid)
        bot.send_message(user.telegram_id, msg, reply_markup=keyboard)
        logger.info(f"Sent finished notification to user {user.name} ({user.telegram_id})")
    except Exception as e:
        logger.error(f"Failed to send finished notification to {user.name}: {e}")
        raise
