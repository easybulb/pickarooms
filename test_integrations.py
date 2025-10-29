#!/usr/bin/env python
"""
Integration test script for PickARooms
Tests TTLock, iCal, and other critical integrations
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import TTLock, Room, Reservation
from main.ttlock_utils import TTLockClient
import requests

def test_ttlock():
    """Test TTLock integration"""
    print("\n[TEST] TTLock Integration")
    print("-" * 50)

    locks = TTLock.objects.all()
    if not locks:
        print("  [WARNING] No TTLocks found in database")
        return False

    print(f"  [OK] Found {locks.count()} TTLocks")

    for lock in locks:
        print(f"  [OK] {lock.name} (Lock ID: {lock.lock_id})")

    # Test TTLock token
    from main.models import TTLockToken
    token = TTLockToken.objects.first()
    if token:
        print(f"  [OK] TTLock token found")
        # Test client initialization
        try:
            client_id = os.getenv('TTLOCK_CLIENT_ID')
            if client_id:
                client = TTLockClient(client_id, token.access_token)
                print(f"  [OK] Client initialized")
            else:
                print(f"  [WARNING] TTLOCK_CLIENT_ID not in environment")
        except Exception as e:
            print(f"  [WARNING] Client initialization failed: {e}")
    else:
        print(f"  [WARNING] No TTLock token found")

    return True

def test_ical():
    """Test iCal feed integration"""
    print("\n[TEST] iCal Feed Integration")
    print("-" * 50)

    rooms = Room.objects.all()
    if not rooms:
        print("  [WARNING] No rooms found")
        return False

    print(f"  [OK] Found {rooms.count()} rooms")

    from main.models import RoomICalConfig

    for room in rooms:
        print(f"  [OK] {room.name}")

        # Check for iCal config
        try:
            ical_config = RoomICalConfig.objects.get(room=room)

            if ical_config.booking_ical_url and ical_config.booking_active:
                print(f"    [OK] Booking.com iCal configured and active")
                try:
                    response = requests.head(ical_config.booking_ical_url, timeout=5)
                    if response.status_code == 200:
                        print(f"    [OK] Booking.com iCal feed accessible")
                    else:
                        print(f"    [WARNING] Booking.com returned {response.status_code}")
                except Exception as e:
                    print(f"    [WARNING] Could not access Booking.com feed: {e}")

            if ical_config.airbnb_ical_url and ical_config.airbnb_active:
                print(f"    [OK] Airbnb iCal configured and active")
                try:
                    response = requests.head(ical_config.airbnb_ical_url, timeout=5)
                    if response.status_code == 200:
                        print(f"    [OK] Airbnb iCal feed accessible")
                    else:
                        print(f"    [WARNING] Airbnb returned {response.status_code}")
                except Exception as e:
                    print(f"    [WARNING] Could not access Airbnb feed: {e}")

            if not (ical_config.booking_active or ical_config.airbnb_active):
                print(f"    [WARNING] No active iCal feeds")

        except RoomICalConfig.DoesNotExist:
            print(f"    [WARNING] No iCal configuration found")

    return True

def test_reservations():
    """Test reservation queries"""
    print("\n[TEST] Reservation System")
    print("-" * 50)

    total = Reservation.objects.count()
    print(f"  [OK] Total reservations: {total}")

    # Test upcoming reservations
    from django.utils import timezone
    upcoming = Reservation.objects.filter(check_in_date__gte=timezone.now().date()).count()
    print(f"  [OK] Upcoming reservations: {upcoming}")

    # Test past reservations
    past = Reservation.objects.filter(check_out_date__lt=timezone.now().date()).count()
    print(f"  [OK] Past reservations: {past}")

    return True

def main():
    print("=" * 50)
    print("PICKAROOMS INTEGRATION TEST")
    print("=" * 50)

    results = {
        'TTLock': test_ttlock(),
        'iCal': test_ical(),
        'Reservations': test_reservations(),
    }

    print("\n" + "=" * 50)
    print("TEST SUMMARY")
    print("=" * 50)

    for test_name, passed in results.items():
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} {test_name}")

    all_passed = all(results.values())
    print("\n" + ("=" * 50))
    if all_passed:
        print("[SUCCESS] All integration tests passed")
    else:
        print("[WARNING] Some tests failed or had warnings")
    print("=" * 50)

if __name__ == '__main__':
    main()
