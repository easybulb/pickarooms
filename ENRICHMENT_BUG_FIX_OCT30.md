# Enrichment Bug Fix - October 30, 2025

## Critical Issue: Reservations Created Without Enrichment

### Problem Reported
User reported that reservations were being created but enrichment was not happening. This was the **3rd occurrence** of this issue and started happening after the refactoring work on October 29, 2025.

---

## Root Cause Analysis

### The Bug
The enrichment workflow in `main/tasks.py` was using **incorrect logic** to determine if a reservation was already enriched:

**OLD (BROKEN) LOGIC:**
```python
# Skip if already enriched
if reservation.booking_reference and len(reservation.booking_reference) >= 5:
    logger.info(f"Reservation {reservation_id} already enriched, skipping workflow")
    return "Already enriched"
```

**Problem:** This checks if a `booking_reference` exists, but a reservation can have a booking_ref **WITHOUT** having a Guest object (incomplete enrichment).

### How the Bug Occurred

1. **iCal feeds contain booking references** in the SUMMARY field (e.g., "Booking 5041581696 - Room 1")
2. `ical_service.py` extracts booking refs using regex: `extract_booking_reference(event['summary'])`
3. When creating a new reservation, iCal sets: `booking_reference=booking_ref or ''`
4. Enrichment workflow is triggered: `trigger_enrichment_workflow.delay(reservation.id)`
5. Enrichment workflow checks: "Does booking_reference exist?"
6. Answer: **YES** → Skips enrichment entirely
7. Result: Reservation has booking_ref but **NO Guest object, NO PINs, NO check-in data**

### Investigation Results

Investigation script (`investigate_ical_booking_refs.py`) revealed:

- **56% of iCal reservations** have booking_ref extracted from SUMMARY field
- **28 reservations** in last 7 days were affected (booking_ref but no Guest)
- Two scenarios identified:
  - **Before Oct 28**: Enrichment not triggered at all (17 reservations)
  - **After Oct 28**: Enrichment triggered but immediately skipped (11 reservations)

**Example Affected Reservations:**
- 5041581696 - Room 1, Check-in: Nov 15, 2025
- 6717790453 - Room 2, Check-in: Oct 23, 2026
- 6588202211 - Room 4, Check-in: Nov 21, 2025
- 6782502387 - Maja Murawka (real guest name visible)
- 5073085021 - Hyunsun Kim

---

## The Fix

### NEW (CORRECT) LOGIC:
```python
# Skip if already enriched (has a Guest object)
if reservation.guest is not None:
    logger.info(f"Reservation {reservation_id} already enriched (has guest), skipping workflow")
    return "Already enriched"
```

**Why This Is Correct:**
- ✅ Guest object = TRUE enrichment indicator (PINs, check-in data, everything created)
- ✅ Ensures email search runs until Guest is created
- ✅ Handles edge cases where booking_ref exists but Guest doesn't
- ✅ More defensive - uses correct enrichment indicator

### Code Changes

**File:** `main/tasks.py`

**Location 1:** `trigger_enrichment_workflow()` (Line 377-385)
```python
# Before
reservation = Reservation.objects.select_related('room').get(id=reservation_id)
if reservation.booking_reference and len(reservation.booking_reference) >= 5:
    return "Already enriched"

# After
reservation = Reservation.objects.select_related('room', 'guest').get(id=reservation_id)
if reservation.guest is not None:
    return "Already enriched"
```

**Location 2:** `search_email_for_reservation()` (Line 431-439)
```python
# Before
reservation = Reservation.objects.get(id=reservation_id)
if reservation.booking_reference and len(reservation.booking_reference) >= 5:
    return "Already enriched"

# After
reservation = Reservation.objects.select_related('guest').get(id=reservation_id)
if reservation.guest is not None:
    return "Already enriched"
```

**Additional Optimization:**
- Added `select_related('guest')` to reduce database queries

---

## Deployment

### Git Commit
```bash
git commit -m "CRITICAL FIX: Check guest object instead of booking_ref for enrichment status"
```

**Commit Hash:** `0c98c42`

### Heroku Deployment
```bash
git push heroku main
heroku restart --app pickarooms
```

**Deployed Version:** v149
**Deployment Time:** October 30, 2025, 20:32 UTC

**Dynos Restarted:**
- ✅ web.1
- ✅ worker.1 (critical - loads new enrichment logic)
- ✅ beat.1

---

## Impact & Results

### What This Fixes

**For NEW bookings** (after v149 deployment):
1. ✅ iCal creates reservation (with or without booking_ref from SUMMARY)
2. ✅ Enrichment workflow triggers
3. ✅ Checks: "Does Guest object exist?" (not booking_ref)
4. ✅ If NO guest → Email search runs → Guest created → Full enrichment
5. ✅ Reservations fully enriched with PINs, check-in data, everything

### What It Doesn't Fix

**The 28 stuck reservations** from before the fix still need manual intervention:
- They have booking refs
- They have real guest names
- But NO Guest objects, PINs, or check-in ability

**Options to fix stuck reservations:**
1. Upload XLS file from Booking.com to bulk-enrich them
2. Manually trigger enrichment for each one
3. Wait for guests to check in and handle manually via SMS

---

## Technical Details

### Why iCal Feeds Contain Booking References

Booking.com iCal feeds include booking references in the **SUMMARY** field:

**Example SUMMARY Field:**
```
Booking.com Reservation 5041581696
```

**Extraction Logic:** `main/services/ical_service.py:44-77`
```python
def extract_booking_reference(text):
    """
    Extract booking reference from text using regex

    Supports:
    - Booking.com: 10-digit numeric codes (e.g., 5282674483)
    - Airbnb: 10-character alphanumeric codes (e.g., HMKHKPPZTQ)
    """
    # Match exactly 10 consecutive digits (Booking.com format)
    match = re.search(r'\b(\d{10})\b', text)
    if match:
        return match.group(1)
```

**Usage:** `main/services/ical_service.py:307`
```python
reservation = Reservation.objects.create(
    ical_uid=uid,
    room=config.room,
    platform=platform,
    guest_name=event['summary'],
    booking_reference=booking_ref or '',  # ← Sets booking_ref if found
    check_in_date=event['dtstart'],
    check_out_date=event['dtend'],
    status=event_status,
    raw_ical_data=event['raw']
)
```

### Enrichment Workflow Flow

**Correct Flow (After Fix):**
```
iCal creates reservation
    ↓
booking_reference = "5041581696" (from SUMMARY)
guest = None
    ↓
trigger_enrichment_workflow()
    ↓
Check: reservation.guest is not None?
    ↓
NO → Continue to email search
    ↓
search_email_for_reservation()
    ↓
Find email, extract booking ref
    ↓
Create Guest object with PINs
    ↓
✅ FULLY ENRICHED
```

**Broken Flow (Before Fix):**
```
iCal creates reservation
    ↓
booking_reference = "5041581696" (from SUMMARY)
guest = None
    ↓
trigger_enrichment_workflow()
    ↓
Check: reservation.booking_reference exists?
    ↓
YES → Skip enrichment! ❌
    ↓
Result: booking_ref exists, guest = None
    ↓
❌ PARTIAL ENRICHMENT (BUG!)
```

---

## Related Files

### Modified Files
- `main/tasks.py` - Fixed enrichment check logic (2 locations)

### Investigation Scripts
- `investigate_ical_booking_refs.py` - Diagnostic script to confirm bug
- `check_specific_booking_ref.py` - Check individual booking reference

### Related Code
- `main/services/ical_service.py` - iCal parsing and booking ref extraction
- `main/models.py` - Reservation and Guest models
- `main/enrichment_config.py` - Enrichment configuration

---

## Lessons Learned

1. **Use the correct enrichment indicator**: Guest object existence, not booking_ref
2. **iCal feeds can contain partial data**: Booking refs without full guest details
3. **Enrichment = Guest object creation**: Everything else is just metadata
4. **Always restart worker/beat dynos** after deploying Celery task changes

---

## Statistics from Investigation

**Last 7 Days (Oct 24-30, 2025):**
- Total iCal reservations: 50
- Reservations with booking_ref: 28 (56%)
- Reservations without booking_ref: 22 (44%)
- Affected by bug: 28 (all unenriched)

**Enrichment Trigger Status:**
- Enrichment triggered (Oct 28-30): 11 reservations
- Enrichment NOT triggered (Oct 24): 17 reservations

---

## Prevention

This bug is now **permanently fixed** by using the correct enrichment indicator (`guest is not None` instead of `booking_reference` existence).

**Future-proofing:**
- The fix is backward compatible
- Works regardless of whether iCal provides booking refs or not
- More defensive programming approach
- Aligns with the actual definition of "enriched" (having a Guest object)

---

**Document Created:** October 30, 2025
**Fix Version:** v149
**Status:** ✅ RESOLVED

---
