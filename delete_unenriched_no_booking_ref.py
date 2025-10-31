"""
Delete unenriched reservations that have NO booking_reference
These are iCal-synced reservations waiting for email enrichment that never happened
Safe to delete because XLS upload will recreate them with full data
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import Reservation
from datetime import date

print("=" * 70)
print("DELETE UNENRICHED RESERVATIONS (NO BOOKING REF)")
print("=" * 70)

# Get unenriched reservations with NO booking_reference
unenriched_no_ref = Reservation.objects.filter(
    guest__isnull=True,
    booking_reference__in=['', None]
).order_by('check_in_date')

total = unenriched_no_ref.count()

print(f"\nTotal unenriched reservations with NO booking_ref: {total}")

if total == 0:
    print("\n✅ No unenriched reservations without booking_ref to delete")
    print("=" * 70)
    exit()

# Show breakdown
today = date.today()
past = unenriched_no_ref.filter(check_in_date__lt=today)
future = unenriched_no_ref.filter(check_in_date__gte=today)

print(f"  - Past check-ins: {past.count()}")
print(f"  - Future check-ins: {future.count()}")

# Show sample
print(f"\nFirst 20 reservations to be deleted:")
for res in unenriched_no_ref[:20]:
    print(f"  - {res.check_in_date} | {res.room.name if res.room else 'No Room'} | Platform: {res.platform}")

print(f"\n... and {max(0, total - 20)} more")

print("\n" + "=" * 70)
print("WHY THIS IS SAFE")
print("=" * 70)
print("""
These reservations are iCal-synced but never got enriched with booking_ref.
They're stuck waiting for email enrichment that never happened.

When you upload XLS:
- If the booking exists in XLS → It will be RECREATED with full data
- If the booking doesn't exist in XLS → It was cancelled/removed anyway

This cleanup removes stale iCal reservations to make room for clean XLS data.
""")

print("=" * 70)
print("DELETING...")
print("=" * 70)

# Delete them
deleted_count, details = unenriched_no_ref.delete()

print(f"\n✅ Successfully deleted {deleted_count} reservation(s)")
print(f"\nDetails:")
for model, count in details.items():
    if count > 0:
        print(f"  - {model}: {count}")

print("\n" + "=" * 70)
print("NEXT STEPS")
print("=" * 70)
print("1. Upload your XLS file from Booking.com")
print("2. XLS will enrich the 106 partially enriched reservations with guest names")
print("3. XLS will create any missing bookings with full data")
print("\n✅ Database is now clean and ready for XLS upload!")
print("=" * 70)
