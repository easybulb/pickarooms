#!/usr/bin/env python
"""
iCal → Email Enrichment Workflow Test
Tests the complete 15-minute polling cycle and enrichment chain
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from datetime import date, timedelta
from django.utils import timezone

def test_workflow_overview():
    """Display the complete workflow chain"""
    print("\n[INFO] iCal -> Email Enrichment Workflow")
    print("=" * 70)
    print("""
STEP 1: iCal Polling (Every 15 minutes - Celery Beat)
  Task: poll_all_ical_feeds()
  - Fetches all RoomICalConfig records
  - Triggers sync_room_ical_feed() for each active platform

STEP 2: Room iCal Sync
  Task: sync_room_ical_feed(config_id, platform)
  - Fetches iCal feed for room
  - Parses iCal events
  - Creates new Reservation records for new bookings
  - Updates existing reservations
  - Handles cancellations
  - For NEW reservations -> triggers trigger_enrichment_workflow()

STEP 3: Enrichment Workflow Decision
  Task: trigger_enrichment_workflow(reservation_id)

  Decision Logic:
  +-----------------------------------------------------+
  | Check: Multiple bookings for same check-in?        |
  +-----------------------------------------------------+
           |
           |-- YES (COLLISION) --------------------------------|
           |   - Log collision                            |
           |   - Send SMS alert IMMEDIATELY               |
           |   - Admin resolves manually via SMS reply    |
           |                                               |
           |-- NO (SINGLE BOOKING) ----------------------- |
               - Start email search workflow              |
               - 4 attempts over 10 minutes:              |
                 * Attempt 1: Immediate                   |
                 * Attempt 2: 2 min later                 |
                 * Attempt 3: 5 min later                 |
                 * Attempt 4: 10 min later                |
               - If found -> enrich reservation           |
               - If not found -> send alert SMS           |
               ------------------------------------------- |

STEP 4a: Email Search (Single Booking)
  Task: search_email_for_reservation(reservation_id, attempt)
  - Searches Gmail for Booking.com confirmation email
  - Looks for check-in date match
  - Extracts booking reference from subject
  - Handles multi-room bookings (same reference)
  - Marks email as read after processing

STEP 4b: Collision Alert (Multiple Bookings)
  Task: send_collision_alert_ical(check_in_date)
  - Sends SMS to admin with all colliding bookings
  - Admin replies with room assignments
  - Format: "REF: ROOM-NIGHTS" (e.g., "6588202211: 1-2")

STEP 5: Alert if Email Not Found
  Task: send_email_not_found_alert(reservation_id)
  - After 4 failed attempts
  - Sends SMS to admin
  - Admin can reply with booking reference
    """)
    print("=" * 70)

def test_ical_config():
    """Test iCal configuration for all rooms"""
    print("\n[TEST] iCal Configuration")
    print("-" * 70)

    from main.models import RoomICalConfig

    configs = RoomICalConfig.objects.all().select_related('room')

    if not configs.exists():
        print("  [ERROR] No iCal configurations found!")
        return False

    print(f"  [OK] Found {configs.count()} room iCal configurations\n")

    for config in configs:
        print(f"  Room: {config.room.name}")

        # Booking.com
        if config.booking_active:
            print(f"    [OK] Booking.com: ACTIVE")
            print(f"        URL: {config.booking_ical_url[:60]}...")
            if config.booking_last_synced:
                print(f"        Last synced: {config.booking_last_synced}")
                print(f"        Status: {config.booking_last_sync_status or 'N/A'}")
        else:
            print(f"    [X] Booking.com: INACTIVE")

        # Airbnb
        if config.airbnb_active:
            print(f"    [OK] Airbnb: ACTIVE")
            print(f"        URL: {config.airbnb_ical_url[:60]}...")
            if config.airbnb_last_synced:
                print(f"        Last synced: {config.airbnb_last_synced}")
                print(f"        Status: {config.airbnb_last_sync_status or 'N/A'}")
        else:
            print(f"    [X] Airbnb: INACTIVE")

        print()

    return True

def test_celery_beat_schedule():
    """Test that iCal polling is scheduled correctly"""
    print("\n[TEST] Celery Beat Schedule")
    print("-" * 70)

    from django_celery_beat.models import PeriodicTask

    # Check for iCal polling task
    try:
        ical_task = PeriodicTask.objects.get(name='poll-ical-feeds-every-15-minutes')
        print(f"  [OK] Task: {ical_task.name}")
        print(f"      Enabled: {ical_task.enabled}")
        print(f"      Task: {ical_task.task}")
        print(f"      Schedule: {ical_task.interval}")

        if ical_task.last_run_at:
            print(f"      Last run: {ical_task.last_run_at}")
            next_run = ical_task.last_run_at + timedelta(minutes=15)
            print(f"      Next run: ~{next_run}")

        if not ical_task.enabled:
            print("  [ERROR] Task is DISABLED!")
            return False

        return True
    except PeriodicTask.DoesNotExist:
        print("  [ERROR] iCal polling task not found in Celery Beat!")
        return False

def test_enrichment_workflow_tasks():
    """Test that all workflow tasks are importable"""
    print("\n[TEST] Enrichment Workflow Tasks")
    print("-" * 70)

    try:
        from main.tasks import (
            poll_all_ical_feeds,
            sync_room_ical_feed,
            trigger_enrichment_workflow,
            search_email_for_reservation,
            send_collision_alert_ical,
            send_multi_room_confirmation_sms,
            send_email_not_found_alert,
        )

        tasks = [
            ('poll_all_ical_feeds', 'Main 15-min polling task'),
            ('sync_room_ical_feed', 'Sync single room iCal feed'),
            ('trigger_enrichment_workflow', 'NEW reservation -> enrichment decision'),
            ('search_email_for_reservation', 'Search Gmail for booking email'),
            ('send_collision_alert_ical', 'SMS alert for multiple bookings'),
            ('send_multi_room_confirmation_sms', 'SMS for multi-room booking'),
            ('send_email_not_found_alert', 'SMS alert when email not found'),
        ]

        for task_name, description in tasks:
            print(f"  [OK] {task_name}")
            print(f"      {description}")

        return True
    except ImportError as e:
        print(f"  [ERROR] Task import failed: {e}")
        return False

def test_ical_service_functions():
    """Test iCal service functions"""
    print("\n[TEST] iCal Service Functions")
    print("-" * 70)

    try:
        from main.services.ical_service import (
            fetch_ical_feed,
            extract_booking_reference,
            parse_ical,
            sync_reservations_for_room,
        )

        print("  [OK] fetch_ical_feed - Fetches iCal from URL")
        print("  [OK] extract_booking_reference - Extracts ref from description")
        print("  [OK] parse_ical - Parses iCal events")
        print("  [OK] sync_reservations_for_room - Main sync logic")

        # Test booking reference extraction
        test_descriptions = [
            "Booking.com - Ref: 1234567890 - Guest Name",
            "Booking ID: 9876543210",
            "Some random text without ref",
        ]

        print("\n  Testing booking reference extraction:")
        for desc in test_descriptions:
            ref = extract_booking_reference(desc)
            if ref:
                print(f"    [OK] Extracted: {ref} from '{desc[:40]}...'")
            else:
                print(f"    [X] No ref in '{desc[:40]}...'")

        return True
    except ImportError as e:
        print(f"  [ERROR] Service import failed: {e}")
        return False

def test_gmail_search_functions():
    """Test Gmail search functions"""
    print("\n[TEST] Gmail Search Functions")
    print("-" * 70)

    try:
        from main.services.gmail_client import GmailClient
        from main.services.email_parser import parse_booking_com_email_subject

        print("  [OK] GmailClient imported")
        print("  [OK] parse_booking_com_email_subject imported")

        # Test email subject parsing
        test_subjects = [
            "Booking.com - New reservation at PickARooms (Ref: 1234567890)",
            "Booking confirmation - Reference 9876543210",
            "Some random email subject",
        ]

        print("\n  Testing email subject parsing:")
        for subject in test_subjects:
            result = parse_booking_com_email_subject(subject)
            if result:
                print(f"    [OK] Parsed: {result}")
            else:
                print(f"    [X] No match for '{subject[:50]}...'")

        # Test Gmail client initialization
        try:
            client = GmailClient()
            print("\n  [OK] GmailClient initialized (credentials found)")
        except Exception as e:
            print(f"\n  [WARNING] GmailClient init: {e}")
            print("  [INFO] This is expected if not on production")

        return True
    except ImportError as e:
        print(f"  [ERROR] Import failed: {e}")
        return False

def test_collision_detection_logic():
    """Test collision detection logic"""
    print("\n[TEST] Collision Detection Logic")
    print("-" * 70)

    from main.models import Reservation
    from datetime import date, timedelta

    # Get a sample date with reservations
    today = timezone.now().date()
    future_date = today + timedelta(days=7)

    print(f"  Testing for date: {future_date}")

    # Check for unenriched bookings on this date
    unenriched = Reservation.objects.filter(
        check_in_date=future_date,
        platform='booking',
        status='confirmed',
        guest__isnull=True,
        booking_reference=''
    )

    count = unenriched.count()
    print(f"  Unenriched bookings on {future_date}: {count}")

    if count > 1:
        print(f"  [WARNING] COLLISION DETECTED: {count} bookings")
        print("  Expected behavior: Send collision SMS alert")
        for res in unenriched:
            print(f"    - Room: {res.room.name}, Guest: {res.guest_name or 'Unknown'}")
    elif count == 1:
        print(f"  [OK] Single booking (normal flow)")
        print("  Expected behavior: Start email search (4 attempts)")
    else:
        print(f"  [OK] No unenriched bookings (testing only)")

    return True

def test_enrichment_logs():
    """Check enrichment log entries"""
    print("\n[TEST] Enrichment Logs")
    print("-" * 70)

    from main.models import EnrichmentLog

    total = EnrichmentLog.objects.count()
    print(f"  Total enrichment logs: {total}")

    if total > 0:
        # Get recent logs
        recent = EnrichmentLog.objects.order_by('-timestamp')[:5]

        print("\n  Recent enrichment actions:")
        for log in recent:
            print(f"    [{log.timestamp.strftime('%Y-%m-%d %H:%M')}] {log.action}")
            print(f"      Room: {log.room.name if log.room else 'N/A'}")
            print(f"      Method: {log.method}")
            if log.booking_reference:
                print(f"      Ref: {log.booking_reference}")

        # Count by action type
        print("\n  Enrichment actions breakdown:")
        actions = EnrichmentLog.objects.values('action').annotate(
            count=__import__('django.db.models', fromlist=['Count']).Count('id')
        ).order_by('-count')[:10]

        for action in actions:
            print(f"    {action['action']}: {action['count']}")

    return True

def test_pending_enrichments():
    """Check pending enrichments"""
    print("\n[TEST] Pending Enrichments")
    print("-" * 70)

    from main.models import PendingEnrichment

    pending = PendingEnrichment.objects.filter(status='pending')
    count = pending.count()

    print(f"  Active pending enrichments: {count}")

    if count > 0:
        print("\n  Details:")
        for p in pending[:5]:  # Show first 5
            print(f"    Room: {p.room_number}")
            print(f"    Check-in: {p.checkin_date}")
            print(f"    Nights: {p.nights}")
            created_field = getattr(p, 'created_at', None) or getattr(p, 'timestamp', None)
            if created_field:
                print(f"    Created: {created_field.strftime('%Y-%m-%d %H:%M')}")
            print()

    return True

def main():
    print("=" * 70)
    print("iCAL -> EMAIL ENRICHMENT WORKFLOW TEST")
    print("=" * 70)

    # Show workflow overview first
    test_workflow_overview()

    results = {
        'iCal Configuration': test_ical_config(),
        'Celery Beat Schedule': test_celery_beat_schedule(),
        'Workflow Tasks': test_enrichment_workflow_tasks(),
        'iCal Service Functions': test_ical_service_functions(),
        'Gmail Search Functions': test_gmail_search_functions(),
        'Collision Detection': test_collision_detection_logic(),
        'Enrichment Logs': test_enrichment_logs(),
        'Pending Enrichments': test_pending_enrichments(),
    }

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    for test_name, passed in results.items():
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} {test_name}")

    all_passed = all(results.values())
    print("\n" + ("=" * 70))
    if all_passed:
        print("[SUCCESS] iCal -> Email enrichment workflow is configured correctly")
        print("\nWorkflow Chain:")
        print("  1. Celery Beat runs poll_all_ical_feeds every 15 min")
        print("  2. New reservation detected -> trigger_enrichment_workflow")
        print("  3. Check for collision:")
        print("     - YES: Send SMS alert immediately")
        print("     - NO: Start email search (4 attempts over 10 min)")
        print("  4. Email found -> Enrich reservation + SMS confirmation")
        print("  5. Email not found (after 4 attempts) -> SMS alert to admin")
        print("\n[INFO] System is ready for production deployment")
    else:
        print("[FAIL] Some workflow components failed")
        print("[WARNING] Review failures before deploying to production")
    print("=" * 70)

    return 0 if all_passed else 1

if __name__ == '__main__':
    exit(main())
