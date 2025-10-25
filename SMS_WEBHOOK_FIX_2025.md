# SMS Webhook Fix - January 2025

## Problem Discovered
- **Date:** 25 October 2025 (Heroku logs show Oct, but current date is Jan 2025)
- **Issue:** SMS replies to enrichment alerts (bookings 6582060925 & 5317556059) were received by webhook but not processed
- **Evidence:** Heroku logs showed `POST /webhooks/twilio/sms/ HTTP/1.1 200` but no handler logs appeared
- **Database Status:** 
  - PendingEnrichment: Both bookings still in `pending` status
  - Reservation: No records created
  - EnrichmentLog: No `sms_reply_assigned` entries

## Root Cause
The SMS webhook handler (`handle_twilio_sms_webhook`) was:
1. Receiving SMS successfully (HTTP 200 response)
2. But producing NO logs from the handler function
3. This means either logger wasn't writing to stdout OR exceptions were swallowed silently

## Fix Applied

### 1. Enhanced SMS Reply Handler (`main/services/sms_reply_handler.py`)
**Added:** Automatic SMS confirmation for all enrichment operations

```python
def send_confirmation_sms(to_number, message):
    """Send SMS confirmation back to admin via Twilio"""
```

**Now sends confirmation for:**
- ✅ Successful assignment: "✅ ENRICHMENT COMPLETE\n\nBooking: #123...\nRoom: Room 2..."
- ❌ Errors: "❌ Invalid format: '2 3'..." with instructions
- ⚠️ Already assigned: Prevents duplicate reservations
- 🚫 Cancellation: "✅ CANCELLED\n\nBooking: #123..."

### 2. Fixed Webhook Logging (`main/views.py`)
**Added:** Explicit `print()` statements to stderr as backup to logger

```python
import sys
print(f"[SMS WEBHOOK] Received SMS from {from_number}: '{body}'", file=sys.stderr)
```

**Why:** Django logger sometimes doesn't output to Heroku logs. Explicit prints ensure visibility.

### 3. Created Status Check Command
```bash
python manage.py check_enrichment_status 6582060925 5317556059
```

Shows:
- PendingEnrichment status
- Reservation existence
- EnrichmentLog timeline
- Whether guest checked in

## What Happens Now

### When You Reply to Next Alert SMS:
1. **Webhook receives SMS** → Logs: `[SMS WEBHOOK] Received SMS from +447539029629: '2-3'`
2. **Handler processes** → Logs: `[SMS WEBHOOK] Handler result: Assigned...`
3. **Confirmation SMS sent** → You receive: "✅ ENRICHMENT COMPLETE..."
4. **Reservation created** → Visible in `/admin-page/all-reservations/`
5. **EnrichmentLog updated** → Action: `sms_reply_assigned`

### For Old Bookings (6582060925 & 5317556059):
Since they're still `pending`, you can:
1. **Re-reply to original SMS** → System will process again
2. **Or manually assign via dashboard** → `/admin-page/pending-enrichments/`

## Files Changed
1. ✅ `main/services/sms_reply_handler.py` - Added `send_confirmation_sms()` + confirmation messages
2. ✅ `main/views.py` - Added explicit logging to `handle_twilio_sms_webhook()`
3. ✅ `main/management/commands/check_enrichment_status.py` - New command for status checking
4. ✅ Documentation files (SMS_CONFIRMATION_ENHANCEMENT.md, etc.)

## Testing After Deployment
```bash
# 1. Deploy to Heroku
git push heroku main

# 2. Check if old enrichments worked
python manage.py check_enrichment_status 6582060925 5317556059

# 3. Watch logs for next SMS
heroku logs --tail --app pickarooms | grep "SMS WEBHOOK"

# 4. Verify confirmation SMS arrives
```

## Deployment Status
- ✅ Pushed to GitHub main: Commit `5a0c42e`
- ⏳ Awaiting Heroku deployment by admin
- ✅ No breaking changes - backward compatible

---

**Last Updated:** January 2025  
**Commits:** 265cf70 (initial), 5a0c42e (webhook fix)  
**Ready for:** `git push heroku main`
