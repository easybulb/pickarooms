#!/usr/bin/env python
"""
Check PopularEvent alert status (local and production)
Shows which events are marked as sent vs not sent
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import PopularEvent
from django.utils import timezone
from datetime import date, timedelta

print("=" * 70)
print("POPULAR EVENT ALERT STATUS CHECK")
print("=" * 70)

# Overall stats
total = PopularEvent.objects.count()
sent = PopularEvent.objects.filter(sms_sent=True).count()
not_sent = PopularEvent.objects.filter(sms_sent=False).count()

print(f"\nOverall Statistics:")
print(f"   Total events: {total}")
print(f"   Marked as sent (sms_sent=True): {sent}")
print(f"   NOT marked as sent (sms_sent=False): {not_sent}")

# Check events that SHOULD trigger alerts (not yet sent)
priority_events = []
for event in PopularEvent.objects.filter(sms_sent=False, date__gte=date.today()):
    if event.should_send_sms:
        priority_events.append(event)

print(f"\nPriority Events NOT Yet Alerted:")
print(f"   Count: {len(priority_events)}")

if priority_events:
    print(f"\n   Top 10 Priority Events That Should Trigger Alerts:")
    for i, event in enumerate(priority_events[:10], 1):
        print(f"   {i}. {event.name[:50]}")
        print(f"      Date: {event.date}, Venue: {event.venue}")
        print(f"      Popularity: {event.popularity_score}/100, Sold Out: {event.is_sold_out}")

# Check recent events added
recent = PopularEvent.objects.filter(
    created_at__gte=timezone.now() - timedelta(hours=24)
).order_by('-created_at')

print(f"\nEvents Added in Last 24 Hours:")
print(f"   Count: {recent.count()}")

if recent.exists():
    print(f"\n   Latest 5 Events:")
    for i, event in enumerate(recent[:5], 1):
        alert_status = "WOULD ALERT" if event.should_send_sms else "No alert"
        sent_status = "SENT" if event.sms_sent else "NOT SENT"
        print(f"   {i}. {event.name[:40]}")
        print(f"      Created: {event.created_at.strftime('%Y-%m-%d %H:%M')}")
        print(f"      Status: {sent_status}, {alert_status}")
        print(f"      Popularity: {event.popularity_score}/100")

print("\n" + "=" * 70)