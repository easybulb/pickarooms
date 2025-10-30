"""
Investigate if iCal feeds actually contain booking references
This will help confirm whether the enrichment bug theory is correct
"""
import os
import sys
import django

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import Reservation, EnrichmentLog
from datetime import datetime, timedelta

print(f"\n{'='*80}")
print(f"INVESTIGATING: Do iCal feeds contain booking references?")
print(f"{'='*80}\n")

# Strategy: Find reservations created by iCal that have booking_reference
# These would have been created with booking_ref from iCal SUMMARY field

print("1️⃣ CHECKING RECENT RESERVATIONS CREATED BY iCAL WITH BOOKING REF:")
print(f"   {'─'*70}")

# Look at recent reservations (last 7 days)
seven_days_ago = datetime.now() - timedelta(days=7)

ical_reservations = Reservation.objects.filter(
    platform='booking',
    created_at__gte=seven_days_ago,
    ical_uid__isnull=False  # Created by iCal
).exclude(
    ical_uid=''
).select_related('room', 'guest').order_by('-created_at')[:50]

print(f"   Found {ical_reservations.count()} iCal-created reservations in last 7 days\n")

ical_with_booking_ref = []
ical_without_booking_ref = []

for res in ical_reservations:
    has_booking_ref = res.booking_reference and len(res.booking_reference) >= 5
    has_guest = res.guest is not None

    if has_booking_ref:
        ical_with_booking_ref.append(res)
        enriched_status = "✅ ENRICHED" if has_guest else "❌ UNENRICHED"

        print(f"   {enriched_status} - Booking Ref: {res.booking_reference}")
        print(f"   Room: {res.room.name} | Check-in: {res.check_in_date}")
        print(f"   Guest Name: {res.guest_name}")
        print(f"   Created: {res.created_at.strftime('%Y-%m-%d %H:%M:%S')}")

        if has_booking_ref and not has_guest:
            print(f"   🚨 BUG CONFIRMED: Has booking_ref but NO Guest object!")

            # Check if enrichment workflow was triggered
            log_started = EnrichmentLog.objects.filter(
                reservation=res,
                action='email_search_started'
            ).exists()

            if log_started:
                print(f"   ✅ Enrichment workflow WAS triggered")
            else:
                print(f"   ❌ Enrichment workflow was NOT triggered (or skipped)")

        print()
    else:
        ical_without_booking_ref.append(res)

print(f"\n{'='*80}")
print(f"📊 STATISTICS:")
print(f"{'='*80}")
print(f"Total iCal reservations (last 7 days): {ical_reservations.count()}")
print(f"  ├─ With booking_ref: {len(ical_with_booking_ref)}")
print(f"  └─ Without booking_ref: {len(ical_without_booking_ref)}")

if len(ical_with_booking_ref) > 0:
    percentage = (len(ical_with_booking_ref) / ical_reservations.count()) * 100
    print(f"\n✅ CONFIRMED: {percentage:.1f}% of iCal reservations have booking_ref")
    print(f"   → This means iCal feeds DO contain booking references!")
    print(f"   → The enrichment bug theory is CORRECT")

    # Check how many of these are unenriched
    unenriched_with_ref = [r for r in ical_with_booking_ref if r.guest is None]
    if len(unenriched_with_ref) > 0:
        print(f"\n🚨 BUG IMPACT:")
        print(f"   {len(unenriched_with_ref)} reservation(s) have booking_ref but NO Guest")
        print(f"   → These were affected by the enrichment skip bug")
        print(f"   → The fix we just deployed should prevent this going forward")
else:
    print(f"\n❌ SURPRISING: NO iCal reservations have booking_ref in last 7 days")
    print(f"   → Either iCal feeds don't contain booking refs")
    print(f"   → Or all recent bookings were enriched via XLS/email before iCal sync")

print(f"\n{'='*80}")
print(f"2️⃣ CHECKING ENRICHMENT LOGS FOR PATTERN:")
print(f"{'='*80}\n")

# Check for reservations that have booking_ref but no "email_search_started" log
recent_reservations = Reservation.objects.filter(
    platform='booking',
    created_at__gte=seven_days_ago,
    guest__isnull=True  # Unenriched
).exclude(
    booking_reference=''
).select_related('room')[:20]

if recent_reservations.exists():
    print(f"Found {recent_reservations.count()} unenriched reservations WITH booking_ref:\n")

    for res in recent_reservations:
        # Check if email search was started
        email_search_log = EnrichmentLog.objects.filter(
            reservation=res,
            action='email_search_started'
        ).exists()

        status = "✅ Email search triggered" if email_search_log else "❌ Email search NOT triggered"

        print(f"   {status}")
        print(f"   Booking Ref: {res.booking_reference}")
        print(f"   Room: {res.room.name} | Check-in: {res.check_in_date}")
        print(f"   Created: {res.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print()
else:
    print("   No unenriched reservations with booking_ref found")

print(f"{'='*80}\n")
