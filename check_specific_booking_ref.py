"""
Check if specific booking reference exists in database
Booking ref: 5041581696 (Nov 15, 2025)
Email arrived at 5:35 PM and was read by email parser
iCal sync ran at 17:39 (5:39 PM) - 4 minutes later
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import Reservation, EnrichmentLog, PendingEnrichment
from datetime import date

booking_ref = "5041581696"
check_in_date = date(2025, 11, 15)

print(f"\n{'='*80}")
print(f"SEARCHING FOR BOOKING REFERENCE: {booking_ref}")
print(f"Expected check-in date: {check_in_date.strftime('%A, %B %d, %Y')}")
print(f"Email arrived: 5:35 PM (read by email parser)")
print(f"iCal synced: 5:39 PM (17:39 UK) - created 1 reservation")
print(f"{'='*80}\n")

# 1. Check if reservation exists with this booking ref
print("1️⃣ CHECKING RESERVATIONS TABLE:")
print(f"   {'─'*70}")

reservations = Reservation.objects.filter(
    booking_reference=booking_ref
).select_related('room', 'guest')

if reservations.exists():
    print(f"   ✅ FOUND: {reservations.count()} reservation(s) with booking ref {booking_ref}\n")
    for res in reservations:
        enriched = "✅ ENRICHED" if res.guest else "❌ UNENRICHED"
        print(f"   {enriched}")
        print(f"   Room: {res.room.name}")
        print(f"   Guest Name: {res.guest_name}")
        print(f"   Check-in: {res.check_in_date}")
        print(f"   Check-out: {res.check_out_date}")
        print(f"   Status: {res.status}")
        print(f"   Created: {res.created_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"   Updated: {res.updated_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        if res.guest:
            print(f"   Guest object: {res.guest.full_name}")
        print()
else:
    print(f"   ❌ NOT FOUND: No reservations with booking ref {booking_ref}\n")

# 2. Check if reservation exists for this date (without booking ref)
print("\n2️⃣ CHECKING RESERVATIONS FOR NOV 15, 2025:")
print(f"   {'─'*70}")

date_reservations = Reservation.objects.filter(
    check_in_date=check_in_date,
    platform='booking'
).select_related('room', 'guest').order_by('-created_at')

if date_reservations.exists():
    print(f"   Found {date_reservations.count()} reservation(s) for {check_in_date}:\n")
    for res in date_reservations:
        enriched = "✅ ENRICHED" if res.guest else "❌ UNENRICHED"
        print(f"   {enriched}")
        print(f"   Room: {res.room.name}")
        print(f"   Booking Ref: {res.booking_reference or '(empty)'}")
        print(f"   Guest Name: {res.guest_name}")
        print(f"   Created: {res.created_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        
        # Check if this is the one created at 17:39
        created_time = res.created_at.strftime('%H:%M')
        if '17:3' in created_time:
            print(f"   🔥 THIS WAS CREATED AT iCAL SYNC TIME (17:39)!")
        print()
else:
    print(f"   ❌ No reservations found for {check_in_date}\n")

# 3. Check EnrichmentLog
print("\n3️⃣ CHECKING ENRICHMENT LOGS:")
print(f"   {'─'*70}")

logs = EnrichmentLog.objects.filter(
    booking_reference=booking_ref
).order_by('-timestamp')

if logs.exists():
    print(f"   Found {logs.count()} enrichment log(s) for {booking_ref}:\n")
    for log in logs:
        print(f"   Time: {log.timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"   Action: {log.get_action_display()}")
        print(f"   Method: {log.method or 'N/A'}")
        print(f"   Details: {log.details}")
        print()
else:
    print(f"   ❌ No enrichment logs for {booking_ref}\n")

# 4. Check PendingEnrichment (old system)
print("\n4️⃣ CHECKING PENDING ENRICHMENT TABLE:")
print(f"   {'─'*70}")

pending = PendingEnrichment.objects.filter(
    booking_reference=booking_ref
)

if pending.exists():
    print(f"   Found {pending.count()} pending enrichment(s):\n")
    for pe in pending:
        print(f"   Status: {pe.get_status_display()}")
        print(f"   Check-in: {pe.check_in_date}")
        print(f"   Email received: {pe.email_received_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"   Attempts: {pe.attempts}")
        print()
else:
    print(f"   ❌ No pending enrichments for {booking_ref}\n")

# 5. Summary
print(f"\n{'='*80}")
print(f"📊 SUMMARY:")
print(f"{'='*80}")

has_reservation_with_ref = Reservation.objects.filter(booking_reference=booking_ref).exists()
has_reservation_without_ref = Reservation.objects.filter(
    check_in_date=check_in_date,
    booking_reference=''
).exists()

if has_reservation_with_ref:
    print(f"✅ Reservation EXISTS with booking ref {booking_ref}")
    print(f"   → iCal feed DID contain the booking reference")
    print(f"   → Enrichment workflow should have been triggered")
    print(f"   → But was likely SKIPPED due to existing booking_ref (THE BUG!)")
elif has_reservation_without_ref:
    print(f"⚠️  Reservation EXISTS but WITHOUT booking ref")
    print(f"   → iCal feed did NOT contain booking reference")
    print(f"   → Email parser read the email but couldn't match it")
    print(f"   → Enrichment workflow should be running (check logs)")
else:
    print(f"❌ NO reservation found for this booking")
    print(f"   → iCal sync may have failed")
    print(f"   → Or booking not in iCal feed yet (payment pending?)")

print(f"{'='*80}\n")
