# Check-In Flow - Quick Testing Checklist

## ⚠️ BEFORE TESTING

### 1. Restart Celery Worker (CRITICAL!)
The code changes won't be picked up until you restart Celery:

```powershell
# In your Celery terminal window:
# Press Ctrl+C to stop the worker

# Then restart:
celery -A pickarooms worker --pool=solo --loglevel=info
```

**Watch for this in the startup logs:**
```
[tasks]
  . main.tasks.generate_checkin_pin_background  <-- Should be listed
```

### 2. Ensure Redis is Running
```powershell
redis-cli ping
# Should return: PONG
```

### 3. Ensure Django Server is Running
```powershell
python manage.py runserver
```

---

## ✅ QUICK TEST (5 minutes)

### Test Path:
1. Go to: `http://localhost:8000/checkin/`

2. **Step 1:** Enter booking reference
   - Use: `5735307998` (or your test booking)
   - Click "Continue"

3. **Step 2:** Enter guest details
   - Name: `Test Guest`
   - Phone: `7539029629` (select +44 UK)
   - Email: `test@example.com`
   - Click "Continue"
   - 🔥 **Check Celery terminal** - should show:
     ```
     Starting background PIN generation for session...
     ```

4. **Step 3:** Parking info
   - **IMPORTANT:** Take at least 10 seconds here (let PIN generate)
   - Select "Yes, I have a car"
   - Enter: `AB12 CDE`
   - Click "Continue"
   - 🔥 **Check Celery terminal** - should show:
     ```
     ✅ Background PIN generated successfully for session wtb8pl546py...: 1234
     ```

5. **Step 4:** Confirmation
   - **EXPECTED BEHAVIOR:**
     - ✅ Green box appears: "Your access PIN is ready!"
     - ✅ Button is enabled
     - ✅ Click "Confirm & Complete Check-In"
     - ✅ **INSTANT** redirect to room detail page (NO SPINNER!)

---

## 🐛 TROUBLESHOOTING

### Issue: Still seeing spinning circle

**Possible causes:**

1. **Celery not restarted** ❌
   - Solution: Restart Celery worker (see step 1 above)
   - Verify: Check Celery terminal for "generate_checkin_pin_background" in task list

2. **Session not found** ❌
   - Check Celery logs for:
     ```
     ERROR: Session {key} not found
     ```
   - Solution: Clear browser cookies and try again

3. **TTLock API failure** ❌
   - Check Celery logs for:
     ```
     ERROR: Failed to generate PIN for session...
     ```
   - Check if TTLock WiFi/gateway is online

4. **Redis not running** ❌
   - Solution: Start Redis server

---

## 🔍 VERIFICATION COMMANDS

### Check Celery is alive:
```powershell
celery -A pickarooms inspect ping
# Should return: pong from celery@Henry
```

### Check task stats:
```powershell
celery -A pickarooms inspect stats
# Look for: "main.tasks.generate_checkin_pin_background": X
# X should increment after each test
```

### Check active tasks:
```powershell
celery -A pickarooms inspect active
# Should be empty if task completed
```

### Check session data (replace SESSION_KEY):
```powershell
python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings'); import django; django.setup(); from django.contrib.sessions.models import Session; s = Session.objects.latest('expire_date'); import json; print(json.dumps(s.get_decoded().get('checkin_flow', {}), indent=2, default=str))"
```

**Should show:**
```json
{
  "pin_generated": true,    // ✅ This is the key!
  "pin": "1234",
  "front_door_pin_id": "...",
  "room_pin_id": "..."
}
```

---

## 📊 SUCCESS CRITERIA

- [x] Celery worker restarted
- [x] No errors in Celery terminal
- [x] PIN generated successfully (check logs)
- [x] Step 4 shows green "PIN ready" message
- [x] Clicking confirm redirects instantly
- [x] No spinning circle
- [x] Guest created successfully
- [x] Room detail page loads with PIN displayed

---

## 🆘 STILL STUCK?

Check these files for errors:
1. **Celery terminal** - Real-time task execution
2. **Django terminal** - Web request errors
3. **`debug.log`** - Historical errors
4. **Browser console** (F12) - JavaScript errors

Common patterns to search in `debug.log`:
```powershell
# Check for session encoding errors (should be GONE now)
type debug.log | findstr /C:"'Session' object has no attribute 'encode'"

# Check for recent PIN generation attempts
type debug.log | findstr /C:"generate_checkin_pin" | Select-Object -Last 10
```

---

**Ready to test? Go!** 🚀
