# 🔄 DATA PRESERVATION ANALYSIS - iCal vs XLS vs Email Enrichment

## Current Data Flow

```
1. iCal Sync (Every 15 min)
   ↓
   Creates: Reservation (booking_reference='', guest_name='CLOSED - Not available', status='confirmed')
   
2. Email Parser (Every 5 min) [NOT YET IMPLEMENTED IN YOUR SYSTEM]
   ↓
   Creates: PendingEnrichment (booking_reference='6623478393', check_in_date, status='pending')
   ↓
   Matches to Reservation by: room + dates
   ↓
   Links Guest to Reservation
   
3. XLS Upload (Manual)
   ↓
   Matches Reservation by:
   - Strategy 1: booking_reference + room + check_in (if booking_ref exists)
   - Strategy 2: room + check_in + check_out (if booking_ref empty)
   ↓
   Updates: booking_reference, guest_name
   PRESERVES: ical_uid, status, guest (if linked)
```

## 🔍 KEY FINDINGS

### 1. iCal Sync Logic (main/services/ical_service.py, lines 267-300)

**What iCal UPDATES on existing reservations:**
- ✅ `check_in_date`
- ✅ `check_out_date`
- ✅ `status` (confirmed/cancelled)
- ✅ `raw_ical_data`

**What iCal PRESERVES (doesn't overwrite):**
- ✅ `booking_reference` (lines 283-297)
- ✅ `guest_name` (only updates if booking_ref changes)
- ✅ `guest` (OneToOneField - NOT touched by iCal!)

**Code Analysis (lines 283-297):**
```python
# Preserve XLS-enriched booking_reference (5+ chars)
# Only update if iCal has a valid booking_ref AND reservation doesn't have one yet
if booking_ref and len(booking_ref) >= 5:
    # iCal has valid booking ref - update it
    reservation.booking_reference = booking_ref
    reservation.guest_name = event['summary']
elif not reservation.booking_reference or len(reservation.booking_reference) < 5:
    # No enrichment yet, update guest_name but keep booking_ref as-is
    reservation.guest_name = event['summary']
else:
    # Preserve XLS-enriched data (booking_reference >= 5 chars)
    logger.info(f"Preserved XLS-enriched booking_ref: {reservation.booking_reference}")
```

**VERDICT:** ✅ iCal PRESERVES XLS enrichments!

---

### 2. XLS Upload Logic (main/services/xls_parser.py, lines 130-176)

**What XLS UPDATES on existing reservations:**
- ✅ `booking_reference`
- ✅ `guest_name`
- ✅ `check_out_date`
- ✅ `status` (if cancelled in XLS)

**What XLS PRESERVES:**
- ✅ `ical_uid` (NOT touched!)
- ✅ `guest` (OneToOneField - NOT touched!)
- ✅ `check_in_date` (NOT updated)
- ✅ `platform` (NOT updated)

**Code Analysis (lines 169-176):**
```python
if existing:
    # Update existing (enriching iCal-synced or updating XLS-created)
    existing.booking_reference = booking_ref  # Set/update booking ref
    existing.guest_name = guest_name
    existing.check_out_date = check_out
    if status == 'cancelled_by_guest':
        existing.status = 'cancelled'
    existing.save()
```

**VERDICT:** ✅ XLS PRESERVES iCal UIDs and Guest links!

---

### 3. Email Enrichment Logic (NOT YET ACTIVE)

**Status:** Email parsing exists but enrichment workflow NOT implemented yet.

**Files Found:**
- ✅ `main/services/email_parser.py` (parses email subjects)
- ✅ `main/tasks.py` (has `poll_booking_com_emails` task)
- ✅ `PendingEnrichment` model (tracks email→iCal matching)

**Missing:**
- ❌ No code to create `Guest` from `PendingEnrichment`
- ❌ No code to link `Guest` to `Reservation.guest`

**Email enrichment would need to:**
1. Create `Guest` object with full details (phone, email, etc.)
2. Link `Guest` to `Reservation` via `Reservation.guest = guest`
3. Mark `PendingEnrichment.status = 'matched'`

---

## ✅ DATA PRESERVATION RULES (CURRENT IMPLEMENTATION)

### When iCal Syncs Every 15 Minutes:

| Field | Behavior | Safe? |
|-------|----------|-------|
| `check_in_date` | ✅ Updated | ✅ Yes (dates should be authoritative from iCal) |
| `check_out_date` | ✅ Updated | ✅ Yes |
| `status` | ✅ Updated | ✅ Yes (iCal knows cancellations) |
| `booking_reference` | 🔒 Preserved (if already enriched) | ✅ Yes |
| `guest_name` | 🔒 Preserved (if booking_ref exists) | ✅ Yes |
| `guest` | 🔒 Never touched | ✅ Yes |
| `ical_uid` | 🔒 Never changed | ✅ Yes |

### When XLS Uploads (Manual):

| Field | Behavior | Safe? |
|-------|----------|-------|
| `booking_reference` | ✅ Updated/Set | ✅ Yes (this is enrichment) |
| `guest_name` | ✅ Updated | ✅ Yes |
| `check_out_date` | ✅ Updated | ⚠️ Could conflict with iCal |
| `status` | ✅ Updated (if cancelled) | ⚠️ Could conflict with iCal |
| `guest` | 🔒 Never touched | ✅ Yes |
| `ical_uid` | 🔒 Never touched | ✅ Yes |
| `check_in_date` | 🔒 Never updated | ✅ Yes |

### When Email Enrichment Happens (FUTURE):

| Action | Effect | Safe? |
|--------|--------|-------|
| Create `Guest` | Links to `Reservation.guest` | ✅ Yes |
| iCal syncs after | Preserves `Guest` link | ✅ Yes |
| XLS uploads after | Preserves `Guest` link | ✅ Yes |

---

## 🚨 POTENTIAL ISSUES

### Issue 1: Multiple XLS Uploads
**Scenario:**
1. XLS upload #1: Sets `booking_reference='6623478393'`, `check_out_date='2025-10-25'`
2. Guest modifies booking to extend stay
3. iCal sync: Updates `check_out_date='2025-10-26'` ✅
4. XLS upload #2 (old data): Resets `check_out_date='2025-10-25'` ❌

**Solution:**
- ⚠️ Always upload latest XLS from Booking.com
- Or: Add logic to only update fields if XLS is newer than last iCal sync

### Issue 2: Cancelled Bookings in XLS
**Status:** ✅ FIXED (lines 76-79 in xls_parser.py)
```python
# Skip ALL cancelled statuses
if 'cancelled' in status.lower():
    logger.info(f"Skipping cancelled booking {booking_ref} from XLS (status: {status})")
    return []
```

### Issue 3: Room Changes Mid-Stay
**Scenario:**
1. Booking originally for Room 1
2. Guest requests room change to Room 2
3. XLS shows Room 2, iCal still shows Room 1

**Current Handling:**
- ⚠️ XLS logs a warning (lines 93-119)
- ❌ Does NOT automatically delete old reservation
- ❌ Admin must manually clean up

---

## 📊 ENRICHMENT SOURCE TRACKING

### How to Know What Enriched a Reservation:

**Method 1: Check `EnrichmentLog`**
```python
EnrichmentLog.objects.filter(booking_reference='6623478393')
# Shows: xls_enriched_single, email_parsed, etc.
```

**Method 2: Check `CSVEnrichmentLog`**
```python
CSVEnrichmentLog.objects.latest('uploaded_at')
# Shows last XLS upload details
```

**Method 3: Check `PendingEnrichment`**
```python
PendingEnrichment.objects.filter(booking_reference='6623478393')
# Shows: enriched_via='email_ical_auto' or 'csv_upload'
```

---

## ✅ RECOMMENDATIONS

### 1. Add Enrichment Source to Reservation Model
```python
class Reservation(models.Model):
    # Add this field:
    enriched_by = models.CharField(
        max_length=20, 
        blank=True,
        choices=[
            ('ical_only', 'iCal Only'),
            ('xls', 'XLS Upload'),
            ('email', 'Email Parsing'),
            ('manual', 'Manual Admin'),
        ]
    )
    enriched_at = models.DateTimeField(null=True, blank=True)
```

### 2. Add Last Modified Tracking
```python
class Reservation(models.Model):
    # Add these:
    last_ical_sync = models.DateTimeField(null=True, blank=True)
    last_xls_update = models.DateTimeField(null=True, blank=True)
```

### 3. Prevent Stale XLS Overrides
```python
# In xls_parser.py, before updating:
if existing.last_ical_sync and existing.last_ical_sync > xls_upload_time:
    logger.warning(f"Skipping XLS update - iCal sync is newer")
    continue
```

---

## 🎯 SUMMARY

| Enrichment Type | Preserves iCal Data? | Preserves Guest Link? | Preserves Booking Ref? |
|-----------------|---------------------|----------------------|------------------------|
| **iCal Sync** | N/A (authoritative) | ✅ Yes | ✅ Yes |
| **XLS Upload** | ✅ Yes (uid preserved) | ✅ Yes | ⚠️ Overwrites |
| **Email (future)** | ✅ Yes (uid preserved) | ✅ Yes | ✅ Yes |

**VERDICT:** ✅ Current implementation is SAFE - enrichments are preserved!

The only risk is uploading outdated XLS files that overwrite newer iCal changes.
