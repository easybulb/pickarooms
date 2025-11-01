# iCal Sync System Revamp

**Date**: November 1, 2025
**Version**: v169
**Status**: Production

## Overview

This document describes the major improvements made to the iCal synchronization system to fix critical bugs related to duplicate reservations and incorrect cancellations when working with XLS uploads.

---

## Problems Fixed

### Problem 1: "CLOSED - Not available" Duplicate Reservations

**Issue**: After uploading XLS file with enriched bookings, iCal sync (runs every 15 minutes) would re-create "CLOSED - Not available" placeholder reservations for the same room+dates, causing duplicates.

**Example**:
```
Room 1, June 20-21, 2026:
- Maria Straub (booking_ref: 6668929481) ← From XLS upload
- CLOSED - Not available (no booking_ref) ← Re-created by iCal every 15 min
```

**Root Cause**: iCal sync had no collision detection. It would blindly create new reservations without checking if the room+dates were already occupied by enriched bookings.

**Solution**: Implemented **Method 3: Collision Detection** (lines 266-304 in `ical_service.py`)

---

### Problem 2: iCal Cancelling ALL XLS-Uploaded Reservations

**Issue**: After uploading XLS file, the next iCal sync would mark ALL XLS-created reservations as cancelled, even though they were valid bookings.

**Example**:
```
After XLS upload:
✓ Maria Straub - CONFIRMED
✓ Sarah Smith - CONFIRMED
✓ Darren Vicarey - CONFIRMED

After iCal sync (15 min later):
✗ Maria Straub - CANCELLED
✗ Sarah Smith - CANCELLED
✗ Darren Vicarey - CANCELLED
```

**Root Cause**: iCal sync's cancellation detection logic checked: "If reservation's ical_uid is NOT in the current iCal feed → mark as cancelled". XLS-created reservations have synthetic UIDs like `xls_6668929481_Room 1_17619374` which are never in the real iCal feed, so they were always getting cancelled.

**Solution**: Excluded XLS-created reservations from cancellation detection (line 377 in `ical_service.py`)

---

## Technical Implementation

### 1. Collision Detection (Method 3)

**File**: `main/services/ical_service.py`
**Lines**: 266-304

**Logic**:
```python
# Before creating a new iCal reservation, check if room+dates are already occupied
collision = Reservation.objects.filter(
    room=config.room,
    check_in_date=event['dtstart'],
    check_out_date=event['dtend'],
    status='confirmed'
).exclude(ical_uid=uid).first()
```

**Three Collision Scenarios**:

#### CASE A: Skip iCal Placeholder (Most Common)
```python
if collision.booking_reference and len(collision.booking_reference) >= 5:
    # Room occupied by enriched booking (from XLS/email)
    # Skip creating iCal placeholder to prevent duplicates
    logger.info(f"⚠️ COLLISION DETECTED: Skipping iCal event...")
    continue
```

**When**: iCal event is "CLOSED - Not available" (no booking_ref), but room is occupied by enriched booking with valid booking_ref.

**Action**: Skip creating the iCal reservation entirely.

#### CASE B: Replace Old Placeholder
```python
elif booking_ref and len(booking_ref) >= 5:
    # iCal event has valid booking_ref, collision doesn't
    # Replace old placeholder with new iCal event
    reservation = collision
    match_method = 'collision_replace'
```

**When**: iCal event has valid booking_ref (e.g., found in SUMMARY field), but existing reservation is an old placeholder without booking_ref.

**Action**: Update the existing placeholder with the new iCal event data.

#### CASE C: Update Existing Placeholder
```python
else:
    # Both are placeholders (no valid booking_ref)
    # Update existing instead of creating duplicate
    reservation = collision
    match_method = 'collision_update'
```

**When**: Both iCal event and existing reservation lack valid booking references.

**Action**: Update the existing reservation instead of creating a duplicate.

---

### 2. XLS Reservation Protection

**File**: `main/services/ical_service.py`
**Line**: 377

**Implementation**:
```python
missing_reservations = Reservation.objects.filter(
    room=config.room,
    platform=platform,
    status='confirmed',
).exclude(ical_uid__in=current_uids).exclude(ical_uid__startswith='xls_')
```

**Logic**:
- XLS-created reservations have `ical_uid` starting with `xls_` (e.g., `xls_6668929481_Room 1_17619374`)
- These reservations are **excluded** from iCal's cancellation detection
- XLS reservations are managed **only by XLS uploads**, never by iCal sync

**Why This Works**:
- XLS is the "single source of truth" for enriched bookings
- iCal provides raw placeholder data
- Email parser + iCal enrichment fills in booking references
- XLS upload can override/correct everything

---

## Existing Features (Still Intact)

### Method 1: Match by Booking Reference
```python
if booking_ref and len(booking_ref) >= 5:
    reservation = Reservation.objects.filter(
        booking_reference=booking_ref,
        room=config.room,
        check_in_date=event['dtstart']
    ).first()
```

Prevents duplicates when XLS upload happens before iCal sync.

### Method 2: Match by iCal UID
```python
reservation = Reservation.objects.get(ical_uid=uid)
```

Standard iCal behavior - match existing reservations by UID.

### Enrichment Workflow Trigger
```python
if platform == 'booking' and event_status == 'confirmed':
    from main.tasks import trigger_enrichment_workflow
    trigger_enrichment_workflow.delay(reservation.id)
```

After creating new reservations, automatically triggers email enrichment workflow to find booking references.

### Preserve XLS-Enriched Data
```python
if booking_ref and len(booking_ref) >= 5:
    reservation.booking_reference = booking_ref
    reservation.guest_name = event['summary']
elif not reservation.booking_reference or len(reservation.booking_reference) < 5:
    reservation.guest_name = event['summary']
else:
    # Preserve XLS-enriched data (booking_reference >= 5 chars)
    logger.info(f"Preserved XLS-enriched booking_ref: {reservation.booking_reference}")
```

iCal updates only update dates/status, never overwrite enriched data.

---

## System Workflow

### Normal Flow (Fresh Start)

```
1. iCal Sync (Every 15 min)
   ↓
   Creates reservations with:
   - guest_name: "CLOSED - Not available" OR booking name
   - booking_reference: "" (empty) OR extracted from SUMMARY
   - ical_uid: From iCal feed
   - status: confirmed
   ↓
2. Email Parser + iCal Enrichment (If emails available)
   ↓
   Updates reservations with:
   - booking_reference: From email subject (10 digits)
   - Triggers enrichment workflow
   ↓
3. XLS Upload (Manual)
   ↓
   Creates/Updates reservations with:
   - Complete guest data
   - booking_reference: From XLS
   - ical_uid: Synthetic "xls_" prefix
   - Deletes wrong assignments
   - Restores cancelled victims
   ↓
4. Next iCal Sync (15 min later)
   ↓
   COLLISION DETECTION prevents duplicates:
   - Skips "CLOSED" placeholders if enriched booking exists
   - Does NOT cancel XLS reservations (excluded by ical_uid prefix)
   ✅ System remains clean!
```

### Recovery Flow (Nuclear Reset)

```
1. Nuclear Delete All Reservations
   ↓
   heroku run python manage.py nuclear_reset_reservations --app pickarooms
   (Type: DELETE ALL)
   ↓
2. Wait 15 minutes for iCal sync
   OR trigger manually from /admin-page/
   ↓
   iCal creates fresh placeholder reservations
   ↓
3. Upload XLS file
   ↓
   XLS enriches/corrects all reservations
   ↓
4. Next iCal sync
   ↓
   Collision detection + XLS protection prevents duplicates/cancellations
   ✅ System stable!
```

---

## Benefits

### 1. No More Duplicate Reservations
- Collision detection prevents iCal from creating "CLOSED" duplicates
- Same room+dates can only have ONE confirmed reservation
- Enriched bookings always take priority over placeholders

### 2. XLS is Single Source of Truth
- XLS uploads never get cancelled by iCal
- XLS can freely correct mistakes without interference
- iCal respects XLS-enriched data

### 3. Safe Multi-Source Enrichment
- iCal provides raw data
- Email parser adds booking references
- XLS provides complete guest information
- All three sources work together without conflicts

### 4. Clean Recovery Process
- Nuclear reset option available
- Predictable re-sync behavior
- No manual cleanup required

---

## Testing Scenarios

### Scenario 1: XLS Upload Before iCal Sync
```
1. Upload XLS with Maria Straub (Room 1, June 20-21)
2. Wait for iCal sync
3. ✅ iCal detects collision, skips creating "CLOSED" placeholder
4. ✅ Only Maria's reservation exists
```

### Scenario 2: iCal Sync Before XLS Upload
```
1. iCal creates "CLOSED - Not available" (Room 1, June 20-21)
2. Upload XLS with Maria Straub (Room 1, June 20-21)
3. ✅ XLS creates Maria's reservation
4. Wait for next iCal sync
5. ✅ iCal detects collision, skips re-creating "CLOSED"
6. ✅ Maria remains confirmed (not cancelled)
```

### Scenario 3: Multiple XLS Uploads
```
1. Upload XLS with wrong room assignment (Darren → Room 1, 2)
2. Upload corrected XLS (Darren → Room 4)
3. ✅ XLS deletes wrong assignments
4. ✅ XLS restores cancelled victims (Maria, Sarah)
5. Wait for iCal sync
6. ✅ iCal does NOT cancel XLS reservations
7. ✅ iCal does NOT re-create deleted "CLOSED" placeholders
```

### Scenario 4: Nuclear Reset
```
1. Delete all reservations
2. iCal re-syncs, creates fresh placeholders
3. Upload XLS to enrich
4. ✅ System returns to clean state
5. ✅ No duplicates or incorrect cancellations
```

---

## Code Locations

### Main Implementation File
- **File**: `main/services/ical_service.py`
- **Function**: `sync_reservations_for_room(config_id, platform='booking')`

### Key Changes

#### Collision Detection
- **Lines**: 266-304
- **Purpose**: Prevent duplicate "CLOSED" reservations

#### XLS Protection
- **Line**: 377
- **Change**: Added `.exclude(ical_uid__startswith='xls_')`
- **Purpose**: Prevent cancelling XLS-created reservations

#### Enrichment Trigger (Unchanged)
- **Lines**: 356-361
- **Purpose**: Automatically trigger email enrichment for new reservations

#### Data Preservation (Unchanged)
- **Lines**: 321-334
- **Purpose**: Never overwrite XLS-enriched booking references

---

## Deployment History

### v168 (2025-11-01 02:45 UTC)
- **Change**: Added collision detection (Method 3)
- **Commit**: `caebc16` - "Add collision detection to iCal sync to prevent duplicate reservations"
- **Status**: Partially fixed - prevented duplicates but caused cancellations

### v169 (2025-11-01 03:15 UTC)
- **Change**: Protected XLS reservations from cancellation
- **Commit**: `fe44b59` - "Fix critical bug: Prevent iCal from cancelling XLS-created reservations"
- **Status**: ✅ Fully fixed - no duplicates, no incorrect cancellations

---

## Related Documentation

- **XLS Upload System**: See `docs/XLS_UPLOAD_SYSTEM_UPDATE.md`
- **Email Enrichment**: See enrichment workflow documentation
- **Nuclear Reset Script**: `main/management/commands/nuclear_reset_reservations.py`

---

## Monitoring

### Log Messages to Watch For

**Collision Detection Working**:
```
⚠️ COLLISION DETECTED: Skipping iCal event 'CLOSED - Not available...'
because room Room 1 is already occupied by enriched booking
6668929481 (Maria Straub) for 2026-06-20 to 2026-06-21
```

**XLS Protection Working**:
```
# No cancelled reservations with ical_uid starting with 'xls_'
```

**Normal Updates**:
```
Updated reservation (method=booking_ref, preserved enrichments): ...
Preserved XLS-enriched booking_ref: 6668929481
```

### Admin Dashboard Checks

1. Check `/admin-page/` for duplicate reservations
2. Verify XLS-uploaded reservations remain confirmed
3. Monitor enrichment status (should stay enriched)
4. Check for "CLOSED - Not available" duplicates

---

## Known Limitations

### XLS Synthetic UIDs
- XLS reservations have UIDs like `xls_6668929481_Room 1_17619374`
- These never match real iCal UIDs
- This is **intentional** - allows iCal protection to work

### iCal Cannot Update XLS Reservations
- Once XLS creates a reservation, iCal cannot update it
- This is **by design** - XLS is single source of truth
- Only XLS uploads can modify XLS-created reservations

### Collision Detection Only Prevents Duplicates
- Does not retroactively clean up existing duplicates
- Use nuclear reset for clean slate
- Prevention-focused, not cleanup-focused

---

## Troubleshooting

### Problem: Duplicates Still Appearing
**Check**:
1. Are both reservations confirmed?
2. Do they have different `ical_uid` values?
3. Was one created before v168 deployment?

**Solution**: Run nuclear reset and re-upload XLS

### Problem: XLS Reservations Getting Cancelled
**Check**:
1. Verify deployment version is v169 or later
2. Check if `ical_uid` starts with `xls_`
3. Review iCal sync logs

**Solution**: Ensure v169 is deployed, re-upload XLS

### Problem: "CLOSED" Placeholders Not Being Skipped
**Check**:
1. Does existing reservation have valid booking_ref (≥5 chars)?
2. Are dates exactly matching?
3. Is status = confirmed?

**Solution**: Review collision detection logic, check logs

---

## Future Improvements

### Potential Enhancements
1. **Retroactive Cleanup**: Script to delete existing duplicates automatically
2. **Smart UID Linking**: Link XLS reservations to real iCal UIDs when booking_ref matches
3. **Conflict Resolution UI**: Admin dashboard to manually resolve conflicts
4. **Automated Testing**: Unit tests for all collision scenarios

### Not Recommended
- Allowing iCal to update XLS reservations (breaks single source of truth)
- Removing XLS UID prefix (breaks protection mechanism)
- Disabling collision detection (causes duplicates)

---

## Conclusion

The iCal sync revamp successfully addresses two critical bugs:
1. ✅ Duplicate "CLOSED - Not available" reservations
2. ✅ Incorrect cancellation of XLS-uploaded bookings

The system now properly handles multi-source data enrichment (iCal + Email + XLS) without conflicts, maintaining XLS as the single source of truth while allowing iCal to provide raw placeholder data and email enrichment to add booking references.

**Status**: Production-ready (v169)
**Stability**: High
**Tested**: Yes (multiple scenarios verified)
**Recommended**: Use nuclear reset for clean slate, then normal XLS upload workflow