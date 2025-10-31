"""
Analyze the 69 unenriched reservations to understand what needs cleanup
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import Reservation
from datetime import date
from django.utils import timezone

print("=" * 70)
print("ANALYZING UNENRICHED RESERVATIONS")
print("=" * 70)

# Get all unenriched reservations (no guest object)
unenriched = Reservation.objects.filter(guest__isnull=True).order_by('check_in_date')

print(f"\nTotal Unenriched Reservations: {unenriched.count()}")

# Breakdown by date
today = date.today()
past = unenriched.filter(check_in_date__lt=today)
future = unenriched.filter(check_in_date__gte=today)

print(f"  - Past check-ins (old data): {past.count()}")
print(f"  - Future check-ins (needs enrichment): {future.count()}")

# Breakdown by platform
by_platform = {}
for res in unenriched:
    platform = res.platform or 'unknown'
    by_platform[platform] = by_platform.get(platform, 0) + 1

print(f"\nBy Platform:")
for platform, count in by_platform.items():
    print(f"  - {platform}: {count}")

# Breakdown by booking_reference
with_ref = unenriched.exclude(booking_reference='').count()
without_ref = unenriched.filter(booking_reference='').count()

print(f"\nBy Booking Reference:")
print(f"  - Has booking_ref: {with_ref}")
print(f"  - No booking_ref: {without_ref}")

# Show oldest and newest
if unenriched.exists():
    oldest = unenriched.first()
    newest = unenriched.last()

    print(f"\nOldest Unenriched:")
    print(f"  - Check-in: {oldest.check_in_date}")
    print(f"  - Room: {oldest.room.name if oldest.room else 'None'}")
    print(f"  - Platform: {oldest.platform}")
    print(f"  - Booking Ref: '{oldest.booking_reference}'")

    print(f"\nNewest Unenriched:")
    print(f"  - Check-in: {newest.check_in_date}")
    print(f"  - Room: {newest.room.name if newest.room else 'None'}")
    print(f"  - Platform: {newest.platform}")
    print(f"  - Booking Ref: '{newest.booking_reference}'")

# Show sample of past (should be deleted)
print(f"\n" + "=" * 70)
print("PAST RESERVATIONS (SHOULD BE DELETED)")
print("=" * 70)
if past.exists():
    print(f"\nShowing first 10 of {past.count()} past reservations:\n")
    for res in past[:10]:
        print(f"  - {res.check_in_date} | {res.room.name if res.room else 'No Room'} | Ref: '{res.booking_reference}'")
else:
    print("\n✅ No past unenriched reservations")

# Show sample of future (investigate)
print(f"\n" + "=" * 70)
print("FUTURE RESERVATIONS (NEEDS INVESTIGATION)")
print("=" * 70)
if future.exists():
    print(f"\nShowing first 10 of {future.count()} future reservations:\n")
    for res in future[:10]:
        print(f"  - {res.check_in_date} | {res.room.name if res.room else 'No Room'} | Ref: '{res.booking_reference}'")
else:
    print("\n✅ All future reservations are enriched")

print(f"\n" + "=" * 70)
print("RECOMMENDATIONS")
print("=" * 70)
print(f"""
1. DELETE all {past.count()} past unenriched reservations (old/stale data)
2. INVESTIGATE {future.count()} future unenriched reservations:
   - If they have booking_ref but no guest → waiting for email enrichment
   - If they have no booking_ref → iCal reservations waiting for email match
3. After cleanup, upload XLS to enrich remaining valid reservations
""")

print("=" * 70)
