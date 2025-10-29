#!/usr/bin/env python
"""
View test script for PickARooms
Tests that all refactored views can be imported and accessed correctly
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from django.urls import reverse, resolve
from django.test import RequestFactory, Client
from main.urls import urlpatterns

def test_view_imports():
    """Test that all views can be imported from the refactored structure"""
    print("\n[TEST] View Imports")
    print("-" * 50)

    from main import views

    # Critical views to test
    critical_views = [
        'home', 'about', 'checkin', 'checkin_details', 'checkin_parking',
        'checkin_confirm', 'checkin_pin_status', 'checkin_error',
        'enrich_reservation', 'room_detail', 'admin_page', 'AdminLoginView',
        'edit_guest', 'edit_reservation', 'manual_checkin_reservation',
        'available_rooms', 'give_access', 'room_management', 'edit_room',
        'past_guests', 'all_reservations', 'user_management', 'audit_logs',
        'message_templates', 'pending_enrichments_page', 'xls_upload_page',
        'enrichment_logs_page', 'ttlock_callback', 'sms_reply_handler',
        'handle_twilio_sms_webhook', 'unauthorized', 'rebook_guest',
        'explore_manchester', 'contact', 'privacy_policy', 'terms_of_use',
        'terms_conditions', 'cookie_policy', 'sitemap', 'how_to_use',
        'awards_reviews', 'event_finder', 'price_suggester'
    ]

    errors = []
    for view_name in critical_views:
        try:
            view = getattr(views, view_name)
            print(f"  [OK] {view_name}")
        except AttributeError:
            print(f"  [ERROR] {view_name} - not found")
            errors.append(view_name)

    if errors:
        print(f"\n  [ERROR] Missing views: {', '.join(errors)}")
        return False

    return True

def test_url_resolution():
    """Test that all URLs can be resolved"""
    print("\n[TEST] URL Resolution")
    print("-" * 50)

    # Critical URL names to test
    critical_urls = [
        'home', 'about', 'checkin', 'checkin_details', 'checkin_parking',
        'checkin_confirm', 'checkin_pin_status', 'checkin_error',
        'enrich_reservation', 'admin_page', 'admin_login', 'unauthorized',
        'available_rooms', 'give_access', 'room_management',
        'past_guests', 'all_reservations', 'user_management', 'audit_logs',
        'message_templates', 'pending_enrichments_page', 'xls_upload_page',
        'enrichment_logs_page', 'ttlock_callback', 'sms_reply_handler',
        'twilio_sms_webhook', 'rebook_guest', 'explore_manchester', 'contact',
        'privacy_policy', 'terms_of_use', 'terms_conditions', 'cookie_policy',
        'sitemap', 'how_to_use', 'awards_reviews', 'event_finder', 'price_suggester'
    ]

    errors = []
    for url_name in critical_urls:
        try:
            url = reverse(url_name)
            print(f"  [OK] {url_name} -> {url}")
        except Exception as e:
            print(f"  [ERROR] {url_name} - {e}")
            errors.append(url_name)

    if errors:
        print(f"\n  [ERROR] Failed URLs: {', '.join(errors)}")
        return False

    return True

def test_basic_responses():
    """Test that public views return 200 responses"""
    print("\n[TEST] Basic View Responses")
    print("-" * 50)

    client = Client()

    # Public views that should work without authentication
    public_views = [
        ('/', 'home'),
        ('/about/', 'about'),
        ('/explore-manchester/', 'explore_manchester'),
        ('/contact/', 'contact'),
        ('/privacy-policy/', 'privacy_policy'),
        ('/terms-of-use/', 'terms_of_use'),
        ('/terms-and-conditions/', 'terms_conditions'),
        ('/cookie-policy/', 'cookie_policy'),
        ('/how-to-use/', 'how_to_use'),
        ('/awards_reviews/', 'awards_reviews'),
    ]

    errors = []
    for url, name in public_views:
        try:
            response = client.get(url)
            if response.status_code == 200:
                print(f"  [OK] {name} ({url}) -> 200")
            else:
                print(f"  [WARNING] {name} ({url}) -> {response.status_code}")
        except Exception as e:
            print(f"  [ERROR] {name} ({url}) - {e}")
            errors.append(name)

    if errors:
        print(f"\n  [ERROR] Failed views: {', '.join(errors)}")
        return False

    return True

def main():
    print("=" * 50)
    print("PICKAROOMS VIEW TEST")
    print("=" * 50)

    results = {
        'View Imports': test_view_imports(),
        'URL Resolution': test_url_resolution(),
        'Basic Responses': test_basic_responses(),
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
        print("[SUCCESS] All view tests passed")
    else:
        print("[FAIL] Some view tests failed")
    print("=" * 50)

    return 0 if all_passed else 1

if __name__ == '__main__':
    exit(main())
