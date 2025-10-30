"""
Comprehensive iCal Sync Diagnostics
Check if iCal feeds are working properly or if there's a sync issue
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import RoomICalConfig, Reservation
from main.services.ical_service import fetch_ical_feed, parse_ical
from datetime import datetime, date
from django.utils import timezone

print(f"\n{'='*80}")
print(f"iCAL SYNC DIAGNOSTICS")
print(f"Current time (UTC): {timezone.now().strftime('%Y-%m-%d %H:%M:%S %Z')}")
print(f"{'='*80}\n")

# 1. Check all iCal configurations
print(f"{'='*80}")
print(f"STEP 1: iCAL CONFIGURATIONS")
print(f"{'='*80}\n")

configs = RoomICalConfig.objects.all().select_related('room')

if not configs.exists():
    print("⚠️  No iCal configurations found!")
else:
    print(f"Found {configs.count()} room configuration(s):\n")
    
    for config in configs:
        print(f"🏠 {config.room.name}")
        print(f"   {'─'*70}")
        
        # Booking.com
        print(f"   📘 BOOKING.COM:")
        if config.booking_active and config.booking_ical_url:
            print(f"      Status: ✅ ACTIVE")
            print(f"      URL: {config.booking_ical_url[:80]}...")
            print(f"      Last synced: {config.booking_last_synced.strftime('%Y-%m-%d %H:%M:%S %Z') if config.booking_last_synced else 'Never'}")
            print(f"      Last status: {config.booking_last_sync_status or 'N/A'}")
        else:
            print(f"      Status: ❌ INACTIVE or NO URL")
        
        # Airbnb
        print(f"   🏡 AIRBNB:")
        if config.airbnb_active and config.airbnb_ical_url:
            print(f"      Status: ✅ ACTIVE")
            print(f"      URL: {config.airbnb_ical_url[:80]}...")
            print(f"      Last synced: {config.airbnb_last_synced.strftime('%Y-%m-%d %H:%M:%S %Z') if config.airbnb_last_synced else 'Never'}")
            print(f"      Last status: {config.airbnb_last_sync_status or 'N/A'}")
        else:
            print(f"      Status: ❌ INACTIVE or NO URL")
        
        print()

# 2. Test fetch iCal feeds directly
print(f"\n{'='*80}")
print(f"STEP 2: DIRECT iCAL FEED TEST")
print(f"Testing if feeds are accessible and returning data...")
print(f"{'='*80}\n")

for config in configs:
    print(f"🏠 {config.room.name}")
    print(f"   {'─'*70}")
    
    # Test Booking.com feed
    if config.booking_active and config.booking_ical_url:
        print(f"   📘 Testing Booking.com feed...")
        try:
            ical_data = fetch_ical_feed(config.booking_ical_url, timeout=30)
            events = parse_ical(ical_data)
            print(f"      ✅ SUCCESS: Fetched {len(events)} event(s) from feed")
            
            if events:
                print(f"      📅 Sample events:")
                for i, event in enumerate(events[:3], 1):  # Show first 3
                    status_icon = "✅" if event['status'] == 'CONFIRMED' else "❌"
                    print(f"         [{i}] {status_icon} {event['summary']}")
                    print(f"             Check-in: {event['dtstart']}, Check-out: {event['dtend']}")
                    print(f"             Status: {event['status']}")
                if len(events) > 3:
                    print(f"         ... and {len(events) - 3} more event(s)")
        except Exception as e:
            print(f"      ❌ FAILED: {str(e)}")
    
    # Test Airbnb feed
    if config.airbnb_active and config.airbnb_ical_url:
        print(f"   🏡 Testing Airbnb feed...")
        try:
            ical_data = fetch_ical_feed(config.airbnb_ical_url, timeout=30)
            events = parse_ical(ical_data)
            print(f"      ✅ SUCCESS: Fetched {len(events)} event(s) from feed")
            
            if events:
                print(f"      📅 Sample events:")
                for i, event in enumerate(events[:3], 1):  # Show first 3
                    status_icon = "✅" if event['status'] == 'CONFIRMED' else "❌"
                    print(f"         [{i}] {status_icon} {event['summary']}")
                    print(f"             Check-in: {event['dtstart']}, Check-out: {event['dtend']}")
                    print(f"             Status: {event['status']}")
                if len(events) > 3:
                    print(f"         ... and {len(events) - 3} more event(s)")
        except Exception as e:
            print(f"      ❌ FAILED: {str(e)}")
    
    print()

# 3. Compare iCal feed vs Database
print(f"\n{'='*80}")
print(f"STEP 3: ICAL FEED vs DATABASE COMPARISON")
print(f"Checking if database matches what's in the iCal feeds...")
print(f"{'='*80}\n")

for config in configs:
    print(f"🏠 {config.room.name}")
    print(f"   {'─'*70}")
    
    if config.booking_active and config.booking_ical_url:
        try:
            # Fetch current feed
            ical_data = fetch_ical_feed(config.booking_ical_url, timeout=30)
            events = parse_ical(ical_data)
            
            # Get current database reservations
            db_reservations = Reservation.objects.filter(
                room=config.room,
                platform='booking',
                status='confirmed'
            ).values_list('ical_uid', flat=True)
            
            feed_uids = set([event['uid'] for event in events if event['status'] == 'CONFIRMED'])
            db_uids = set(db_reservations)
            
            # Find discrepancies
            in_feed_not_db = feed_uids - db_uids
            in_db_not_feed = db_uids - feed_uids
            
            print(f"   📘 BOOKING.COM:")
            print(f"      iCal feed: {len(feed_uids)} confirmed event(s)")
            print(f"      Database: {len(db_uids)} confirmed reservation(s)")
            
            if in_feed_not_db:
                print(f"      ⚠️  IN FEED BUT NOT IN DATABASE: {len(in_feed_not_db)} event(s)")
                print(f"         This means iCal sync is NOT working properly!")
                for uid in list(in_feed_not_db)[:3]:
                    event = next((e for e in events if e['uid'] == uid), None)
                    if event:
                        print(f"         - {event['summary']} ({event['dtstart']})")
            else:
                print(f"      ✅ All feed events are in database")
            
            if in_db_not_feed:
                print(f"      ℹ️  IN DATABASE BUT NOT IN FEED: {len(in_db_not_feed)} reservation(s)")
                print(f"         (These were likely cancelled or are from XLS upload)")
            
        except Exception as e:
            print(f"   ❌ Comparison failed: {str(e)}")
    
    print()

# 4. Check specific dates with unread emails
print(f"\n{'='*80}")
print(f"STEP 4: CHECK SPECIFIC PROBLEMATIC DATES")
print(f"{'='*80}\n")

# The two dates with unread emails
problematic_dates = [
    date(2025, 11, 21),  # 6508851340, Friday, 21 November 2025
    date(2026, 6, 20),   # 5041560226, Saturday, 20 June 2026
]

for check_date in problematic_dates:
    print(f"📅 Checking {check_date.strftime('%A, %B %d, %Y')}")
    print(f"   {'─'*70}")
    
    # Check database
    db_reservations = Reservation.objects.filter(
        check_in_date=check_date,
        platform='booking',
        status='confirmed'
    ).select_related('room')
    
    print(f"   Database: {db_reservations.count()} reservation(s)")
    for res in db_reservations:
        enriched = "✅ Enriched" if res.guest else "❌ Unenriched"
        print(f"      - {res.room.name}: {res.guest_name} ({enriched})")
        print(f"        Booking ref: {res.booking_reference or '(empty)'}")
    
    # Check iCal feeds for this date
    print(f"   iCal Feeds:")
    for config in configs:
        if config.booking_active and config.booking_ical_url:
            try:
                ical_data = fetch_ical_feed(config.booking_ical_url, timeout=30)
                events = parse_ical(ical_data)
                
                matching_events = [e for e in events if e['dtstart'] == check_date and e['status'] == 'CONFIRMED']
                
                if matching_events:
                    print(f"      {config.room.name}: {len(matching_events)} event(s) in feed")
                    for event in matching_events:
                        print(f"         - {event['summary']}")
            except Exception as e:
                print(f"      {config.room.name}: ❌ Feed error: {str(e)}")
    
    print()

# 5. Check Celery task execution
print(f"\n{'='*80}")
print(f"STEP 5: CELERY TASK HEALTH CHECK")
print(f"{'='*80}\n")

print("To check if Celery is running and executing tasks:")
print("1. Run: heroku logs --tail --dyno=worker")
print("2. Look for: 'Starting iCal feed polling...'")
print("3. Should appear every 15 minutes")
print()
print("To check Beat (scheduler):")
print("1. Run: heroku logs --tail --dyno=beat")
print("2. Look for: 'Scheduler: Sending due task'")
print()
print("Manual sync test:")
print("1. Run: heroku run python -c \"from main.tasks import poll_all_ical_feeds; poll_all_ical_feeds()\"")
print()

# 6. Summary and recommendations
print(f"\n{'='*80}")
print(f"SUMMARY & RECOMMENDATIONS")
print(f"{'='*80}\n")

print("✅ If feeds are accessible and have events:")
print("   → iCal URLs are working")
print()
print("⚠️  If 'IN FEED BUT NOT IN DATABASE' shows events:")
print("   → iCal sync is FAILING - check Celery worker logs")
print("   → Run manual sync to test")
print()
print("ℹ️  If feeds are empty for problematic dates:")
print("   → Likely a payment/confirmation issue on Booking.com side")
print("   → Download XLS to verify if booking exists there")
print()
print("📋 Next steps:")
print("   1. Review diagnostics above")
print("   2. Check Celery logs (heroku logs --tail --dyno=worker)")
print("   3. Download XLS for November to verify booking 6508851340 exists")
print("   4. If in XLS but not in feed → Payment issue")
print("   5. If in feed but not in database → Sync issue")
print(f"{'='*80}\n")
