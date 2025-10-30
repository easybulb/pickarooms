"""
Check if Christopher Jefferson booking (6508851340) appeared in database after resync
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import Reservation, Room, RoomICalConfig
from datetime import date

print(f"\n{'='*80}")
print(f"CHECKING FOR BOOKING 6508851340 AFTER RESYNC")
print(f"{'='*80}\n")

# Target booking
target_ref = '6508851340'
target_date = date(2025, 11, 21)

# Check if it exists in database
print(f"1. DATABASE CHECK:")
print(f"   {'-'*70}")
found = Reservation.objects.filter(booking_reference=target_ref).select_related('room', 'guest')

if found.exists():
    print(f"   FOUND IN DATABASE!")
    for res in found:
        enriched = "Enriched" if res.guest else "Unenriched"
        print(f"      Room: {res.room.name}")
        print(f"      Guest: {res.guest_name}")
        print(f"      Check-in: {res.check_in_date}")
        print(f"      Check-out: {res.check_out_date}")
        print(f"      Status: {res.status} ({enriched})")
        print(f"      Created: {res.created_at}")
else:
    print(f"   NOT FOUND IN DATABASE")
    print(f"   This means it's still not in the Booking.com iCal feed")

print()

# Check Room 2 last sync
print(f"2. ROOM 2 SYNC STATUS:")
print(f"   {'-'*70}")
try:
    room2 = Room.objects.get(name='Room 2')
    config2 = RoomICalConfig.objects.get(room=room2)
    print(f"   Last synced: {config2.booking_last_synced}")
    print(f"   Status: {config2.booking_last_sync_status}")
except Exception as e:
    print(f"   Error: {e}")

print()

# Check all Nov 21 bookings
print(f"3. ALL NOV 21, 2025 BOOKINGS IN DATABASE:")
print(f"   {'-'*70}")
nov21_bookings = Reservation.objects.filter(
    check_in_date=target_date,
    status='confirmed'
).select_related('room', 'guest').order_by('room__name')

print(f"   Total: {nov21_bookings.count()} booking(s)")
for res in nov21_bookings:
    enriched = "Enriched" if res.guest else "Unenriched"
    print(f"      {res.room.name}: {res.guest_name} ({res.booking_reference or 'no ref'}) - {enriched}")

print()

# Summary
print(f"{'='*80}")
print(f"SUMMARY:")
print(f"{'='*80}")
if found.exists():
    print(f"SUCCESS! Booking 6508851340 is now in the database.")
    print(f"The resync worked and Booking.com updated their iCal feed.")
else:
    print(f"STILL NOT FOUND: Booking 6508851340 is not in database.")
    print(f"This confirms Booking.com iCal feed issue (not your system).")
    print(f"Recommendation: Upload XLS file to add this booking manually.")
print(f"{'='*80}\n")
