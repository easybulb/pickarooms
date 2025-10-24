# ✅ EMAIL ENRICHMENT - FULLY IMPLEMENTED & ACTIVE

## ❌ MY MISTAKE - CORRECTION

I incorrectly stated email enrichment was "not active yet". **IT IS FULLY ACTIVE!**

## 🔄 COMPLETE EMAIL ENRICHMENT WORKFLOW

### 1. Email Polling (Every 5 minutes)
**Task:** `poll_booking_com_emails` (main/tasks.py, line 266)

**What it does:**
```
1. Connects to Gmail via IMAP
2. Searches for unread Booking.com emails
3. Parses subject line to extract:
   - booking_reference (10 digits)
   - check_in_date
   - email_type (new/modification/cancellation)
4. Creates PendingEnrichment record
5. Marks email as read
6. Triggers iCal sync workflow
```

**Example Email Subject:**
```
"Booking.com - New booking! (6623478393, Friday, 24 October 2025)"
```

**Extracted Data:**
- `booking_reference`: 6623478393
- `check_in_date`: 2025-10-24
- `email_type`: new

### 2. iCal Sync Triggered (T+60s)
**Task:** `sync_booking_com_rooms_for_enrichment` (main/tasks.py, line 352)

**What it does:**
```
1. Syncs ALL Booking.com room iCal feeds
2. Creates/updates Reservation records
3. Reservation gets created with:
   - booking_reference: '' (empty)
   - guest_name: 'CLOSED - Not available'
   - status: 'confirmed'
   - ical_uid: unique ID from iCal
```

### 3. Matching Attempt (T+90s)
**Task:** `match_pending_to_reservation` (main/tasks.py, line 379)

**What it does:**
```
1. Finds unenriched Reservations for same check_in_date
2. Matches PendingEnrichment → Reservation
3. Updates Reservation.booking_reference
4. Marks PendingEnrichment as 'matched'
```

**Matching Logic (main/services/enrichment_service.py):**
```python
candidates = Reservation.objects.filter(
    check_in_date=pending.check_in_date,
    platform='booking',
    booking_reference__isnull=True,  # Unenriched
    status='confirmed'
)
```

### 4. Retry Logic
- **Attempt 1**: T+60s
- **Attempt 2**: T+3m
- **Attempt 3**: T+5m
- **Attempt 4**: T+10m
- **Attempt 5**: T+15m (final)

If all 5 attempts fail → SMS/Email alert to admin

## 📊 ENRICHMENT SCENARIOS

### Scenario 1: Single Room Booking ✅
```
Email: booking_reference=6623478393, check_in=2025-10-24
iCal: 1 reservation for 2025-10-24 (no booking_ref)
Result: Match → Update reservation.booking_reference=6623478393
```

### Scenario 2: Multi-Room Booking ✅
```
Email: booking_reference=5555555555, check_in=2025-10-25
iCal: 2 reservations for 2025-10-25 (Room 1 + Room 2, no booking_ref)
Result: Match → Update BOTH reservations with same booking_reference
```

### Scenario 3: Collision (Multiple Bookings Same Date) ⚠️
```
Email 1: booking_reference=1111111111, check_in=2025-10-26
Email 2: booking_reference=2222222222, check_in=2025-10-26
iCal: 2 reservations for 2025-10-26
Result: Cannot auto-match → Send admin alert for manual assignment
```

### Scenario 4: No Match Yet (iCal Delayed) 🔄
```
Email: booking_reference=3333333333, check_in=2025-10-27
iCal: 0 reservations for 2025-10-27 (not synced yet)
Result: Retry up to 5 times over 15 minutes
```

## 🚨 CRITICAL ISSUE DISCOVERED

### The Problem with Status Field

**In enrichment_service.py (line 54):**
```python
candidates = Reservation.objects.filter(
    check_in_date=pending.check_in_date,
    platform='booking',
    booking_reference__isnull=True,
    status='confirmed'  # ← HARDCODED!
)
```

**This is CORRECT!** But we need to verify it matches what iCal creates.

**In ical_service.py (line 235):**
```python
event_status = 'cancelled' if event['status'] == 'CANCELLED' else 'confirmed'
```

✅ **GOOD** - iCal creates reservations with `status='confirmed'`

**But what about the XLS issue we fixed?**

In xls_parser.py, we fixed:
```python
if 'cancelled' in status.lower():  # Skips ALL cancellations
    return []
```

This means XLS will NEVER create cancelled reservations.

## ⚠️ POTENTIAL ISSUE: Email + iCal + XLS Conflict

### The Molly Coughlan Case Revisited

**Timeline:**
1. **T+0**: Guest cancels 6558646178 (cancelled_by_hotel)
2. **T+1**: Email arrives: "Cancelled booking! (6558646178, Friday, 24 October 2025)"
3. **T+2**: `poll_booking_com_emails` creates PendingEnrichment (email_type='cancellation')
4. **T+3**: iCal sync runs → Removes 6558646178 from feed → Marks as 'cancelled'
5. **T+4**: New guest books 6623478393 for same room/date
6. **T+5**: Email arrives: "New booking! (6623478393, Friday, 24 October 2025)"
7. **T+6**: iCal sync runs → Creates reservation for 6623478393 (status='confirmed')
8. **T+7**: Email enrichment matches 6623478393 → Sets booking_reference ✅
9. **T+8**: XLS upload with BOTH bookings:
   - 6558646178 (cancelled_by_hotel) → SKIPPED ✅
   - 6623478393 (ok) → Enriches/updates ✅

**VERDICT:** ✅ This should work correctly now!

## 🔍 CHECKING IF EMAIL ENRICHMENT IS WORKING

### On Production (Heroku):
```bash
heroku run python manage.py shell -c "from main.models import PendingEnrichment; print(PendingEnrichment.objects.count())"
```

### Check Recent Enrichments:
```bash
heroku run python manage.py shell -c "from main.models import EnrichmentLog; logs = EnrichmentLog.objects.filter(action__contains='auto_matched').order_by('-timestamp')[:10]; [print(f'{log.booking_reference} - {log.action}') for log in logs]"
```

### Check Email Polling Logs:
```bash
heroku logs --tail | grep "poll_booking_com_emails"
```

## ✅ DATA PRESERVATION WITH EMAIL ENRICHMENT

### What Email Enrichment Updates:
- ✅ `Reservation.booking_reference` (from empty to actual ref)

### What Email Enrichment NEVER Touches:
- 🔒 `Reservation.ical_uid`
- 🔒 `Reservation.status`
- 🔒 `Reservation.guest` (OneToOneField)
- 🔒 `Reservation.check_in_date`
- 🔒 `Reservation.check_out_date`
- 🔒 `Reservation.guest_name`

### After Email Enrichment, iCal Sync Preserves:
- 🔒 `booking_reference` (lines 283-297 in ical_service.py)
- 🔒 `guest` link

### After Email Enrichment, XLS Upload Preserves:
- 🔒 `ical_uid`
- 🔒 `guest` link

## 🎯 COMPLETE DATA FLOW (ALL 3 SYSTEMS)

```
1. Guest books on Booking.com
   ↓
2. Email arrives → PendingEnrichment created
   ↓
3. iCal sync (15 min) → Reservation created (booking_ref='')
   ↓
4. Email enrichment matches → Sets booking_reference ✅
   ↓
5. iCal syncs again → Preserves booking_reference ✅
   ↓
6. XLS upload → Enriches further (guest_name, etc.) ✅
   ↓
7. iCal syncs again → Preserves everything ✅
```

## 📋 RECOMMENDATION: CHECK STATUS CONSISTENCY

We need to verify that email enrichment handles cancellation emails correctly!

**In main/services/email_parser.py:**
```python
EMAIL_TYPE_CHOICES = [
    ('new', 'New Booking'),
    ('modification', 'Modification'),
    ('cancellation', 'Cancellation'),
]
```

**Question:** What happens when a cancellation email arrives?

**In main/tasks.py, poll_booking_com_emails:**
- Creates PendingEnrichment with `email_type='cancellation'`
- BUT: enrichment_service.py doesn't check email_type!
- It only looks for `status='confirmed'` reservations

**This means:**
- Cancellation emails create PendingEnrichment
- But they'll never match (no confirmed reservation exists)
- After 5 retries → Admin alert sent
- Admin manually dismisses

**RECOMMENDATION:**
Skip creating PendingEnrichment for cancellation emails entirely!
