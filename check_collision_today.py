"""
Check what triggered the collision SMS at 21:09 for Oct 29, 2025
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import Reservation, EnrichmentLog
from datetime import date, datetime
import pytz

check_in_date = date(2025, 10, 29)
uk_tz = pytz.timezone('Europe/London')

print(f"\n{'='*60}")
print(f"Investigating collision alert at 21:09 for {check_in_date}")
print(f"{'='*60}\n")

# Get all enrichment logs around 21:09
logs_around_2109 = EnrichmentLog.objects.filter(
    reservation__check_in_date=check_in_date,
    timestamp__gte=datetime(2025, 10, 29, 21, 0, tzinfo=uk_tz),
    timestamp__lte=datetime(2025, 10, 29, 21, 20, tzinfo=uk_tz)
).order_by('timestamp')

print(f"Enrichment logs between 21:00-21:20:")
for log in logs_around_2109:
    print(f"  {log.timestamp.strftime('%H:%M:%S')} - {log.action} - {log.method}")
    print(f"    Room: {log.room.name if log.room else 'N/A'}")
    print(f"    Booking Ref: {log.booking_reference or 'None'}")
    if log.details:
        print(f"    Details: {log.details}")
    print()

# Check all reservations for Oct 29
all_reservations_oct29 = Reservation.objects.filter(
    check_in_date=check_in_date,
    platform='booking',
    status='confirmed'
).select_related('room', 'guest').order_by('created_at')

print(f"\nAll reservations for {check_in_date}:")
for res in all_reservations_oct29:
    enriched = "Enriched" if res.guest else "Unenriched"
    print(f"  {res.room.name}: {enriched}, Ref: {res.booking_reference or 'None'}")
    print(f"    Created: {res.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

# Check for collision detection logs
collision_logs = EnrichmentLog.objects.filter(
    reservation__check_in_date=check_in_date,
    action='collision_detected'
).order_by('timestamp')

print(f"\nCollision detection logs for {check_in_date}:")
if collision_logs.exists():
    for log in collision_logs:
        print(f"  {log.timestamp.strftime('%Y-%m-%d %H:%M:%S')} - {log.method}")
        print(f"    Details: {log.details}")
        print()
else:
    print("  None found")

print(f"\n{'='*60}\n")
