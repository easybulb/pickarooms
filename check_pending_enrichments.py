"""
Check for any PendingEnrichment records that might be causing collision alerts
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import PendingEnrichment
from datetime import date

print("=" * 70)
print("CHECKING PENDINGENRICHMENT TABLE")
print("=" * 70)

# Get all pending enrichments
all_pending = PendingEnrichment.objects.all()
print(f"\nTotal PendingEnrichment records: {all_pending.count()}")

if all_pending.count() > 0:
    print("\n🚨 FOUND PENDING ENRICHMENT RECORDS\n")

    # Check for Nov 3rd specifically (the date causing issues)
    nov_3_pending = PendingEnrichment.objects.filter(check_in_date=date(2025, 11, 3))

    if nov_3_pending.exists():
        print(f"⚠️  Nov 3rd 2025 records: {nov_3_pending.count()}")
        for p in nov_3_pending:
            print(f"  - Booking Ref: {p.booking_reference}")
            print(f"    Status: {p.status}")
            print(f"    Created: {p.email_received_at}")
            print(f"    Room: {p.room_matched}")
            print()

    # Show recent pending enrichments
    recent = all_pending.order_by('-email_received_at')[:10]
    print("\nMost recent 10 pending enrichments:")
    for p in recent:
        print(f"  - {p.booking_reference} | Check-in: {p.check_in_date} | Status: {p.status}")

    print("\n" + "=" * 70)
    print("PROBLEM IDENTIFIED")
    print("=" * 70)
    print("The PendingEnrichment table contains OLD email-driven enrichment records.")
    print("This table is part of the DEPRECATED enrichment flow.")
    print()
    print("The system is likely running collision detection on these old records,")
    print("which is why you're getting 'Multiple bookings detected' SMS.")
    print()
    print("SOLUTION: Delete all PendingEnrichment records:")
    print("  PendingEnrichment.objects.all().delete()")
    print()
else:
    print("\n✅ PendingEnrichment table is empty")
    print("\nIf you're still getting collision SMS, check:")
    print("  1. Models.py for any signal that creates PendingEnrichment")
    print("  2. Webhooks or external triggers")
    print()

print("=" * 70)
