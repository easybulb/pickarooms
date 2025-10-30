"""
Check iCal configurations for all rooms, especially Room 2 and Room 4
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import Room, RoomICalConfig

print(f"\n{'='*80}")
print(f"iCAL CONFIGURATION CHECK")
print(f"{'='*80}\n")

rooms = Room.objects.all().order_by('name')

for room in rooms:
    print(f"{room.name}:")
    print(f"   {'-'*70}")
    
    try:
        config = RoomICalConfig.objects.get(room=room)
        
        # Booking.com
        print(f"   Booking.com:")
        print(f"      Active: {config.booking_active}")
        print(f"      URL: {config.booking_ical_url[:80] if config.booking_ical_url else 'None'}...")
        print(f"      Last synced: {config.booking_last_synced}")
        print(f"      Last status: {config.booking_last_sync_status}")
        
        # Airbnb
        print(f"   Airbnb:")
        print(f"      Active: {config.airbnb_active}")
        print(f"      URL: {config.airbnb_ical_url[:80] if config.airbnb_ical_url else 'None'}...")
        print(f"      Last synced: {config.airbnb_last_synced}")
        print(f"      Last status: {config.airbnb_last_sync_status}")
        
    except RoomICalConfig.DoesNotExist:
        print(f"   NO iCAL CONFIG FOUND!")
    
    print()

print(f"{'='*80}\n")
print("RECOMMENDATION:")
print("1. Check if Room 2 and Room 4 have active Booking.com configs")
print("2. Check if URLs are correct")
print("3. Try manual sync from admin page if configs look good")
print(f"{'='*80}\n")
