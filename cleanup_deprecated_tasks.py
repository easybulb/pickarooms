"""
Cleanup script for deprecated Celery tasks
Run this to check for any orphaned tasks in Celery Beat database
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from django_celery_beat.models import PeriodicTask, CrontabSchedule

print("=" * 70)
print("CELERY BEAT TASK AUDIT")
print("=" * 70)

# Get all periodic tasks
all_tasks = PeriodicTask.objects.all()
print(f"\nTotal Periodic Tasks: {all_tasks.count()}\n")

deprecated_tasks = []

for task in all_tasks:
    print(f"Task: {task.name}")
    print(f"  Function: {task.task}")
    print(f"  Enabled: {task.enabled}")
    print(f"  Last Run: {task.last_run_at}")
    print()

    # Check if task references deprecated functions
    if 'send_collision_alert_ical' in task.task:
        deprecated_tasks.append(task)
        print(f"  ⚠️  DEPRECATED TASK FOUND: {task.name}")

    if 'poll_booking_com_emails' in task.task:
        deprecated_tasks.append(task)
        print(f"  ⚠️  DEPRECATED TASK FOUND: {task.name}")

print("\n" + "=" * 70)
print(f"DEPRECATED TASKS FOUND: {len(deprecated_tasks)}")
print("=" * 70)

if deprecated_tasks:
    print("\n⚠️  The following tasks reference deprecated functions:")
    for task in deprecated_tasks:
        print(f"  - {task.name} ({task.task})")

    print("\n" + "=" * 70)
    print("RECOMMENDED ACTION")
    print("=" * 70)
    print("Delete these tasks from Django admin:")
    print("https://pickarooms-495ab160017c.herokuapp.com/admin/django_celery_beat/periodictask/")
    print("\nOr run this to delete automatically:")
    print("  for task in deprecated_tasks:")
    print("      task.delete()")
else:
    print("\n✅ No deprecated tasks found in Celery Beat database")

print("\n" + "=" * 70)
print("CELERY QUEUE CHECK")
print("=" * 70)
print("\nTo check for pending tasks in Redis queue:")
print("  heroku redis:cli --app pickarooms")
print("  Then run: KEYS celery*")
print("\nTo purge all pending tasks:")
print("  heroku run python manage.py shell --app pickarooms")
print("  >>> from pickarooms.celery import app")
print("  >>> app.control.purge()")
