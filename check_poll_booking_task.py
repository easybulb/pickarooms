"""
Check for deprecated poll_booking_com_emails task in Celery Beat
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from django_celery_beat.models import PeriodicTask

print("=" * 70)
print("SEARCHING FOR DEPRECATED POLL_BOOKING_COM_EMAILS TASK")
print("=" * 70)

# Search for any task with 'poll_booking' in the name or task path
deprecated_tasks = PeriodicTask.objects.filter(task__icontains='poll_booking')

if deprecated_tasks.exists():
    print(f"\n🚨 FOUND {deprecated_tasks.count()} DEPRECATED TASK(S)!\n")

    for task in deprecated_tasks:
        print(f"Task Name: {task.name}")
        print(f"Task Function: {task.task}")
        print(f"Enabled: {task.enabled}")
        print(f"Last Run: {task.last_run_at}")
        print(f"Crontab: {task.crontab}")
        print(f"Interval: {task.interval}")
        print()

        print("=" * 70)
        print("ACTION REQUIRED")
        print("=" * 70)
        print("This task is calling the OLD email-driven enrichment flow!")
        print("This is what's sending the deprecated 'Multiple bookings detected' SMS.")
        print()
        print("To delete this task, run:")
        print(f"  task = PeriodicTask.objects.get(id={task.id})")
        print("  task.delete()")
        print()
else:
    print("\n✅ No deprecated poll_booking_com_emails tasks found")
    print()

print("=" * 70)
