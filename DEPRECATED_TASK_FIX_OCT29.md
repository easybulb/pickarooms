# 🔧 CRITICAL FIX: Deprecated Task Removal (Oct 29, 2025)

## 🚨 Problem Identified

**Issue**: Old SMS and email alerts were still triggering despite deprecated email-driven enrichment flow being removed.

**Root Cause**: The `poll_booking_com_emails` task was:
1. ✅ Removed from `main/tasks.py` (commit `66ca5f1`)
2. ❌ **Still defined in `pickarooms/settings.py`** - This was the problem!
3. ❌ **Still in database** as a PeriodicTask record

**Result**: Celery Beat kept recreating the task from settings.py on every restart, causing old SMS/email behavior to persist.

---

## 🔍 Investigation Timeline

### 1. Discovery (Oct 29, 13:30 UTC)
- User reported still receiving old SMS/email messages
- Checked active Celery Beat tasks in production database

```bash
heroku run python manage.py shell -c "from django_celery_beat.models import PeriodicTask; [print(t.name, t.enabled) for t in PeriodicTask.objects.all()]" -a pickarooms
```

**Found**:
```
poll-booking-com-emails  True  ← PROBLEM!
```

### 2. Root Cause Analysis
- Task function deleted from code but defined in two places:
  - `pickarooms/settings.py` (CELERY_BEAT_SCHEDULE)
  - Database (PeriodicTask model)
- Celery Beat syncs CELERY_BEAT_SCHEDULE → Database on startup
- Even after manual deletion, task would recreate on next beat restart

### 3. Files Searched
```bash
grep -r "poll_booking_com_emails" --include="*.py"
```

**Found in**:
- ✅ `main/tasks.py` - Function already removed
- ❌ `pickarooms/settings.py` - **Still defined** (lines 361-367)
- ✅ Management commands (references only, not definitions)

---

## ✅ Solution Implemented

### Step 1: Remove from settings.py (Commit b2fabb5)

**File**: `pickarooms/settings.py`

**Before** (lines 358-367):
```python
CELERY_BEAT_SCHEDULE = {
    # Email polling - Reduced from 2min to 5min to reduce load
    'poll-booking-com-emails': {
        'task': 'main.tasks.poll_booking_com_emails',
        'schedule': 300.0,  # Every 5 minutes (reduced from 2 min)
        'options': {
            'expires': 120,  # Task expires after 2 minutes if not picked up
        }
    },
    # iCal feed polling - Reduced from 10min to 15min
```

**After**:
```python
CELERY_BEAT_SCHEDULE = {
    # REMOVED: poll-booking-com-emails (deprecated Oct 29, 2025)
    # Old email-driven flow removed in favor of iCal-driven enrichment

    # iCal feed polling - Reduced from 10min to 15min
```

**Commit Message**:
```
CRITICAL FIX: Remove deprecated poll_booking_com_emails from CELERY_BEAT_SCHEDULE

- Task was deleted from code but still defined in settings.py
- Celery Beat was recreating it automatically on restart
- This was causing old SMS/email alerts to trigger
- Replaced with comment explaining removal

Related: commit 66ca5f1 (removed task function from tasks.py)
```

### Step 2: Delete from LOCAL Database

```bash
python manage.py shell -c "from django_celery_beat.models import PeriodicTask; tasks = PeriodicTask.objects.filter(name='poll-booking-com-emails'); tasks.delete()"
```

**Result**: Deleted 1 task(s) from LOCAL database

### Step 3: Deploy to Heroku

```bash
git add pickarooms/settings.py
git commit -m "CRITICAL FIX: Remove deprecated poll_booking_com_emails from CELERY_BEAT_SCHEDULE"
git push heroku main
```

**Result**: Deployed as v122

### Step 4: Delete from HEROKU Database

**Via Django Admin Panel**:
1. Navigate to: https://pickarooms-495ab160017c.herokuapp.com/admin/django_celery_beat/periodictask/
2. Found task: `poll-booking-com-emails` (ID: 137, Enabled: True)
3. Manually deleted via admin interface

### Step 5: Restart Heroku Dynos

```bash
heroku ps:restart beat -a pickarooms
heroku ps:restart worker -a pickarooms
```

**Verification**: Beat logs show clean startup
```
2025-10-29T13:58:10.844626+00:00 app[beat.1]: [INFO] DatabaseScheduler: Schedule changed.
```

---

## 🎯 Current State (Verified Clean)

### Active Celery Beat Tasks (7 total)
```
✅ poll-ical-feeds-every-15-minutes (main.tasks.poll_all_ical_feeds)
✅ archive-past-guests-midday (main.tasks.archive_past_guests)
✅ archive-past-guests-afternoon (main.tasks.archive_past_guests)
✅ archive-past-guests-evening (main.tasks.archive_past_guests)
✅ cleanup-old-reservations-daily (main.tasks.cleanup_old_reservations)
✅ cleanup-enrichment-logs-daily (main.tasks.cleanup_old_enrichment_logs)
✅ celery.backend_cleanup (celery.backend_cleanup)
```

### Removed Tasks
```
❌ poll-booking-com-emails (DELETED - will not recreate)
```

---

## 📊 Impact & Verification

### Expected Behavior (Current)
- ✅ iCal feed polling every 15 minutes (active)
- ✅ Email search triggered only when new reservation detected
- ✅ SMS alerts sent only when email NOT found after 10 minutes
- ✅ No old-format SMS messages
- ✅ No duplicate email polling

### Old Behavior (Fixed)
- ❌ Gmail polling every 5 minutes (deprecated flow)
- ❌ Old SMS format with booking reference in reply
- ❌ Duplicate enrichment workflows running simultaneously

### Monitoring Checklist
Monitor production for next 24-48 hours:
- [ ] No old-format SMS alerts
- [ ] No "email not found" alerts for bookings that exist
- [ ] iCal-driven enrichment working correctly
- [ ] Beat dyno logs show no errors
- [ ] Worker dyno processing tasks normally

---

## 🔗 Related Documentation

- [ENRICHMENT_FLOW_HISTORY.md](ENRICHMENT_FLOW_HISTORY.md) - Architecture history
- [SMS_REPLY_QUICK_REFERENCE.md](SMS_REPLY_QUICK_REFERENCE.md) - Current SMS commands
- Commit `66ca5f1` - Removed deprecated task functions (369 lines)
- Commit `b2fabb5` - Removed task from settings.py (this fix)

---

## 🛡️ Prevention Measures

### For Future Task Deprecation
When removing a Celery periodic task, ensure:

1. ✅ Remove task function from `main/tasks.py`
2. ✅ **Remove task from `pickarooms/settings.py` (CELERY_BEAT_SCHEDULE)**
3. ✅ Delete task from database (both local and production)
4. ✅ Restart Celery Beat dyno
5. ✅ Verify task doesn't recreate (check admin panel after 5 minutes)
6. ✅ Monitor logs for 24 hours

### Checklist Template
```bash
# 1. Remove from code
# Edit: main/tasks.py

# 2. Remove from settings
# Edit: pickarooms/settings.py (CELERY_BEAT_SCHEDULE)

# 3. Delete from local DB
python manage.py shell -c "from django_celery_beat.models import PeriodicTask; PeriodicTask.objects.filter(name='task-name').delete()"

# 4. Deploy to Heroku
git add .
git commit -m "Remove deprecated task: task-name"
git push heroku main

# 5. Delete from Heroku DB
heroku run python manage.py disable_and_delete_deprecated_task -a pickarooms
# OR via admin panel: /admin/django_celery_beat/periodictask/

# 6. Restart dynos
heroku ps:restart beat -a pickarooms
heroku ps:restart worker -a pickarooms

# 7. Verify
heroku logs --tail --dyno-name=beat -a pickarooms
```

---

## 🔍 Debugging Commands (Future Reference)

### Check Active Tasks (Local)
```bash
python manage.py shell -c "from django_celery_beat.models import PeriodicTask; [print(f'{t.name} - Enabled: {t.enabled}') for t in PeriodicTask.objects.filter(enabled=True)]"
```

### Check Active Tasks (Heroku)
```bash
heroku run python manage.py check_beat_tasks -a pickarooms
```

### View Beat Schedule (Heroku Logs)
```bash
heroku logs --tail --dyno-name=beat -a pickarooms | grep "Scheduler: Sending"
```

### Delete Specific Task
```bash
heroku run python manage.py disable_and_delete_deprecated_task -a pickarooms
```

---

**Status**: ✅ RESOLVED
**Fixed**: Oct 29, 2025 @ 13:58 UTC
**Deployed**: Heroku v122 (commit b2fabb5)
**Next Steps**: Monitor production for 24-48 hours, then proceed with views.py refactoring

---

**Author**: Claude (with Henry)
**Last Updated**: Oct 29, 2025
