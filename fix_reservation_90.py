"""
Fix Reservation ID 90 - Add booking reference manually
Run with: heroku run python fix_reservation_90.py -a pickarooms
"""

import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import Reservation

print("=" * 60)
print("FIXING RESERVATION ID 90")
print("=" * 60)

try:
    res = Reservation.objects.get(id=90)
    
    print(f"\nCurrent state:")
    print(f"  ID: {res.id}")
    print(f"  Booking Ref: {res.booking_reference or 'NOT SET'}")
    print(f"  Guest Name: {res.guest_name}")
    print(f"  Room: {res.room.name}")
    print(f"  Check-in: {res.check_in_date}")
    print(f"  Check-out: {res.check_out_date}")
    print(f"  Status: {res.status}")
    
    # ASK USER FOR INPUT
    print("\n" + "=" * 60)
    print("ENTER THE CORRECT BOOKING REFERENCE:")
    print("(Press Ctrl+C to cancel)")
    print("=" * 60)
    
    booking_ref = input("\nBooking Reference: ").strip()
    guest_name = input("Guest Name (optional, press Enter to skip): ").strip()
    
    if booking_ref:
        res.booking_reference = booking_ref
        if guest_name:
            res.guest_name = guest_name
        res.save()
        
        print("\n✅ SUCCESS!")
        print(f"  Updated booking reference to: {res.booking_reference}")
        if guest_name:
            print(f"  Updated guest name to: {res.guest_name}")
    else:
        print("\n❌ No booking reference provided. Cancelled.")
        
except Reservation.DoesNotExist:
    print("\n❌ Reservation ID 90 not found!")
except Exception as e:
    print(f"\n❌ Error: {str(e)}")

print("\n" + "=" * 60)
