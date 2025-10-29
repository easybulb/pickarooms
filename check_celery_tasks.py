#!/usr/bin/env python
"""Check Celery Beat scheduled tasks"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from django_celery_beat.models import PeriodicTask

print("\n" + "="*60)
print("CELERY BEAT SCHEDULED TASKS")
print("="*60 + "\n")

tasks = PeriodicTask.objects.all().order_by('name')

for task in tasks:
    status = "✅ ENABLED" if task.enabled else "❌ DISABLED"
    print(f"{status} | {task.name}")
    print(f"   Task: {task.task}")
    print(f"   Schedule: {task.crontab or task.interval}")
    print()

print("="*60)
print(f"Total: {tasks.count()} scheduled task(s)")
print("="*60 + "\n")
