"""
NUCLEAR OPTION: Clear ALL reservation and enrichment data
This will delete:
- All Reservations (iCal synced data)
- All Guests (enriched data)
- All CSVEnrichmentLog (XLS upload logs)
- All EnrichmentLog (enrichment history)
- All PendingEnrichment (email enrichment queue)

Run with: heroku run python clear_all_reservation_data.py -a pickarooms
"""

import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import (
    Reservation, 
    Guest, 
    CSVEnrichmentLog, 
    EnrichmentLog, 
    PendingEnrichment
)

print("=" * 80)
print("🚨 NUCLEAR OPTION: CLEAR ALL RESERVATION DATA 🚨")
print("=" * 80)

# Count current data
reservation_count = Reservation.objects.count()
guest_count = Guest.objects.count()
csv_log_count = CSVEnrichmentLog.objects.count()
enrichment_log_count = EnrichmentLog.objects.count()
pending_count = PendingEnrichment.objects.count()

print("\n📊 CURRENT DATA COUNTS:")
print(f"  - Reservations: {reservation_count}")
print(f"  - Guests: {guest_count}")
print(f"  - CSV Upload Logs: {csv_log_count}")
print(f"  - Enrichment Logs: {enrichment_log_count}")
print(f"  - Pending Enrichments: {pending_count}")

if reservation_count == 0 and guest_count == 0:
    print("\n✅ Database is already clean!")
    print("=" * 80)
    exit(0)

print("\n" + "=" * 80)
print("⚠️  WARNING: THIS WILL DELETE ALL DATA!")
print("=" * 80)
print("\nThis action will:")
print("  1. Delete ALL reservations (iCal synced data)")
print("  2. Delete ALL guests (with their PINs)")
print("  3. Delete ALL XLS upload logs")
print("  4. Delete ALL enrichment history")
print("  5. Delete ALL pending enrichments")
print("\nAfter this:")
print("  ✅ iCal will re-sync within 15 minutes (next scheduled poll)")
print("  ✅ You can then upload XLS to enrich the data")
print("  ✅ No data conflicts!")

print("\n" + "=" * 80)
print("Type 'DELETE EVERYTHING' to confirm (case-sensitive):")
print("Or press Ctrl+C to cancel")
print("=" * 80)

confirmation = input("\nConfirmation: ").strip()

if confirmation != "DELETE EVERYTHING":
    print("\n❌ Cancelled. No data was deleted.")
    print("=" * 80)
    exit(0)

print("\n🔥 STARTING DELETION...")
print("-" * 80)

# Delete in correct order (respecting foreign keys)
print("\n1. Deleting Guests (and their PINs)...")
deleted_guests = Guest.objects.all().delete()
print(f"   ✅ Deleted {deleted_guests[0]} guest(s)")

print("\n2. Deleting Reservations...")
deleted_reservations = Reservation.objects.all().delete()
print(f"   ✅ Deleted {deleted_reservations[0]} reservation(s)")

print("\n3. Deleting CSV Upload Logs...")
deleted_csv_logs = CSVEnrichmentLog.objects.all().delete()
print(f"   ✅ Deleted {deleted_csv_logs[0]} CSV log(s)")

print("\n4. Deleting Enrichment Logs...")
deleted_enrichment_logs = EnrichmentLog.objects.all().delete()
print(f"   ✅ Deleted {deleted_enrichment_logs[0]} enrichment log(s)")

print("\n5. Deleting Pending Enrichments...")
deleted_pending = PendingEnrichment.objects.all().delete()
print(f"   ✅ Deleted {deleted_pending[0]} pending enrichment(s)")

print("\n" + "=" * 80)
print("✅ SUCCESS! ALL DATA CLEARED")
print("=" * 80)

print("\n📋 NEXT STEPS:")
print("  1. Wait 15 minutes for iCal to sync (or trigger manually)")
print("  2. Check /admin-page/ to see reservations appear")
print("  3. Upload XLS file to enrich with booking references")
print("  4. Guests can then check in!")

print("\n🔄 To trigger iCal sync immediately:")
print("   - Visit: https://pickarooms.com/admin-page/")
print("   - Or wait for next scheduled poll (every 15 min)")

print("\n" + "=" * 80)
