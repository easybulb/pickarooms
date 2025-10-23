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

# NOTE: Celery Beat Schedule is now managed via Django Admin (django-celery-beat)
# This allows dynamic schedule changes without redeployment
# Schedule configured in: pickarooms/settings.py CELERY_BEAT_SCHEDULE
# All periodic tasks should be configured there or via Django Admin

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
