import os
import sys
from celery import Celery, Task
from celery.schedules import crontab
from dotenv import dotenv_values
from loguru import logger


def init_app(app):
    class FlaskTask(Task):
        def __call__(self, *args: object, **kwargs: object) -> object:
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    
    celery_app.config_from_object(dict(
        broker_url=app.config['REDIS_URI_MAIN'],
        result_backend=app.config['REDIS_URI_MAIN'],
        # task_ignore_result=True,
    ))
    app.extensions["celery"] = celery_app


        # Calls test('hello') every 10 seconds.
    from hiddifypanel.panel import usage
    celery_app.add_periodic_task(60.0, usage.update_local_usage.s(), name='update usage')
    # celery_app.conf.beat_schedule = {
    # 'update_usage': {
    #     'task': 'hiddifypanel.panel.usage.update_local_usage',
    #     'schedule': 30.0, 

    # },
# }
    from hiddifypanel.panel.cli import backup_task
    from hiddifypanel.models import hconfig, ConfigEnum
    celery_app.autodiscover_tasks()
    # celery_app.add_periodic_task(30.0, backup_task.s(), name='backup task')
    # celery_app.add_periodic_task(
    #     crontab(hour="*/6", minute=30),
    #     backup_task.delay(),
    # )

    # Backup task - runs every 6 hours by default
    # Note: backup_interval config is read at task execution time, not here
    # to avoid calling hconfig() outside app context
    celery_app.add_periodic_task(
        crontab(hour="*/6", minute="0"),
        backup_task.s(),
        name="backup_task"
    )
    
    # User notification task - runs every hour
    from hiddifypanel.panel.user_notifications import check_user_notifications
    celery_app.add_periodic_task(
        crontab(minute="30"),  # Run at :30 every hour
        check_user_notifications.s(),
        name="check_user_notifications"
    )
    
    # Connection limit check task - runs every 2 minutes
    from hiddifypanel.panel.connection_limit import check_connection_limits
    celery_app.add_periodic_task(
        120.0,  # Every 2 minutes
        check_connection_limits.s(),
        name="check_connection_limits"
    )
    
    # User connection log collection task - runs every minute
    from hiddifypanel.hutils.log_parser import collect_logs, cleanup_old_logs
    celery_app.add_periodic_task(
        60.0,  # Every minute
        collect_logs.s(),
        name="collect_user_logs"
    )
    
    # Log cleanup task - runs every hour
    celery_app.add_periodic_task(
        crontab(minute="0"),  # Run at :00 every hour
        cleanup_old_logs.s(),
        name="cleanup_old_logs"
    )
    
    celery_app.set_default()
    return celery_app



def init_app_no_flask():
    config={}
    for c, v in dotenv_values(os.environ.get("HIDDIFY_CFG_PATH", 'app.cfg')).items():
        if v.isdecimal():
            v = int(v)
        else:
            v = True if v.lower() == "true" else (False if v.lower() == "false" else v)
        config[c] = v
    import hiddifypanel.database 
    hiddifypanel.database.init_no_flask()

    from hiddifypanel.panel import init_db
    while not init_db.is_db_latest():
        logger.error("The database upgrade is required before proceeding. Retrying...")
        import time
        time.sleep(20)
    
    logger.info("Starting background tasks")

    celery_app = Celery()
    
    celery_app.config_from_object(dict(
        broker_url=config['REDIS_URI_MAIN'],
        result_backend=config['REDIS_URI_MAIN'],
        # task_ignore_result=True,
    ))
    

    
        # Calls test('hello') every 10 seconds.
    from hiddifypanel.panel import usage
    celery_app.add_periodic_task(60.0, usage.update_local_usage.s(), name='update usage')
    # celery_app.conf.beat_schedule = {
    # 'update_usage': {
    #     'task': 'hiddifypanel.panel.usage.update_local_usage',
    #     'schedule': 30.0, 

    # },
# }
    from hiddifypanel.panel.cli import backup_task
    from hiddifypanel.models import hconfig, ConfigEnum
    celery_app.autodiscover_tasks()
    # celery_app.add_periodic_task(30.0, backup_task.s(), name='backup task')
    # celery_app.add_periodic_task(
    #     crontab(hour="*/6", minute=30),
    #     backup_task.delay(),
    # )

    # Get backup interval from config (default 6 hours, 0 = disabled)
    try:
        backup_interval = int(hconfig(ConfigEnum.backup_interval) or "6")
    except (ValueError, TypeError):
        backup_interval = 6
    
    if backup_interval > 0:
        celery_app.add_periodic_task(
            crontab(hour=f"*/{backup_interval}", minute="0"),
            # crontab(hour="*", minute="*"),
            backup_task.s(),
            name="backup_task"
        )
    
    # User notification task - runs every hour
    from hiddifypanel.panel.user_notifications import check_user_notifications
    celery_app.add_periodic_task(
        crontab(minute="30"),  # Run at :30 every hour
        check_user_notifications.s(),
        name="check_user_notifications"
    )
    
    # Connection limit check task - runs every 2 minutes
    from hiddifypanel.panel.connection_limit import check_connection_limits
    celery_app.add_periodic_task(
        120.0,  # Every 2 minutes
        check_connection_limits.s(),
        name="check_connection_limits"
    )
    
    # User connection log collection task - runs every minute
    from hiddifypanel.hutils.log_parser import collect_logs, cleanup_old_logs
    celery_app.add_periodic_task(
        60.0,  # Every minute
        collect_logs.s(),
        name="collect_user_logs"
    )
    
    # Log cleanup task - runs every hour
    celery_app.add_periodic_task(
        crontab(minute="0"),  # Run at :00 every hour
        cleanup_old_logs.s(),
        name="cleanup_old_logs"
    )
    
    celery_app.set_default()
    
    return celery_app


    