#!/usr/bin/env python
"""
Diagnose the June 20, 2026 room issue
Check when "CLOSED - Not available" reservations were created
"""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import Reservation, EnrichmentLog
from datetime import date

print("=" * 80)
print("JUNE 20, 2026 RESERVATION ANALYSIS")
print("=" * 80)

# Get all reservations for June 20, 2026
june_20_reservations = Reservation.objects.filter(
    check_in_date=date(2026, 6, 20)
).order_by('room__name', 'created_at')

print(f"\nTotal reservations for June 20, 2026: {june_20_reservations.count()}\n")

for res in june_20_reservations:
    print(f"\n{'='*70}")
    print(f"RESERVATION ID: {res.id}")
    print(f"{'='*70}")
    print(f"Room: {res.room.name}")
    print(f"Booking Reference: '{res.booking_reference}'")
    print(f"Guest Name: {res.guest_name}")
    print(f"Status: {res.status}")
    print(f"Platform: {res.platform}")
    print(f"iCal UID: {res.ical_uid}")
    print(f"Created At: {res.created_at}")
    print(f"Updated At: {res.updated_at}")
    print(f"Has Guest Object: {res.guest is not None}")

    # Check enrichment logs for this reservation
    enrichment_logs = EnrichmentLog.objects.filter(
        reservation=res
    ).order_by('timestamp')

    print(f"\nEnrichment History ({enrichment_logs.count()} events):")
    for i, log in enumerate(enrichment_logs, 1):
        print(f"  {i}. {log.timestamp.strftime('%Y-%m-%d %H:%M:%S')} - {log.action}")
        print(f"     Method: {log.method}")
        if log.details:
            print(f"     Details: {log.details}")

print("\n" + "=" * 80)
print("ANALYSIS SUMMARY")
print("=" * 80)

# Group by characteristics
with_booking_ref = june_20_reservations.exclude(booking_reference__in=['', None])
without_booking_ref = june_20_reservations.filter(booking_reference__in=['', None])
closed_ones = june_20_reservations.filter(guest_name__icontains='CLOSED')

print(f"\nReservations WITH booking reference: {with_booking_ref.count()}")
for res in with_booking_ref:
    print(f"  - {res.booking_reference} | {res.guest_name} | {res.room.name} | {res.status}")

print(f"\nReservations WITHOUT booking reference: {without_booking_ref.count()}")
for res in without_booking_ref:
    print(f"  - {res.guest_name} | {res.room.name} | Created: {res.created_at}")

print(f"\n'CLOSED - Not available' reservations: {closed_ones.count()}")
for res in closed_ones:
    print(f"  - {res.room.name} | Created: {res.created_at} | iCal UID: {res.ical_uid[:50]}...")

# Check when these were created relative to XLS upload
from main.models import CSVEnrichmentLog
latest_xls = CSVEnrichmentLog.objects.order_by('-uploaded_at').first()
if latest_xls:
    print(f"\n{'='*70}")
    print(f"LATEST XLS UPLOAD:")
    print(f"  Time: {latest_xls.uploaded_at}")
    print(f"  File: {latest_xls.file_name}")

    # Check if CLOSED reservations were created AFTER XLS upload
    for res in closed_ones:
        if res.created_at > latest_xls.uploaded_at:
            print(f"\n  ⚠️ WARNING: {res.room.name} CLOSED reservation created AFTER XLS upload!")
            print(f"     XLS uploaded: {latest_xls.uploaded_at}")
            print(f"     Reservation created: {res.created_at}")
            print(f"     Time difference: {res.created_at - latest_xls.uploaded_at}")
        else:
            print(f"\n  ✓ {res.room.name} CLOSED reservation created BEFORE XLS upload")
            print(f"     XLS uploaded: {latest_xls.uploaded_at}")
            print(f"     Reservation created: {res.created_at}")

print("\n" + "=" * 80)