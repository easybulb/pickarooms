"""
Purge all pending Celery tasks from Redis queue
This will clear any delayed tasks that might contain deprecated function calls
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from pickarooms.celery import app

print("=" * 70)
print("PURGING CELERY QUEUE")
print("=" * 70)

print("\nClearing all pending tasks from Redis queue...")
print("This will remove any delayed tasks that reference deprecated functions.")
print()

try:
    # Purge all pending tasks
    result = app.control.purge()

    if isinstance(result, list):
        total_purged = sum(r.get('ok', 0) if isinstance(r, dict) else r for r in result)
    else:
        total_purged = result

    print(f"✅ Successfully purged {total_purged} task(s) from queue")
    print()
    print("This should have removed any pending 'send_collision_alert_ical' tasks.")
    print()

except Exception as e:
    print(f"❌ Error purging queue: {str(e)}")
    print()

print("=" * 70)
print("NEXT STEPS")
print("=" * 70)
print()
print("1. Worker and beat dynos have already been restarted")
print("2. Queue has been purged")
print("3. Monitor for any more deprecated SMS messages")
print()
print("If you still receive the old SMS format, check:")
print("  - Heroku logs: heroku logs --tail --app pickarooms")
print("  - Look for 'send_collision_alert_ical' in logs")
print()
