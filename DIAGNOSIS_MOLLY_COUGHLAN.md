# 🔍 MOLLY COUGHLAN CASE STUDY - Why Wrong Reservation Got Enriched

## XLS File Data:
- **6558646178** - Status: `cancelled_by_hotel` ❌
- **6623478393** - Status: `ok` ✅ (current booking)

## Expected Behavior:
XLS should enrich **6623478393** (confirmed) and ignore **6558646178** (cancelled)

## Actual Behavior (What Went Wrong):
Database shows **6558646178 is confirmed** and **6623478393 is cancelled** (backwards!)

## Root Cause Analysis:

### Scenario Timeline:
1. **Guest cancels booking 6558646178**
2. **iCal sync runs** → Removes 6558646178 from feed → Marks it as `cancelled` in DB
3. **New guest books 66234783393** for same room/dates
4. **iCal sync runs again** → Creates new reservation with **new UID** for 6623478393
5. **XLS upload happens**:
   - XLS has BOTH bookings (6558646178 cancelled + 6623478393 ok)
   - XLS parser skips cancelled (line 76: `if status == 'cancelled_by_guest'`)
   - **BUT** XLS shows `cancelled_by_hotel` not `cancelled_by_guest` - so it DOESN'T skip!
6. **XLS enriches BOTH reservations** (it shouldn't!)

## THE BUG:

```python
# Line 76 in xls_parser.py
if status == 'cancelled_by_guest':
    logger.info(f"Skipping cancelled booking {booking_ref} from XLS")
    return []
```

**Problem:** Only skips `cancelled_by_guest` but **NOT `cancelled_by_hotel`**!

Booking.com uses BOTH:
- `cancelled_by_guest` 
- `cancelled_by_hotel`
- `cancelled_by_booking_dot_com`

All should be skipped!

## THE FIX:

Change line 76 to:

```python
if 'cancelled' in status.lower():
    logger.info(f"Skipping cancelled booking {booking_ref} from XLS")
    return []
```

This will skip ALL cancellation types!

## Additional Issue:

Even if we fix this, there's still a timing problem:

1. iCal creates reservation with empty `booking_reference`
2. XLS tries to enrich by matching `room + dates`
3. If there are multiple reservations for same room/date (old cancelled + new confirmed), which one gets matched?

Currently Strategy 2 should match confirmed first (line 160: `status='confirmed'`)...

BUT if the old cancelled reservation already has a booking_ref from previous XLS enrichment, it will match in Strategy 1!

## Solution:

1. Fix cancellation check to catch ALL cancellation types
2. Ensure Strategy 1 always filters by `status='confirmed'` (already done ✅)
3. Maybe add additional check: if matching by dates, exclude any reservations that have a different booking_ref than what we're trying to enrich

---

**Fix needed in `xls_parser.py` line 76!**
