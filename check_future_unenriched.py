"""
Check for unenriched reservations far in the future (likely test/dummy data)
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.models import Reservation
from datetime import date, timedelta

print("=" * 70)
print("CHECKING FAR-FUTURE UNENRICHED RESERVATIONS")
print("=" * 70)

today = date.today()
six_months = today + timedelta(days=180)
one_year = today + timedelta(days=365)

# Get all unenriched reservations
unenriched = Reservation.objects.filter(guest__isnull=True).order_by('check_in_date')

print(f"\nTotal Unenriched: {unenriched.count()}")

# Breakdown by time period
next_month = unenriched.filter(check_in_date__lte=today + timedelta(days=30))
next_6_months = unenriched.filter(check_in_date__gt=today + timedelta(days=30), check_in_date__lte=six_months)
next_year = unenriched.filter(check_in_date__gt=six_months, check_in_date__lte=one_year)
beyond_year = unenriched.filter(check_in_date__gt=one_year)

print(f"\nBy Time Period:")
print(f"  - Next 30 days: {next_month.count()}")
print(f"  - 30 days - 6 months: {next_6_months.count()}")
print(f"  - 6 months - 1 year: {next_year.count()}")
print(f"  - Beyond 1 year (2026+): {beyond_year.count()}")

# Show sample of far-future reservations
if beyond_year.exists():
    print(f"\n" + "=" * 70)
    print("FAR-FUTURE RESERVATIONS (2026+) - Likely Test/Dummy Data")
    print("=" * 70)
    print(f"\nShowing first 20 of {beyond_year.count()}:\n")
    for res in beyond_year[:20]:
        print(f"  - {res.check_in_date} | {res.room.name if res.room else 'No Room'} | Ref: '{res.booking_reference}'")

    print(f"\n... and {max(0, beyond_year.count() - 20)} more")

    print("\n" + "=" * 70)
    print("RECOMMENDATION")
    print("=" * 70)
    print(f"""
These {beyond_year.count()} far-future reservations are likely:
1. Test/dummy data from early development
2. Old iCal syncs that were never cleaned up
3. Placeholder reservations

They will KEEP triggering 'Email not found' SMS alerts!

SOLUTION: Delete all reservations beyond {one_year}:
  Reservation.objects.filter(
      guest__isnull=True,
      check_in_date__gt='{one_year}'
  ).delete()
""")

print("=" * 70)
