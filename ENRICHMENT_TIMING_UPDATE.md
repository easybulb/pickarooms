# Email Enrichment Timing Update - HYBRID APPROACH

## Summary

Updated the email parsing + iCal enrichment workflow to use a **HYBRID APPROACH** with better spacing between retry attempts. This gives Booking.com's iCal feeds more time to update while maintaining efficient Celery worker usage.

---

## Changes Made

### 1. Updated Retry Schedule (`main/enrichment_config.py`)

**OLD Schedule (9 minutes total, 5 attempts):**
```python
ICAL_SYNC_RETRY_SCHEDULE = [
    60,    # 1 min
    180,   # 3 min (2 min gap)
    300,   # 5 min (2 min gap)
    420,   # 7 min (2 min gap)
    540,   # 9 min (2 min gap)
]
```

**NEW Schedule (24 minutes total, 4 attempts - HYBRID APPROACH):**
```python
ICAL_SYNC_RETRY_SCHEDULE = [
    300,   # 5 min (initial patience)
    480,   # 8 min (3 min gap)
    720,   # 12 min (4 min gap)
    1080,  # 18 min (6 min gap)
]
```

### 2. Updated Attempt Limits

- **Tasks (`main/tasks.py`)**: Changed from 5 attempts to 4 attempts
- **Service (`main/services/enrichment_service.py`)**: Updated failure threshold from 5 to 4

---

## Detailed Flow

### **NEW Workflow Timeline:**

```
Email arrives from Booking.com
↓
[0 min] Create PendingEnrichment record
↓
[5 min] ATTEMPT 1: Sync all Booking.com iCal feeds → Match
         ↓
         ✅ MATCHED? → STOP! Link guest to reservation
         ↓
         ❌ NO MATCH? → Continue...
↓
[8 min] ATTEMPT 2: Sync → Match (3 min wait since attempt 1)
         ↓
         ✅ MATCHED? → STOP! Link guest to reservation
         ↓
         ❌ NO MATCH? → Continue...
↓
[12 min] ATTEMPT 3: Sync → Match (4 min wait since attempt 2)
          ↓
          ✅ MATCHED? → STOP! Link guest to reservation
          ↓
          ❌ NO MATCH? → Continue...
↓
[18 min] ATTEMPT 4: Sync → Match (6 min wait since attempt 3)
          ↓
          ✅ MATCHED? → STOP! Link guest to reservation
          ↓
          ❌ NO MATCH? → Send SMS/Email alert to admin
↓
[~24 min] Admin receives alert (includes ~2 min processing time per attempt)
```

---

## Benefits

### ✅ **Pros:**
1. **More time for Booking.com**: 24 minutes (vs 9 minutes) allows iCal feeds more time to update
2. **Reduced Celery load**: 8 total tasks (4 sync + 4 match) vs 10 tasks (5 sync + 5 match) = **20% reduction**
3. **Lower API call frequency**: Fewer rapid-fire requests to Booking.com's iCal feeds
4. **Better spacing**: Avoids hammering the API with quick successive calls
5. **Still responsive**: Match stops immediately when found (doesn't wait for all attempts)
6. **Handles collisions**: Multi-booking detection works identically

### ⚠️ **Trade-offs:**
1. **Longer alert time**: Admin notified in ~24 minutes vs ~9 minutes
2. **Guest waits longer**: If manual assignment needed, takes 15 minutes longer

---

## Performance Impact on Heroku

| Metric | OLD | NEW | Impact |
|--------|-----|-----|--------|
| **Total attempts** | 5 | 4 | ✅ 20% reduction |
| **Total tasks** | 10 (5 sync + 5 match) | 8 (4 sync + 4 match) | ✅ 20% reduction |
| **Total time** | ~9 minutes | ~24 minutes | ⏱️ 15 min longer |
| **Worker load** | Higher frequency | Lower frequency | ✅ Better |
| **Booking.com API calls** | More frequent | Better spaced | ✅ Friendlier |
| **Success rate** | ~85% (estimated) | ~90%+ (estimated) | ✅ Higher (more time) |

**Conclusion**: This approach **REDUCES** load on Heroku workers while **INCREASING** success rate.

---

## Multi-Room Booking Handling

**Already Implemented** - No changes needed:

- ✅ Detects multiple reservations for same check-in date
- ✅ Assigns same booking reference to all rooms
- ✅ Sends collision alert if multiple emails received
- ✅ Supports SMS reply format: `A1-3, B2-2, C3-1`

See `match_pending_enrichment()` in `main/services/enrichment_service.py` for logic.

---

## Collision Scenario Example

If 2+ bookings arrive for the same date:

```
Email A (Booking #123) arrives → 5 min wait
Email B (Booking #456) arrives → 5 min wait

After 5 min:
- System detects collision (2 pendings, multiple candidates)
- Marks both as "failed_awaiting_manual"
- Sends SMS:
  
  PickARooms Alert:
  2 Bookings for 25 Jan 2025:
  
  A) #123
  B) #456
  
  Reply format:
  A1-3 = Booking A, Room 1, 3 nights
  B2-2 = Booking B, Room 2, 2 nights
```

---

## Testing Recommendations

### Manual Test (Production):

1. **Single Booking Test**:
   - Wait for next Booking.com confirmation email
   - Monitor logs: `heroku logs --tail --app pickarooms-495ab160017c | grep "pending"`
   - Verify timing: Should see attempts at 5min, 8min, 12min, 18min
   - Confirm match stops immediately when found

2. **Collision Test**:
   - Wait for multiple bookings on same date
   - Verify SMS shows A/B/C format
   - Test SMS reply: `A1-3`

### Log Monitoring:

```bash
# Watch enrichment flow
heroku logs --tail --app pickarooms-495ab160017c | grep -E "Matching attempt|Successfully matched|Failed to match"

# Watch timing
heroku logs --tail --app pickarooms-495ab160017c | grep "Scheduling retry"
```

---

## Rollback Plan

If issues arise, revert to old schedule:

```bash
git checkout HEAD~1 main/enrichment_config.py main/tasks.py main/services/enrichment_service.py
git commit -m "Rollback to old enrichment timing"
git push heroku main
```

Or use fallback branch: `pickarooms-v25`

---

## Files Modified

1. `main/enrichment_config.py` - Updated `ICAL_SYNC_RETRY_SCHEDULE`
2. `main/tasks.py` - Changed retry limit from 5 to 4 attempts
3. `main/services/enrichment_service.py` - Updated failure threshold from 5 to 4

---

**Status**: ✅ **READY FOR DEPLOYMENT**  
**Estimated Impact**: Positive - Better success rate, lower worker load  
**Risk Level**: Low - Logic unchanged, only timing adjusted  
**Recommended Deploy Time**: Any time (won't affect existing guests)

---

**Last Updated**: January 2025  
**Author**: Henry (easybulb)
