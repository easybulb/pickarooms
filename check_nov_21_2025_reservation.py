"""
Check Heroku production for reservation with check-in date November 21, 2025
Email arrived today at 10:46 AM but hasn't been picked up by email parser or iCal sync
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import Reservation, EnrichmentLog, PendingEnrichment, Room
from datetime import date, datetime, timedelta
from django.utils import timezone

# Target check-in date: November 21, 2025
check_in_date = date(2025, 11, 21)
today = timezone.now().date()
current_time = timezone.now()

print(f"\n{'='*80}")
print(f"CHECKING FOR RESERVATION: Check-in Date = {check_in_date.strftime('%A, %B %d, %Y')}")
print(f"Current time (UTC): {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
print(f"Today's date: {today}")
print(f"Email arrived: Today at 10:46 AM (should be unread/unpicked)")
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
        created_today = res.created_at.date() == today
        time_marker = "🔥 CREATED TODAY!" if created_today else f"Created: {res.created_at.date()}"
        
        print(f"   [{i}] {enriched} - {time_marker}")
        print(f"       Room: {res.room.name}")
        print(f"       Platform: {platform}")
        print(f"       Guest Name: {res.guest_name}")
        print(f"       Booking Ref: {res.booking_reference or '(empty)'}")
        print(f"       Check-in: {res.check_in_date}")
        print(f"       Check-out: {res.check_out_date} ({nights} nights)")
        print(f"       Status: {res.status}")
        print(f"       Created: {res.created_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"       Updated: {res.updated_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"       iCal UID: {res.ical_uid[:60]}..." if len(res.ical_uid) > 60 else f"       iCal UID: {res.ical_uid}")
        
        if res.guest:
            print(f"       👤 Guest Info:")
            print(f"          Name: {res.guest.full_name}")
            print(f"          Email: {res.guest.email or '(none)'}")
            print(f"          Phone: {res.guest.phone_number or '(none)'}")
            print(f"          PIN: {res.guest.front_door_pin or '(none)'}")
        print()
else:
    print("   ⚠️  No reservations found for this date in iCal feed.\n")

# 2. Check specifically for UNENRICHED reservations
unenriched = Reservation.objects.filter(
    check_in_date=check_in_date,
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
        created_today = res.created_at.date() == today
        detected_marker = "🔥 DETECTED TODAY!" if created_today else f"Created {res.created_at.date()}"
        
        print(f"   [{i}] {detected_marker}")
        print(f"       Room: {res.room.name}")
        print(f"       Guest Name: {res.guest_name}")
        print(f"       Booking Ref: {res.booking_reference or '(empty - needs enrichment)'}")
        print(f"       Nights: {nights}")
        print(f"       Created: {res.created_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"       Status: Waiting for enrichment...")
        print()

# 3. Check PendingEnrichment for any emails parsed for this date
print(f"\n{'='*80}")
print(f"📧 PENDING ENRICHMENTS (Email Parser) for {check_in_date}:")
print(f"{'='*80}\n")

pending = PendingEnrichment.objects.filter(
    check_in_date=check_in_date
).select_related('matched_reservation', 'room_matched').order_by('-email_received_at')

print(f"   Total pending enrichments: {pending.count()}")
print()

if pending.exists():
    for i, pe in enumerate(pending, 1):
        email_today = pe.email_received_at.date() == today
        time_marker = "🔥 EMAIL TODAY!" if email_today else f"Email: {pe.email_received_at.date()}"
        
        print(f"   [{i}] {time_marker}")
        print(f"       Email received: {pe.email_received_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"       Booking Ref: {pe.booking_reference}")
        print(f"       Check-in Date: {pe.check_in_date}")
        print(f"       Status: {pe.get_status_display()}")
        print(f"       Email Type: {pe.get_email_type_display()}")
        print(f"       Attempts: {pe.attempts}")
        if pe.matched_reservation:
            print(f"       ✅ Matched to: {pe.matched_reservation.room.name}")
        else:
            print(f"       ❌ Not matched yet")
        if pe.alert_sent_at:
            print(f"       Alert sent: {pe.alert_sent_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print()
else:
    print("   ⚠️  No emails parsed for this date (Email parser hasn't picked it up).\n")

# 4. Check EnrichmentLog for activities related to this date
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
        logged_today = log.timestamp.date() == today
        time_marker = "🔥 TODAY" if logged_today else log.timestamp.strftime('%Y-%m-%d')
        
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

# 5. Check for collision detection on this date
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

# 6. Summary
print(f"\n{'='*80}")
print(f"📊 SUMMARY:")
print(f"{'='*80}")
print(f"   Total reservations in iCal: {all_reservations.count()}")
print(f"   Enriched: {all_reservations.filter(guest__isnull=False).count()}")
print(f"   Unenriched: {unenriched.count()}")
print(f"   Created today: {all_reservations.filter(created_at__date=today).count()}")
print(f"   Emails parsed (PendingEnrichment): {pending.count()}")
print(f"   Emails today: {pending.filter(email_received_at__date=today).count()}")
print(f"   Enrichment logs: {logs.count()}")
print()
print(f"   ⚠️  Expected: Email at 10:46 AM should be parsed by email poller")
print(f"   ⚠️  Expected: iCal sync (every 15 min) should create unenriched reservation")
print(f"   📌  If both are missing: Payment issue may be blocking iCal feed update")
print(f"{'='*80}\n")
