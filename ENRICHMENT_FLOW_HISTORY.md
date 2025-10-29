# 📜 Enrichment Flow History & Architecture

## Overview
This document explains the evolution of the PickARooms booking enrichment system, including what was deprecated and why.

---

## 🏗️ Current Architecture (Active)

### **iCal-Driven Flow** (Oct 26, 2025 - Present)

**How it works:**
1. iCal feed polling (every 15 minutes) detects new reservations
2. New unenriched reservation triggers `trigger_enrichment_workflow()`
3. System checks for collision (multiple bookings same day)
4. If single booking → searches Gmail for matching email (4 attempts over 10 min)
5. If found → enriches with booking reference
6. If not found → sends SMS alert to admin

**Active Tasks in `main/tasks.py`:**
- `trigger_enrichment_workflow()` - Entry point when iCal creates reservation
- `search_email_for_reservation()` - Searches Gmail for booking reference (4 attempts)
- `send_collision_alert_ical()` - SMS alert for multiple bookings same date
- `send_multi_room_confirmation_sms()` - Confirms multi-room bookings with admin
- `send_email_not_found_alert()` - SMS alert when email not found after 10 min

**Advantages:**
- ✅ More reliable (iCal is primary source of truth)
- ✅ Fewer false positives
- ✅ Handles multi-room bookings automatically
- ✅ Better collision detection
- ✅ Less Celery task overhead

---

## 🗄️ Deprecated Architecture (Removed Oct 29, 2025)

### **Email-Driven Flow** (Oct 23-26, 2025)

**How it worked:**
1. Gmail polling (every 5 minutes) detected Booking.com emails
2. Email created `PendingEnrichment` record
3. System triggered iCal sync to find matching reservation
4. Retry logic: 5 attempts over 15 minutes
5. If no match → sent SMS alert for manual assignment

**Removed Tasks (369 lines):**
- ❌ `poll_booking_com_emails()` - Polled Gmail every 5 minutes
- ❌ `sync_booking_com_rooms_for_enrichment()` - Triggered iCal sync after email
- ❌ `match_pending_to_reservation()` - Attempted to match email to iCal reservation
- ❌ `send_enrichment_failure_alert()` - Dispatched failure alerts
- ❌ `send_single_booking_alert()` - Sent SMS with old format (see below)
- ❌ `send_collision_alert()` - Old collision detection logic

**Why it was deprecated:**
- ⚠️ Race condition: Email could arrive before iCal sync completed
- ⚠️ False negatives: Booking might exist but iCal hadn't synced yet
- ⚠️ More complex: Required `PendingEnrichment` model + retry scheduling
- ⚠️ Higher Celery overhead: More frequent polling + retry chains

---

## 📱 SMS Format Changes

### Old Format (Deprecated)
```
PickARooms Alert:
Booking #6001569138 for 04 Apr 2026 not found in iCal.

Reply with:
6001569138: ROOM-NIGHTS

Examples:
6001569138: 1-3
6001569138: 2-2
6001569138: 3-1
Or reply X to cancel
```

**Issues:**
- Required booking reference in reply (redundant)
- Format: `6001569138: 1-3`

### New Format (Active)
```
PickARooms Alert

New booking detected (iCal)
Email not found after 10 min

Room: Room 2
Check-in: 04 Apr 2026
Check-out: 07 Apr 2026 (3 nights)

Reply with booking ref only:

Example: 6588202211
```

**Improvements:**
- Simpler reply format (just booking reference)
- More context (shows room, dates, nights)
- Clearer instructions

---

## 📊 Model Usage

### Active Models
- ✅ `Reservation` - All bookings (enriched or not)
- ✅ `EnrichmentLog` - Audit trail for enrichment actions
- ✅ `Guest` - Created after check-in with full details

### Deprecated Models (Still in DB, but not actively used by email-driven flow)
- ⚠️ `PendingEnrichment` - Used by old email-driven flow
  - **Status:** Still exists in database for historical records
  - **Usage:** No longer created by new flow
  - **Cleanup:** Can be deleted via admin or management command

---

## 🔄 Migration Timeline

| Date | Event | Commit |
|------|-------|--------|
| Oct 23, 2025 | Email-driven flow implemented | `f24ae7e` |
| Oct 26, 2025 | iCal-driven flow implemented (Phase 1) | `f9870c1` |
| Oct 26, 2025 | Old tasks marked as DEPRECATED | `b95839d` |
| Oct 26, 2025 | Multi-room support added to new flow | `7ef16aa` |
| Oct 29, 2025 | **Deprecated tasks removed (369 lines)** | `66ca5f1` |

---

## 🎯 Future Considerations

### If You Need to Restore Old Flow
1. Checkout commit `4c16dbe` (last commit before deletion)
2. Extract old tasks from `main/tasks.py`
3. Re-enable `poll_booking_com_emails` in Celery Beat schedule

### Recommended Path Forward
- ✅ Keep current iCal-driven flow
- ✅ Monitor `EnrichmentLog` for email search success rates
- ✅ Consider removing `PendingEnrichment` model in future migration
- ✅ Update `SMS_REPLY_QUICK_REFERENCE.md` if any SMS format changes

---

## 📝 Key Learnings

1. **iCal as Source of Truth:** More reliable than email parsing
2. **Simplify SMS Replies:** Users prefer minimal input
3. **Audit Everything:** `EnrichmentLog` is invaluable for debugging
4. **Multi-room Detection:** Rare but critical edge case to handle
5. **Deprecation Period:** Kept old code for 3 days before deletion (safe buffer)

---

## 🔗 Related Files

- `main/tasks.py` - All Celery tasks (current flow only)
- `main/services/gmail_client.py` - Gmail API wrapper (still used)
- `main/services/email_parser.py` - Email subject parsing (still used)
- `main/services/ical_service.py` - iCal feed sync (primary trigger)
- `main/models.py` - Database models (Reservation, EnrichmentLog, Guest)
- `SMS_REPLY_QUICK_REFERENCE.md` - Admin SMS command reference

---

**Last Updated:** Oct 29, 2025  
**Current Flow Version:** iCal-Driven (v2)  
**Status:** ✅ Production Ready
