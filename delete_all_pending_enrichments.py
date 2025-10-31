"""
Delete ALL PendingEnrichment records to stop deprecated enrichment flow
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import PendingEnrichment

print("=" * 70)
print("DELETING ALL PENDINGENRICHMENT RECORDS")
print("=" * 70)

# Count before deletion
before_count = PendingEnrichment.objects.all().count()
print(f"\nPendingEnrichment records before deletion: {before_count}")

if before_count > 0:
    print("\n⚠️  These records are from the OLD deprecated email-driven enrichment flow.")
    print("Deleting them will stop the 'Multiple bookings detected' SMS alerts.")
    print()

    # Show what will be deleted
    print("Records to be deleted:")
    for p in PendingEnrichment.objects.all():
        print(f"  - {p.booking_reference} | Check-in: {p.check_in_date} | Status: {p.status}")

    print("\n" + "=" * 70)
    print("DELETING...")
    print("=" * 70)

    # Delete all
    deleted_count, _ = PendingEnrichment.objects.all().delete()

    print(f"\n✅ Successfully deleted {deleted_count} PendingEnrichment record(s)")
    print()
    print("The deprecated enrichment flow is now fully disabled.")
    print("You should NO LONGER receive 'Multiple bookings detected' SMS.")
    print()
else:
    print("\n✅ No PendingEnrichment records to delete")

print("=" * 70)
