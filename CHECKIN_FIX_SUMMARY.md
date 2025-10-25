# Check-In Flow - Session Encoding Fix

## 🐛 Problem Identified

The multi-step check-in flow was showing a **spinning/whirling circle** at Step 4 because the background PIN generation task was failing silently.

### Root Cause
The Celery background task `generate_checkin_pin_background` was trying to save PIN data to the Django session but was using the wrong method:

```python
# ❌ WRONG (caused the error)
session.session_data = session.encode(session_data)
session.save()
```

**Error:** `'Session' object has no attribute 'encode'`

The Django `Session` model doesn't have an `encode()` method - we needed to use the `SessionStore` backend instead.

---

## ✅ Solution Applied

Fixed the session encoding in `main/tasks.py` by using `SessionStore`:

```python
# ✅ CORRECT
from django.contrib.sessions.backends.db import SessionStore

session_store = SessionStore(session_key=session_key)
session_store.update(session_data)
session_store.save()
```

This fix was applied in **TWO places**:
1. When PIN generation **succeeds** (stores PIN in session)
2. When PIN generation **fails** (stores error message in session)

---

## 📊 Evidence of the Bug

From `debug.log`:
```
ERROR 2025-10-25 18:12:59,164 tasks Failed to generate PIN for session wtb8pl546py1l053mwzqsjkyw05euayy: 'Session' object has no attribute 'encode'
ERROR 2025-10-25 18:13:09,764 tasks Failed to generate PIN for session wtb8pl546py1l053mwzqsjkyw05euayy: 'Session' object has no attribute 'encode'
ERROR 2025-10-25 18:14:50,394 tasks Failed to generate PIN for session wtb8pl546py1l053mwzqsjkyw05euayy: 'Session' object has no attribute 'encode'
ERROR 2025-10-25 18:20:28,316 tasks Failed to generate PIN for session wtb8pl546py1l053mwzqsjkyw05euayy: 'Session' object has no attribute 'encode'
```

Celery task ran 4 times but failed each time because of the encoding error.

Session data check showed the PIN fields were missing:
```json
{
  "booking_ref": "5735307998",
  "reservation_id": 728,
  "step": 3,
  "full_name": "Amara",
  "phone_number": "+447539029629",
  "email": "easybulb@gmail.com",
  "has_car": true,
  "car_registration": "TT16 ABH"
  // ❌ Missing: pin_generated, pin, front_door_pin_id, room_pin_id
}
```

---

## 🎯 Expected Behavior After Fix

### Flow Timeline:

1. **Step 2 (Guest Details):** Guest submits name, phone, email
   - ✅ Trigger: Background task starts generating PIN
   - ✅ Guest redirected to Step 3 (parking)

2. **Step 3 (Parking Info):** Guest fills car registration (10-20 seconds)
   - ⏳ Background: PIN generation completes (2-5 seconds)
   - ✅ PIN stored in session: `pin_generated=True, pin=1234, front_door_pin_id=..., room_pin_id=...`

3. **Step 4 (Confirm):** Guest reviews details
   - ✅ AJAX polling checks PIN status via `/checkin/pin-status/`
   - ✅ If ready: Show ✅ "Your access PIN is ready!"
   - ✅ If failed: Redirect to error page after 2 seconds
   - ⏳ If still generating: Show ⏳ "Preparing your access PIN..."

4. **Step 4 (Submit):** Guest clicks "Confirm & Complete Check-In"
   - ✅ If PIN ready: Create guest immediately, instant redirect to room detail page
   - ❌ If PIN failed: Show error page with contact info
   - ⏳ If still generating (rare): Wait 2 seconds, then check again

---

## 🚀 Testing Instructions

### Prerequisites:
1. **Restart Celery Worker** (CRITICAL - picks up the code changes):
   ```powershell
   # Stop current Celery worker (Ctrl+C in Celery terminal)
   # Then restart:
   celery -A pickarooms worker --pool=solo --loglevel=info
   ```

2. **Django server running:**
   ```powershell
   python manage.py runserver
   ```

3. **Redis running** (Celery broker)

### Test Scenario 1: Happy Path (PIN Ready)
1. Go to `http://localhost:8000/checkin/`
2. Enter booking reference: `5735307998` (or any valid booking ref)
3. Click "Continue"
4. **Step 2:** Enter guest details
   - Name: `Test Guest`
   - Phone: `7539029629` (country code: +44)
   - Email: `test@example.com`
5. Click "Continue"
   - 🔥 **Background task triggers** (check Celery terminal for logs)
6. **Step 3:** Enter parking info (take your time - 10+ seconds)
   - Select "Yes, I have a car"
   - Enter car reg: `AB12 CDE`
7. Click "Continue"
8. **Step 4:** Confirmation page loads
   - ✅ **Expected:** Green box appears: "Your access PIN is ready!"
   - ✅ Button becomes enabled
   - ✅ Click "Confirm & Complete Check-In"
   - ✅ **INSTANT** redirect to room detail page (no loading spinner!)

### Test Scenario 2: Fast User (PIN Still Generating)
1. Same as above, but on **Step 3**, immediately click "No car" and "Continue" (2 seconds)
2. **Step 4:** Confirmation page loads
   - ⏳ **Expected:** Blue box appears: "Preparing your access PIN... Almost ready!"
   - ⏳ Spinner shows for 1-2 seconds
   - ✅ Then switches to green "Your access PIN is ready!"
   - ✅ Button becomes enabled

### Test Scenario 3: TTLock Failure (PIN Generation Fails)
*Difficult to test without disconnecting TTLock WiFi*
1. Same flow as above
2. **Step 4:** If TTLock API fails:
   - ❌ **Expected:** Red box appears: "PIN generation failed"
   - ❌ Auto-redirect to error page after 2 seconds
   - ❌ Error page shows contact info with booking reference

---

## 🔍 How to Verify Fix in Logs

### Celery Worker Terminal (should show):
```
[2025-10-25 18:30:00] INFO/MainProcess] Starting background PIN generation for session wtb8pl546py...
[2025-10-25 18:30:00] INFO/MainProcess] Looking for session with key: wtb8pl546py...
[2025-10-25 18:30:00] INFO/MainProcess] Session found, decoding data...
[2025-10-25 18:30:00] INFO/MainProcess] Session data keys: dict_keys(['_auth_user_id', 'checkin_flow'])
[2025-10-25 18:30:00] INFO/MainProcess] Flow data: {'booking_ref': '5735307998', 'reservation_id': 728, ...}
[2025-10-25 18:30:03] INFO/MainProcess] ✅ Background PIN generated successfully for session wtb8pl546py...: 1234
[2025-10-25 18:30:03] INFO/MainProcess] Task main.tasks.generate_checkin_pin_background[...] succeeded
```

### Django Debug Shell (check session):
```powershell
python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings'); import django; django.setup(); from django.contrib.sessions.models import Session; s = Session.objects.get(session_key='YOUR_SESSION_KEY'); import json; flow = s.get_decoded().get('checkin_flow', {}); print(json.dumps(flow, indent=2, default=str))"
```

**Expected output:**
```json
{
  "booking_ref": "5735307998",
  "reservation_id": 728,
  "step": 3,
  "full_name": "Test Guest",
  "phone_number": "+447539029629",
  "email": "test@example.com",
  "has_car": true,
  "car_registration": "AB12 CDE",
  "pin_generated": true,          // ✅ Present
  "pin": "1234",                   // ✅ Present
  "front_door_pin_id": "12345678", // ✅ Present
  "room_pin_id": "87654321"        // ✅ Present
}
```

---

## 📝 Files Modified

1. **`main/tasks.py`** (3 changes)
   - Added import: `from django.contrib.sessions.backends.db import SessionStore`
   - Fixed success case: Use `SessionStore` to save PIN data
   - Fixed error case: Use `SessionStore` to save error message

---

## 🎉 Expected Result

✅ **No more spinning circle!**
✅ PIN generated in background while guest fills Step 3
✅ Step 4 shows instant "PIN ready" message
✅ Clicking "Confirm" redirects immediately to room detail page
✅ UX feels premium and fast

---

## 🚨 If Issues Persist

1. **Check Celery is running with new code:**
   ```powershell
   celery -A pickarooms inspect stats
   ```
   Should show task count incrementing

2. **Check Redis is running:**
   ```powershell
   redis-cli ping
   ```
   Should return `PONG`

3. **Check Django logs** for any new errors

4. **Clear all sessions** (if stuck):
   ```powershell
   python manage.py shell -c "from django.contrib.sessions.models import Session; Session.objects.all().delete(); print('All sessions cleared')"
   ```

---

## 📚 Related Documents

- `CHECKIN_MULTISTEP_PROGRESS.md` - Overall progress tracker
- `CHECKIN_PART4_OVERVIEW.txt` - Original design discussion
- `main/checkin_views.py` - Multi-step check-in views
- `main/tasks.py` - Background PIN generation task

---

**Status:** ✅ **FIXED - Ready for Testing**
**Date:** October 25, 2025
**Issue:** Session encoding error causing background PIN generation to fail
**Solution:** Use `SessionStore` instead of `Session.encode()`
