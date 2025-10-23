"""
Diagnostic script to check production data
Run with: heroku run python check_production_data.py -a pickarooms
"""

from datetime import date
from main.models import Reservation, Guest, CSVEnrichmentLog

print("=" * 60)
print("PRODUCTION DATA DIAGNOSTIC")
print("=" * 60)

today = date.today()
print(f"\nToday's date: {today}")

# Check today's reservations
print("\n--- TODAY'S RESERVATIONS ---")
todays_reservations = Reservation.objects.filter(check_in_date=today)
print(f"Total count: {todays_reservations.count()}")

for res in todays_reservations:
    print(f"\n  ID: {res.id}")
    print(f"  Booking Ref: {res.booking_reference or 'NOT SET'}")
    print(f"  Guest Name: {res.guest_name or 'NOT SET'}")
    print(f"  Room: {res.room.name}")
    print(f"  Platform: {res.platform}")
    print(f"  Status: {res.status}")
    print(f"  Has Guest?: {'YES - ENRICHED' if res.guest else 'NO - UNENRICHED'}")
    if res.guest:
        print(f"    Guest Full Name: {res.guest.full_name}")
        print(f"    Guest Phone: {res.guest.phone_number}")

# Check today's guests
print("\n--- TODAY'S GUESTS ---")
todays_guests = Guest.objects.filter(check_in_date=today, is_archived=False)
print(f"Total count: {todays_guests.count()}")

for guest in todays_guests:
    print(f"\n  ID: {guest.id}")
    print(f"  Name: {guest.full_name}")
    print(f"  Booking Ref: {guest.reservation_number}")
    print(f"  Room: {guest.assigned_room.name}")
    print(f"  Front Door PIN: {guest.front_door_pin or 'NOT SET'}")
    print(f"  Room PIN ID: {guest.room_pin_id or 'NOT SET'}")

# Check recent XLS uploads
print("\n--- RECENT XLS UPLOADS ---")
recent_logs = CSVEnrichmentLog.objects.all().order_by('-uploaded_at')[:5]
print(f"Total upload logs: {CSVEnrichmentLog.objects.count()}")

for log in recent_logs:
    print(f"\n  ID: {log.id}")
    print(f"  Uploaded: {log.uploaded_at}")
    print(f"  File: {log.file_name}")
    print(f"  By: {log.uploaded_by.username if log.uploaded_by else 'Unknown'}")
    print(f"  Total rows: {log.total_rows}")
    print(f"  Created: {log.created_count}")
    print(f"  Updated: {log.updated_count}")
    print(f"  Multi-room: {log.multi_room_count}")

# Check if there are reservations without booking references
print("\n--- RESERVATIONS WITHOUT BOOKING REFERENCE ---")
no_ref = Reservation.objects.filter(
    check_in_date=today,
    booking_reference__isnull=True
) | Reservation.objects.filter(
    check_in_date=today,
    booking_reference=''
)
print(f"Count: {no_ref.count()}")

for res in no_ref:
    print(f"\n  ID: {res.id}")
    print(f"  Guest Name: {res.guest_name or 'NOT SET'}")
    print(f"  Room: {res.room.name}")
    print(f"  iCal UID: {res.ical_uid[:50]}..." if len(res.ical_uid or '') > 50 else f"  iCal UID: {res.ical_uid}")

print("\n" + "=" * 60)
print("END OF DIAGNOSTIC")
print("=" * 60)
