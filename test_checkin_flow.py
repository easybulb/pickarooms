#!/usr/bin/env python3
"""
Test script to verify check-in flow is working
This simulates the background PIN generation task
"""

import os
import sys
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from django.contrib.sessions.backends.db import SessionStore
from main.tasks import generate_checkin_pin_background
from main.models import Reservation
from django.utils import timezone

def test_pin_generation():
    print("\n" + "="*60)
    print("TEST: Background PIN Generation")
    print("="*60)
    
    # Create a test session
    session_store = SessionStore()
    
    # Find a test reservation (unenriched)
    test_reservation = Reservation.objects.filter(
        status='confirmed',
        guest__isnull=True
    ).first()
    
    if not test_reservation:
        print("[ERROR] No unenriched reservations found for testing")
        print("       Create a test reservation first")
        return False
    
    print(f"\n[OK] Found test reservation:")
    print(f"     ID: {test_reservation.id}")
    print(f"     Room: {test_reservation.room.name}")
    print(f"     Check-in: {test_reservation.check_in_date}")
    
    # Create test session data
    flow_data = {
        'booking_ref': test_reservation.booking_reference or 'TEST123',
        'reservation_id': test_reservation.id,
        'step': 2,
        'full_name': 'Test Guest',
        'phone_number': '+447123456789',
        'email': 'test@example.com',
    }
    
    session_store['checkin_flow'] = flow_data
    session_store.create()
    session_key = session_store.session_key
    
    print(f"\n[OK] Created test session: {session_key}")
    print(f"\n[INFO] Triggering background PIN generation task...")
    
    # Trigger the task (will run synchronously since worker is running)
    try:
        result = generate_checkin_pin_background.delay(session_key)
        print(f"[OK] Task triggered: {result.id}")
        print(f"\n[INFO] Waiting for task to complete...")
        
        # Wait for result (timeout 30 seconds)
        task_result = result.get(timeout=30)
        print(f"\n[OK] Task completed: {task_result}")
        
        # Check if PIN was generated
        session_store = SessionStore(session_key=session_key)
        updated_flow_data = session_store.get('checkin_flow', {})
        
        if updated_flow_data.get('pin_generated') == True:
            pin = updated_flow_data.get('pin')
            print(f"\n[SUCCESS] PIN generated: {pin}")
            print(f"          Front door PIN ID: {updated_flow_data.get('front_door_pin_id')}")
            print(f"          Room PIN ID: {updated_flow_data.get('room_pin_id')}")
            return True
        else:
            error = updated_flow_data.get('pin_error', 'Unknown error')
            print(f"\n[FAILED] PIN generation failed: {error}")
            return False
            
    except Exception as e:
        print(f"\n[ERROR] Task failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("\n" + "="*60)
    print("PICKAROOMS CHECK-IN FLOW TEST")
    print("="*60)
    
    print("\n[INFO] Testing if Celery worker is running...")
    print("       (Make sure you started it with: celery -A pickarooms worker)")
    
    # Test PIN generation
    success = test_pin_generation()
    
    print("\n" + "="*60)
    print("TEST RESULTS")
    print("="*60)
    
    if success:
        print("\n[SUCCESS] Check-in flow is working!")
        print("\nNext steps:")
        print("1. Try checking in through the website")
        print("2. Monitor debug.log for any errors")
        print("3. Check Celery worker output for task execution")
        return 0
    else:
        print("\n[FAILED] Check-in flow has issues")
        print("\nTroubleshooting:")
        print("1. Check if Celery worker is running")
        print("2. Check if Redis is running")
        print("3. Check TTLock credentials in settings")
        print("4. Check debug.log for errors")
        return 1


if __name__ == "__main__":
    sys.exit(main())
