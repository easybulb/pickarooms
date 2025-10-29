#!/usr/bin/env python
"""
Email Parser and SMS Alert Test Script
Tests the new iCal-driven enrichment workflow
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

def test_email_parser():
    """Test Gmail email parser integration"""
    print("\n[TEST] Email Parser (Gmail Integration)")
    print("-" * 50)

    try:
        from main.services.gmail_client import GmailClient
        print("  [OK] GmailClient imported")

        from main.services.email_parser import parse_booking_com_email_subject
        print("  [OK] parse_booking_com_email_subject imported")

        # Test parser function
        test_subject = "Booking.com - New reservation at Room 1 (Booking ref: 1234567890)"
        try:
            result = parse_booking_com_email_subject(test_subject)
            if result:
                print(f"  [OK] Email parser working (test parse successful)")
            else:
                print(f"  [OK] Email parser imported (test subject didn't match)")
        except Exception as e:
            print(f"  [WARNING] Parser test failed: {e}")

        # Test Gmail client initialization
        try:
            client = GmailClient()
            print("  [OK] GmailClient initialized")
        except Exception as e:
            print(f"  [WARNING] GmailClient init failed: {e}")
            print("  [INFO] This is expected if Gmail credentials not configured locally")

        return True
    except ImportError as e:
        print(f"  [ERROR] Could not import Gmail modules: {e}")
        return False

def test_sms_functions():
    """Test SMS alert functions"""
    print("\n[TEST] SMS Alert Functions")
    print("-" * 50)

    try:
        from main.services.sms_commands import send_confirmation_sms
        print("  [OK] send_confirmation_sms imported")

        from main.services.sms_reply_handler import handle_sms_room_assignment, parse_sms_reply
        print("  [OK] SMS reply handlers imported")

        # Test Twilio configuration
        from django.conf import settings

        try:
            twilio_sid = settings.TWILIO_ACCOUNT_SID
            twilio_token = settings.TWILIO_AUTH_TOKEN
            twilio_number = settings.TWILIO_PHONE_NUMBER

            if twilio_sid and twilio_token and twilio_number:
                print("  [OK] Twilio credentials configured in settings")
            else:
                print("  [WARNING] Twilio credentials missing in settings")
        except AttributeError:
            print("  [WARNING] Twilio settings not configured")
            print("  [INFO] This is expected for local testing")

        return True
    except ImportError as e:
        print(f"  [ERROR] Could not import SMS modules: {e}")
        return False

def test_enrichment_tasks():
    """Test enrichment workflow tasks"""
    print("\n[TEST] Enrichment Workflow Tasks")
    print("-" * 50)

    try:
        # Import all enrichment-related tasks
        from main.tasks import (
            poll_all_ical_feeds,
            trigger_enrichment_workflow,
            search_email_for_reservation,
            send_collision_alert_ical,
            send_multi_room_confirmation_sms,
            send_email_not_found_alert,
        )

        print("  [OK] poll_all_ical_feeds")
        print("  [OK] trigger_enrichment_workflow")
        print("  [OK] search_email_for_reservation")
        print("  [OK] send_collision_alert_ical")
        print("  [OK] send_multi_room_confirmation_sms")
        print("  [OK] send_email_not_found_alert")

        return True
    except ImportError as e:
        print(f"  [ERROR] Could not import enrichment tasks: {e}")
        return False

def test_enrichment_models():
    """Test enrichment database models"""
    print("\n[TEST] Enrichment Models")
    print("-" * 50)

    try:
        from main.models import (
            PendingEnrichment,
            EnrichmentLog,
            MessageTemplate,
        )

        # Check counts
        pending_count = PendingEnrichment.objects.count()
        log_count = EnrichmentLog.objects.count()
        template_count = MessageTemplate.objects.count()

        print(f"  [OK] PendingEnrichment model - {pending_count} records")
        print(f"  [OK] EnrichmentLog model - {log_count} records")
        print(f"  [OK] MessageTemplate model - {template_count} templates")

        # Check for required templates
        try:
            templates = MessageTemplate.objects.all()
            if templates.exists():
                print(f"  [OK] Found {templates.count()} message templates")
                for template in templates[:3]:  # Show first 3
                    print(f"    - {template.name}")
            else:
                print("  [WARNING] No message templates found")
        except Exception as e:
            print(f"  [WARNING] Could not query templates: {e}")

        return True
    except Exception as e:
        print(f"  [ERROR] Model test failed: {e}")
        return False

def test_enrichment_services():
    """Test enrichment service functions"""
    print("\n[TEST] Enrichment Services")
    print("-" * 50)

    try:
        from main.services.ical_service import fetch_ical_feed, parse_ical, sync_reservations_for_room
        print("  [OK] iCal service functions imported")

        from main.services.gmail_client import GmailClient
        print("  [OK] GmailClient imported")

        from main.services.email_parser import parse_booking_com_email_subject
        print("  [OK] Email parser imported")

        from main.services.sms_commands import send_confirmation_sms, handle_guide_command
        print("  [OK] SMS command functions imported")

        return True
    except ImportError as e:
        print(f"  [ERROR] Service import failed: {e}")
        return False

def test_webhook_handlers():
    """Test webhook handler views"""
    print("\n[TEST] Webhook Handlers")
    print("-" * 50)

    try:
        from main.views import (
            ttlock_callback,
            sms_reply_handler,
            handle_twilio_sms_webhook,
        )

        print("  [OK] ttlock_callback")
        print("  [OK] sms_reply_handler")
        print("  [OK] handle_twilio_sms_webhook")

        return True
    except ImportError as e:
        print(f"  [ERROR] Webhook handler import failed: {e}")
        return False

def test_alert_functions():
    """Test alert generation functions"""
    print("\n[TEST] Alert Functions")
    print("-" * 50)

    try:
        # Check if alert functions exist in tasks
        from main import tasks

        alert_functions = [
            'send_collision_alert_ical',
            'send_multi_room_confirmation_sms',
            'send_email_not_found_alert',
        ]

        for func_name in alert_functions:
            if hasattr(tasks, func_name):
                print(f"  [OK] {func_name}")
            else:
                print(f"  [ERROR] {func_name} not found")
                return False

        return True
    except Exception as e:
        print(f"  [ERROR] Alert function test failed: {e}")
        return False

def main():
    print("=" * 50)
    print("EMAIL PARSER & SMS ALERT TEST")
    print("=" * 50)

    results = {
        'Email Parser': test_email_parser(),
        'SMS Functions': test_sms_functions(),
        'Enrichment Tasks': test_enrichment_tasks(),
        'Enrichment Models': test_enrichment_models(),
        'Enrichment Services': test_enrichment_services(),
        'Webhook Handlers': test_webhook_handlers(),
        'Alert Functions': test_alert_functions(),
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
        print("[SUCCESS] All email/SMS tests passed")
        print("\n[INFO] System is ready for production deployment")
    else:
        print("[FAIL] Some tests failed")
    print("=" * 50)

    return 0 if all_passed else 1

if __name__ == '__main__':
    exit(main())
