"""
Quick Celery Health Check
Verify Celery worker and beat are running and executing tasks
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import RoomICalConfig
from django.utils import timezone
from datetime import timedelta

print(f"\n{'='*80}")
print(f"CELERY HEALTH CHECK")
print(f"{'='*80}\n")

# Check last sync times
configs = RoomICalConfig.objects.all().select_related('room')

if not configs.exists():
    print("⚠️  No iCal configurations found!")
else:
    print(f"Last Sync Status for Each Room:\n")
    
    now = timezone.now()
    
    for config in configs:
        print(f"🏠 {config.room.name}")
        print(f"   {'─'*70}")
        
        # Booking.com
        if config.booking_active:
            if config.booking_last_synced:
                time_ago = now - config.booking_last_synced
                minutes_ago = int(time_ago.total_seconds() / 60)
                
                if minutes_ago < 20:
                    status = f"✅ {minutes_ago} min ago (HEALTHY)"
                elif minutes_ago < 60:
                    status = f"⚠️  {minutes_ago} min ago (CHECK LOGS)"
                else:
                    hours_ago = int(minutes_ago / 60)
                    status = f"❌ {hours_ago} hours ago (SYNC FAILING!)"
                
                print(f"   📘 Booking.com: {status}")
                print(f"      Last synced: {config.booking_last_synced.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                print(f"      Status: {config.booking_last_sync_status}")
            else:
                print(f"   📘 Booking.com: ❌ NEVER SYNCED")
        
        # Airbnb
        if config.airbnb_active:
            if config.airbnb_last_synced:
                time_ago = now - config.airbnb_last_synced
                minutes_ago = int(time_ago.total_seconds() / 60)
                
                if minutes_ago < 20:
                    status = f"✅ {minutes_ago} min ago (HEALTHY)"
                elif minutes_ago < 60:
                    status = f"⚠️  {minutes_ago} min ago (CHECK LOGS)"
                else:
                    hours_ago = int(minutes_ago / 60)
                    status = f"❌ {hours_ago} hours ago (SYNC FAILING!)"
                
                print(f"   🏡 Airbnb: {status}")
                print(f"      Last synced: {config.airbnb_last_synced.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                print(f"      Status: {config.airbnb_last_sync_status}")
            else:
                print(f"   🏡 Airbnb: ❌ NEVER SYNCED")
        
        print()

print(f"\n{'='*80}")
print(f"INTERPRETATION:")
print(f"{'='*80}")
print("✅ < 20 min ago  → Celery is working perfectly (syncs every 15 min)")
print("⚠️  20-60 min ago → Possible issue, check logs")
print("❌ > 60 min ago  → Celery worker or beat is NOT running!")
print()
print("If all show ❌:")
print("   1. Check: heroku ps")
print("   2. Restart: heroku ps:restart worker")
print("   3. Restart: heroku ps:restart beat")
print()
print("If sync status shows errors:")
print("   1. Check logs: heroku logs --tail --dyno=worker")
print("   2. Look for iCal fetch errors or parsing errors")
print(f"{'='*80}\n")
