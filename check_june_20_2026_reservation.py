"""
Check Heroku production for unenriched reservation with check-in date June 20, 2026
This checks if there was a reservation detected yesterday from the iCal feed
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import Reservation, EnrichmentLog, Room
from datetime import date, datetime, timedelta
from django.utils import timezone

# Target check-in date: Saturday, June 20, 2026
check_in_date = date(2026, 6, 20)
yesterday = timezone.now().date() - timedelta(days=1)

print(f"\n{'='*80}")
print(f"CHECKING FOR RESERVATION: Check-in Date = {check_in_date.strftime('%A, %B %d, %Y')}")
print(f"Looking for detections from: {yesterday}")
print(f"{'='*80}\n")

# 1. Check for ANY reservations with this check-in date (enriched or unenriched)
all_reservations = Reservation.objects.filter(
    check_in_date=check_in_date
).select_related('room', 'guest').order_by('created_at')

print(f"📋 ALL RESERVATIONS for {check_in_date}:")
print(f"   Total found: {all_reservations.count()}")
print()

if all_reservations.exists():
    for i, res in enumerate(all_reservations, 1):
        enriched = "✅ ENRICHED" if res.guest else "❌ UNENRICHED"
        platform = res.get_platform_display()
        nights = (res.check_out_date - res.check_in_date).days
        
        print(f"   [{i}] {enriched}")
        print(f"       Room: {res.room.name}")
        print(f"       Platform: {platform}")
        print(f"       Guest Name: {res.guest_name}")
        print(f"       Booking Ref: {res.booking_reference or '(empty)'}")
        print(f"       Check-in: {res.check_in_date}")
        print(f"       Check-out: {res.check_out_date} ({nights} nights)")
        print(f"       Status: {res.status}")
        print(f"       Created: {res.created_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"       Updated: {res.updated_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"       iCal UID: {res.ical_uid[:50]}..." if len(res.ical_uid) > 50 else f"       iCal UID: {res.ical_uid}")
        
        if res.guest:
            print(f"       👤 Guest Info:")
            print(f"          Name: {res.guest.full_name}")
            print(f"          Email: {res.guest.email or '(none)'}")
            print(f"          Phone: {res.guest.phone_number or '(none)'}")
            print(f"          PIN: {res.guest.front_door_pin or '(none)'}")
        print()
else:
    print("   ⚠️  No reservations found for this date.\n")

# 2. Check specifically for UNENRICHED reservations
unenriched = Reservation.objects.filter(
    check_in_date=check_in_date,
    platform='booking',
    status='confirmed',
    guest__isnull=True  # Not enriched yet
).select_related('room')

print(f"\n{'='*80}")
print(f"❌ UNENRICHED RESERVATIONS for {check_in_date}:")
print(f"   Total found: {unenriched.count()}")
print(f"{'='*80}\n")

if unenriched.exists():
    for i, res in enumerate(unenriched, 1):
        nights = (res.check_out_date - res.check_in_date).days
        created_yesterday = res.created_at.date() == yesterday
        detected_marker = "🔥 DETECTED YESTERDAY!" if created_yesterday else ""
        
        print(f"   [{i}] {detected_marker}")
        print(f"       Room: {res.room.name}")
        print(f"       Guest Name: {res.guest_name}")
        print(f"       Booking Ref: {res.booking_reference or '(empty - needs enrichment)'}")
        print(f"       Nights: {nights}")
        print(f"       Created: {res.created_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"       Status: Waiting for enrichment...")
        print()

# 3. Check EnrichmentLog for activities related to this date
print(f"\n{'='*80}")
print(f"📝 ENRICHMENT LOGS for {check_in_date}:")
print(f"{'='*80}\n")

logs = EnrichmentLog.objects.filter(
    reservation__check_in_date=check_in_date
).select_related('reservation', 'room').order_by('-timestamp')

print(f"   Total logs found: {logs.count()}")
print()

if logs.exists():
    for i, log in enumerate(logs, 1):
        logged_yesterday = log.timestamp.date() == yesterday
        time_marker = "🔥 YESTERDAY" if logged_yesterday else log.timestamp.strftime('%Y-%m-%d')
        
        print(f"   [{i}] {time_marker}")
        print(f"       Time: {log.timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"       Action: {log.get_action_display()}")
        print(f"       Booking Ref: {log.booking_reference}")
        print(f"       Method: {log.method or '(none)'}")
        if log.room:
            print(f"       Room: {log.room.name}")
        if log.details:
            print(f"       Details: {log.details}")
        print()
else:
    print("   ℹ️  No enrichment logs found for this date.\n")

# 4. Check for collision detection on this date
print(f"\n{'='*80}")
print(f"⚠️  COLLISION CHECK for {check_in_date}:")
print(f"{'='*80}\n")

same_day_bookings = Reservation.objects.filter(
    check_in_date=check_in_date,
    platform='booking',
    status='confirmed',
    guest__isnull=True
).select_related('room')

if same_day_bookings.count() > 1:
    print(f"   🚨 COLLISION DETECTED: {same_day_bookings.count()} unenriched bookings on same day!")
    for res in same_day_bookings:
        print(f"      - {res.room.name}: {res.guest_name}")
    print()
else:
    print(f"   ✅ No collision detected.\n")

# 5. Summary
print(f"\n{'='*80}")
print(f"📊 SUMMARY:")
print(f"{'='*80}")
print(f"   Total reservations for {check_in_date}: {all_reservations.count()}")
print(f"   Enriched: {all_reservations.filter(guest__isnull=False).count()}")
print(f"   Unenriched: {unenriched.count()}")
print(f"   Detected yesterday: {all_reservations.filter(created_at__date=yesterday).count()}")
print(f"   Enrichment logs: {logs.count()}")
print(f"{'='*80}\n")
