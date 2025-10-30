"""
Check all bookings created TODAY by iCal sync
This will show us what iCal actually found vs what we expected
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import Reservation, EnrichmentLog
from datetime import date, datetime
from django.utils import timezone

print(f"\n{'='*80}")
print(f"BOOKINGS CREATED TODAY BY iCAL SYNC")
print(f"Current time (UTC): {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"{'='*80}\n")

today = timezone.now().date()

# Get all reservations created today
todays_reservations = Reservation.objects.filter(
    created_at__date=today
).select_related('room', 'guest').order_by('created_at')

print(f"Total reservations created today: {todays_reservations.count()}\n")

if todays_reservations.exists():
    print(f"{'='*80}")
    print(f"DETAILS:")
    print(f"{'='*80}\n")
    
    for i, res in enumerate(todays_reservations, 1):
        enriched = "Enriched" if res.guest else "Unenriched"
        platform = res.get_platform_display()
        nights = (res.check_out_date - res.check_in_date).days
        
        print(f"[{i}] {res.booking_reference or '(no ref)'}")
        print(f"    Room: {res.room.name}")
        print(f"    Guest: {res.guest_name}")
        print(f"    Platform: {platform}")
        print(f"    Check-in: {res.check_in_date}")
        print(f"    Check-out: {res.check_out_date} ({nights} nights)")
        print(f"    Status: {res.status} ({enriched})")
        print(f"    Created: {res.created_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"    iCal UID: {res.ical_uid[:50]}..." if len(res.ical_uid) > 50 else f"    iCal UID: {res.ical_uid}")
        
        if res.guest:
            print(f"    Guest Details:")
            print(f"       Name: {res.guest.full_name}")
            print(f"       Phone: {res.guest.phone_number or 'N/A'}")
            print(f"       Email: {res.guest.email or 'N/A'}")
        
        print()
else:
    print("   No reservations created today by iCal sync.\n")

# Check for the specific bookings mentioned
print(f"\n{'='*80}")
print(f"CHECKING SPECIFIC BOOKING REFERENCES:")
print(f"{'='*80}\n")

# Multi-room booking that worked
multi_room_ref = '6343804240'
print(f"1. Multi-room booking: {multi_room_ref}")
print(f"   {'-'*70}")
multi_room = Reservation.objects.filter(booking_reference=multi_room_ref).select_related('room', 'guest')
if multi_room.exists():
    print(f"   FOUND: {multi_room.count()} reservation(s)")
    for res in multi_room:
        enriched = "Enriched" if res.guest else "Unenriched"
        print(f"      - {res.room.name}: {res.guest_name} ({enriched})")
        print(f"        Created: {res.created_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
else:
    print(f"   NOT FOUND")

print()

# Missing booking
missing_ref = '6508851340'
print(f"2. Missing booking: {missing_ref}")
print(f"   {'-'*70}")
missing = Reservation.objects.filter(booking_reference=missing_ref).select_related('room', 'guest')
if missing.exists():
    print(f"   FOUND: {missing.count()} reservation(s)")
    for res in missing:
        enriched = "Enriched" if res.guest else "Unenriched"
        print(f"      - {res.room.name}: {res.guest_name} ({enriched})")
        print(f"        Created: {res.created_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
else:
    print(f"   NOT FOUND (This is the missing one!)")

print()

# Check enrichment logs for today
print(f"\n{'='*80}")
print(f"ENRICHMENT LOGS FOR TODAY:")
print(f"{'='*80}\n")

todays_logs = EnrichmentLog.objects.filter(
    timestamp__date=today
).select_related('reservation', 'room').order_by('timestamp')

print(f"Total enrichment logs today: {todays_logs.count()}\n")

if todays_logs.exists():
    for i, log in enumerate(todays_logs, 1):
        print(f"[{i}] {log.timestamp.strftime('%H:%M:%S')}: {log.get_action_display()}")
        print(f"    Booking Ref: {log.booking_reference}")
        print(f"    Room: {log.room.name if log.room else 'N/A'}")
        print(f"    Method: {log.method}")
        if log.details:
            print(f"    Details: {log.details}")
        print()

# Summary
print(f"\n{'='*80}")
print(f"SUMMARY:")
print(f"{'='*80}")
print(f"Total new reservations created today: {todays_reservations.count()}")
print(f"Multi-room booking 6343804240 found: {'YES' if multi_room.exists() else 'NO'}")
print(f"Missing booking 6508851340 found: {'YES' if missing.exists() else 'NO'}")
print(f"Enrichment activities today: {todays_logs.count()}")
print(f"{'='*80}\n")

print("INTERPRETATION:")
if not missing.exists() and multi_room.exists():
    print("- Multi-room booking was found by iCal (working correctly)")
    print("- Missing booking was NOT found by iCal (confirms feed issue)")
    print("- This proves iCal sync is working, but Booking.com feed is incomplete")
elif missing.exists():
    print("- GOOD NEWS! The missing booking WAS found by iCal after refresh!")
    print("- The 'Refresh connection' fixed the issue")
else:
    print("- Neither booking found - need to investigate further")
print()
