"""
Analyze XLS file to check for specific booking and compare with database
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

import pandas as pd
from datetime import datetime
from main.models import Reservation

# XLS file path
xls_path = r"C:\Users\easyb\Downloads\Check-in with contact details 2025-10-31 to 2026-11-30.xls"

print(f"\n{'='*80}")
print(f"XLS BOOKING ANALYSIS")
print(f"File: {xls_path}")
print(f"{'='*80}\n")

# Check if file exists
if not os.path.exists(xls_path):
    print(f"ERROR: File not found at {xls_path}")
    sys.exit(1)

try:
    # Read XLS file
    print("Reading XLS file...")
    df = pd.read_excel(xls_path)
    print(f"Loaded {len(df)} row(s) from XLS\n")
    
    # Show columns
    print(f"{'='*80}")
    print(f"XLS COLUMNS:")
    print(f"{'='*80}")
    for i, col in enumerate(df.columns, 1):
        print(f"   [{i}] {col}")
    print()
    
    # Look for booking reference column
    booking_ref_col = None
    for col in df.columns:
        if 'booking' in col.lower() or 'reservation' in col.lower() or 'confirmation' in col.lower():
            booking_ref_col = col
            break
    
    if booking_ref_col:
        print(f"Found booking reference column: '{booking_ref_col}'\n")
    else:
        print(f"Could not auto-detect booking reference column\n")
        print("Available columns:")
        for col in df.columns:
            print(f"   - {col}")
        print()
    
    # Target booking references - June 20, 2026
    target_refs = ['5041560226', '6682343841', '6668929481']
    
    print(f"{'='*80}")
    print(f"SEARCHING FOR TARGET BOOKINGS:")
    print(f"{'='*80}\n")
    
    for target_ref in target_refs:
        print(f"Searching for booking: {target_ref}")
        print(f"   {'-'*70}")
        
        # Search across all columns for the booking ref
        found = False
        for col in df.columns:
            if df[col].astype(str).str.contains(target_ref, na=False).any():
                found = True
                matching_rows = df[df[col].astype(str).str.contains(target_ref, na=False)]
                
                print(f"   FOUND in column: '{col}'")
                print(f"   Number of matches: {len(matching_rows)}")
                print()
                
                for idx, row in matching_rows.iterrows():
                    print(f"   BOOKING DETAILS:")
                    # Show all columns for this booking
                    for column in df.columns:
                        value = row[column]
                        if pd.notna(value):
                            print(f"      {column}: {value}")
                    print()
                
                # Check if this booking exists in database
                db_check = Reservation.objects.filter(
                    booking_reference=target_ref,
                    platform='booking'
                )
                
                if db_check.exists():
                    print(f"   EXISTS IN DATABASE:")
                    for res in db_check:
                        enriched = "Enriched" if res.guest else "Unenriched"
                        print(f"      - {res.room.name}: {res.guest_name} ({enriched})")
                        print(f"        Check-in: {res.check_in_date}, Check-out: {res.check_out_date}")
                else:
                    print(f"   NOT IN DATABASE")
                    print(f"      This booking should be added via XLS upload!")
                
                print()
                break
        
        if not found:
            print(f"   NOT FOUND in XLS file")
            print(f"      This confirms the booking is NOT confirmed on Booking.com")
            print(f"      Likely reason: Payment pending or cancelled")
            print()
    
    # Show all June 20, 2026 bookings from XLS
    print(f"\n{'='*80}")
    print(f"ALL BOOKINGS FOR JUNE 20, 2026 in XLS:")
    print(f"{'='*80}\n")

    # Try to find check-in date column
    checkin_col = None
    for col in df.columns:
        if 'check' in col.lower() and 'in' in col.lower():
            checkin_col = col
            break

    if checkin_col:
        print(f"Using check-in column: '{checkin_col}'\n")

        # Convert to datetime
        df[checkin_col] = pd.to_datetime(df[checkin_col], errors='coerce')

        # Filter for June 20, 2026
        target_date = pd.Timestamp('2026-06-20')
        june_20_bookings = df[df[checkin_col] == target_date]

        print(f"Found {len(june_20_bookings)} booking(s) for June 20, 2026:\n")

        for idx, row in june_20_bookings.iterrows():
            print(f"   {'-'*70}")
            for column in df.columns:
                value = row[column]
                if pd.notna(value):
                    print(f"   {column}: {value}")
            print()
    else:
        print(f"Could not find check-in date column")
        print(f"Available columns with 'date' or 'check':")
        for col in df.columns:
            if 'date' in col.lower() or 'check' in col.lower():
                print(f"   - {col}")

    # Summary
    print(f"\n{'='*80}")
    print(f"SUMMARY:")
    print(f"{'='*80}")
    print(f"Total rows in XLS: {len(df)}")
    print(f"Booking 5041560226 found: {'YES' if '5041560226' in str(df.values) else 'NO'}")
    print(f"Booking 6682343841 found: {'YES' if '6682343841' in str(df.values) else 'NO'}")
    print(f"Booking 6668929481 found: {'YES' if '6668929481' in str(df.values) else 'NO'}")
    print(f"{'='*80}\n")
    
except Exception as e:
    print(f"ERROR reading XLS file: {str(e)}")
    import traceback
    traceback.print_exc()
