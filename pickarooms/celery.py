"""
Celery configuration for PickARooms project
"""
import os
from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')

app = Celery('pickarooms')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related config keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Celery Beat Schedule
app.conf.beat_schedule = {
    'poll-ical-feeds-every-10-minutes': {
        'task': 'main.tasks.poll_all_ical_feeds',
        'schedule': crontab(minute='*/10'),  # Every 10 minutes
    },
    'archive-past-guests-midday': {
        'task': 'main.tasks.archive_past_guests',
        'schedule': crontab(hour=12, minute=15),  # 12:15 PM UK time - catches default 11 AM checkouts
    },
    'archive-past-guests-afternoon': {
        'task': 'main.tasks.archive_past_guests',
        'schedule': crontab(hour=15, minute=0),  # 3:00 PM UK time - catches late checkouts (up to 2 PM)
    },
    'archive-past-guests-evening': {
        'task': 'main.tasks.archive_past_guests',
        'schedule': crontab(hour=23, minute=0),  # 11:00 PM UK time - end of day safety net
    },
    'cleanup-old-reservations-daily': {
        'task': 'main.tasks.cleanup_old_reservations',
        'schedule': crontab(hour=3, minute=0),  # Daily at 3 AM
    },
}

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
