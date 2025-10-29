"""
Check for unresolved collision on 2026-10-23
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import Reservation, EnrichmentLog
from datetime import date

check_in_date = date(2026, 10, 23)

print(f"\n{'='*60}")
print(f"Checking for collision on {check_in_date}")
print(f"{'='*60}\n")

# Check for unenriched reservations
unenriched = Reservation.objects.filter(
    check_in_date=check_in_date,
    platform='booking',
    status='confirmed',
    guest__isnull=True,
    booking_reference=''
).select_related('room')

print(f"Unenriched reservations: {unenriched.count()}")
for res in unenriched:
    print(f"  - {res.room.name}: Check-in {res.check_in_date}, Check-out {res.check_out_date}")

# Check enrichment logs for this date
logs = EnrichmentLog.objects.filter(
    reservation__check_in_date=check_in_date
).order_by('-timestamp')[:10]

print(f"\nEnrichment logs for this date: {logs.count()}")
for log in logs:
    print(f"  - {log.timestamp.strftime('%Y-%m-%d %H:%M:%S')}: {log.action} - {log.method}")
    if log.details:
        print(f"    Details: {log.details}")

print(f"\n{'='*60}\n")
