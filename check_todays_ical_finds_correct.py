"""
Check all NEW reservations found by iCal TODAY
Search by creation date, not booking reference (which iCal doesn't always have)
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import Reservation, EnrichmentLog, Room
from datetime import date, datetime
from django.utils import timezone

print(f"\n{'='*80}")
print(f"ALL NEW RESERVATIONS CREATED TODAY BY iCAL")
print(f"Current time (UTC): {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"{'='*80}\n")

today = timezone.now().date()

# Get ALL reservations created today (regardless of booking reference)
todays_reservations = Reservation.objects.filter(
    created_at__date=today,
    platform='booking'
).select_related('room', 'guest').order_by('created_at')

print(f"📊 TOTAL NEW RESERVATIONS CREATED TODAY: {todays_reservations.count()}\n")

if todays_reservations.count() == 0:
    print("   ⚠️  No new reservations created today.")
    print("   This means iCal hasn't found any NEW bookings today.")
    print("   (It may have UPDATED existing ones, but no new ones created)\n")
else:
    print(f"{'='*80}")
    print(f"BREAKDOWN BY ROOM:")
    print(f"{'='*80}\n")
    
    # Group by room
    rooms = Room.objects.all().order_by('name')
    for room in rooms:
        room_reservations = todays_reservations.filter(room=room)
        if room_reservations.exists():
            print(f"🏠 {room.name}: {room_reservations.count()} new reservation(s)")
            for res in room_reservations:
                enriched = "✅ Enriched" if res.guest else "❌ Unenriched"
                booking_ref = res.booking_reference if res.booking_reference else "(no ref yet)"
                print(f"      - {booking_ref}")
                print(f"        Check-in: {res.check_in_date}")
                print(f"        Guest: {res.guest_name}")
                print(f"        Created: {res.created_at.strftime('%H:%M:%S UTC')}")
                print(f"        Status: {enriched}")
            print()
    
    print(f"{'='*80}")
    print(f"DETAILED LIST (Chronological Order):")
    print(f"{'='*80}\n")
    
    for i, res in enumerate(todays_reservations, 1):
        enriched = "✅ Enriched" if res.guest else "❌ Unenriched"
        booking_ref = res.booking_reference if res.booking_reference else "(no ref yet)"
        nights = (res.check_out_date - res.check_in_date).days
        
        print(f"[{i}] Created at {res.created_at.strftime('%H:%M:%S UTC')}")
        print(f"    Room: {res.room.name}")
        print(f"    Booking Ref: {booking_ref}")
        print(f"    Guest Name: {res.guest_name}")
        print(f"    Check-in: {res.check_in_date} ({nights} nights)")
        print(f"    Check-out: {res.check_out_date}")
        print(f"    Status: {res.status} ({enriched})")
        
        if res.guest:
            print(f"    💚 Linked Guest:")
            print(f"       Name: {res.guest.full_name}")
            print(f"       Phone: {res.guest.phone_number or 'N/A'}")
            print(f"       Email: {res.guest.email or 'N/A'}")
        
        print()

# Check expected bookings for today
print(f"\n{'='*80}")
print(f"CHECKING EXPECTED BOOKINGS:")
print(f"{'='*80}\n")

# We expect 2 bookings received today:
# 1. Multi-room booking (6343804240) - received earlier today
# 2. Christopher Jefferson (6508851340) - received at 10:36 AM

print(f"Expected bookings received today:")
print(f"   1. Multi-room booking (2 rooms, same ref)")
print(f"   2. Christopher Jefferson (Room 2, Nov 21)")
print()
print(f"What iCal found: {todays_reservations.count()} new reservation(s)")
print()

if todays_reservations.count() == 2:
    print(f"✅ MATCHES! iCal found both expected bookings (multi-room = 2 reservations)")
elif todays_reservations.count() == 1:
    print(f"⚠️  ONLY 1 FOUND! One booking is missing from iCal feed")
elif todays_reservations.count() > 2:
    print(f"✅ GOOD! iCal found {todays_reservations.count()} reservations (maybe more bookings came in)")
else:
    print(f"❌ PROBLEM! iCal found 0 new reservations today")

# Check Room 2 specifically (where missing booking should be)
print(f"\n{'='*80}")
print(f"ROOM 2 SPECIFIC CHECK (Missing Booking Location):")
print(f"{'='*80}\n")

room2_today = todays_reservations.filter(room__name='Room 2')
print(f"Room 2 new reservations today: {room2_today.count()}")

if room2_today.exists():
    print(f"✅ Room 2 had new reservations today:")
    for res in room2_today:
        print(f"   - Check-in: {res.check_in_date}, Guest: {res.guest_name}")
else:
    print(f"❌ Room 2 had NO new reservations today")
    print(f"   This confirms Christopher Jefferson booking is NOT in iCal feed")

# Check all Room 2 reservations for Nov 21
print(f"\n📅 All Room 2 reservations for Nov 21, 2025:")
room2_nov21 = Reservation.objects.filter(
    room__name='Room 2',
    check_in_date=date(2025, 11, 21),
    status='confirmed'
).select_related('guest').order_by('created_at')

if room2_nov21.exists():
    print(f"   Found {room2_nov21.count()} reservation(s):")
    for res in room2_nov21:
        enriched = "Enriched" if res.guest else "Unenriched"
        print(f"   - {res.guest_name} ({res.booking_reference or 'no ref'})")
        print(f"     Created: {res.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"     Status: {enriched}")
else:
    print(f"   ⚠️  No reservations found for Room 2 on Nov 21")

# Summary
print(f"\n{'='*80}")
print(f"📊 SUMMARY:")
print(f"{'='*80}")
print(f"Total new reservations created today: {todays_reservations.count()}")
print(f"Room 2 new reservations today: {room2_today.count()}")
print(f"Room 2 reservations for Nov 21: {room2_nov21.count()}")
print()

if todays_reservations.count() >= 2 and room2_today.count() == 0:
    print(f"INTERPRETATION:")
    print(f"   ✅ iCal found other bookings today (working)")
    print(f"   ❌ Room 2 booking missing from feed")
    print(f"   📌 Suggests Room 2 iCal feed has an issue")
elif todays_reservations.count() == 0:
    print(f"INTERPRETATION:")
    print(f"   ⚠️  No new bookings found by iCal today at all")
    print(f"   📌 Check if Booking.com had any new bookings")
else:
    print(f"INTERPRETATION:")
    print(f"   Check details above to see what was found")

print(f"{'='*80}\n")
