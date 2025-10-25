# Debug: Past Guests Not Showing - Investigation

## Issue Report
**Problem**: Archived guests are not appearing on `/admin-page/past-guests/` page

---

## ✅ Code Review Results

### 1. **Past Guests View Logic** (`main/views.py` line ~1969)
```python
def past_guests(request):
    past_guests = Guest.objects.filter(
        is_archived=True  # ✅ CORRECT - Queries archived guests
    ).select_related('assigned_room').prefetch_related('reservation')
    
    past_guests = past_guests.order_by('-check_out_date')  # ✅ CORRECT
    paginator = Paginator(past_guests, 50)  # ✅ Shows 50 per page
```
**Status**: ✅ **Logic is CORRECT**

---

### 2. **Archive Task Logic** (`main/tasks.py` line ~330)
```python
# Update guest status
guest.front_door_pin = None
guest.front_door_pin_id = None
guest.room_pin_id = None
guest.is_archived = True  # ✅ CORRECT - Sets archived flag
guest.save()

# Send post-stay message if the guest has contact info
if guest.phone_number or guest.email:
    try:
        guest.send_post_stay_message()  # ✅ Respects dont_send_review_message
```
**Status**: ✅ **Logic is CORRECT**

---

### 3. **Archive Schedule** (`pickarooms/settings.py`)
```python
# Archive past guests - Midday check (12:15 PM)
'archive-past-guests-midday': {
    'task': 'main.tasks.archive_past_guests',
    'schedule': crontab(hour=12, minute=15),  # 12:15 PM UK time
},
# Archive past guests - Afternoon check (3:00 PM)
'archive-past-guests-afternoon': {
    'task': 'main.tasks.archive_past_guests',
    'schedule': crontab(hour=15, minute=0),  # 3:00 PM UK time
},
# Archive past guests - Evening check (11:00 PM)
'archive-past-guests-evening': {
    'task': 'main.tasks.archive_past_guests',
    'schedule': crontab(hour=23, minute=0),  # 11:00 PM UK time
},
```
**Status**: ✅ **Schedule is CORRECT** (3 times daily)

---

## 🔍 Possible Root Causes

### **Cause 1: Archive Task Not Running** ⚠️
**Check**: Is Celery Beat running on Heroku?

```bash
# Check if Celery Beat is scheduled
heroku logs --tail --app pickarooms-495ab160017c | grep "archive_past_guests"

# Check Celery Beat status
heroku ps --app pickarooms-495ab160017c
```

**Expected output**:
```
web.1: up 2025/01/XX
worker.1: up 2025/01/XX  ✅ Must be running
beat.1: up 2025/01/XX    ✅ Must be running (scheduler)
```

**If beat.1 is missing**:
```bash
heroku ps:scale beat=1 --app pickarooms-495ab160017c
```

---

### **Cause 2: No Guests Have Checked Out Yet** 🤔
**Check**: Are there guests who should be archived?

**Archive criteria**:
- `is_archived = False` (currently active)
- `check_out_date <= today` (checkout date has passed)
- Current time > `late_checkout_time` or 11:00 AM (default)

**Query to check**:
```python
from main.models import Guest
from datetime import date

# Guests that SHOULD be archived
should_be_archived = Guest.objects.filter(
    is_archived=False,
    check_out_date__lt=date.today()  # Checkout before today
)
print(f"Guests awaiting archive: {should_be_archived.count()}")
```

---

### **Cause 3: Guests Are Being DELETED Instead of Archived** ❌
**Check**: Is manual delete action being used?

In `main/views.py` line ~1965:
```python
def delete_guest(request, guest_id):
    guest.delete()  # ❌ This DELETES guest (not archives)
```

**If admin manually deletes guests**, they won't appear in past_guests!

**Solution**: Should use archive instead of delete

---

### **Cause 4: Database Migration Missing** 🗄️
**Check**: Is `is_archived` field in database?

```bash
# Check if field exists
heroku run python manage.py shell --app pickarooms-495ab160017c
>>> from main.models import Guest
>>> Guest._meta.get_field('is_archived')
```

---

### **Cause 5: Archive Task Has Errors** ⚠️
**Check**: Are there errors in logs?

```bash
# Check for archive errors
heroku logs --tail --app pickarooms-495ab160017c | grep -E "archive_past_guests|Failed to archive"
```

**Common errors**:
- TTLock API failures (doesn't stop archiving, just logs warning)
- Database save errors
- Timezone issues

---

## 🛠️ Debugging Steps

### **Step 1: Check if ANY archived guests exist**
```bash
heroku run python manage.py shell --app pickarooms-495ab160017c
```
```python
from main.models import Guest

# Count archived guests
archived_count = Guest.objects.filter(is_archived=True).count()
print(f"Archived guests in database: {archived_count}")

# Show recent archived guests
recent = Guest.objects.filter(is_archived=True).order_by('-check_out_date')[:5]
for g in recent:
    print(f"{g.full_name} - {g.reservation_number} - {g.check_out_date}")
```

**Expected**: Should show count > 0 if guests have been archived

---

### **Step 2: Check Celery Beat schedule**
```bash
heroku run python manage.py shell --app pickarooms-495ab160017c
```
```python
from django_celery_beat.models import PeriodicTask

# Check archive tasks are scheduled
archive_tasks = PeriodicTask.objects.filter(name__icontains='archive')
for task in archive_tasks:
    print(f"{task.name} - Enabled: {task.enabled} - Last run: {task.last_run_at}")
```

---

### **Step 3: Manually trigger archive task**
```bash
heroku run python manage.py shell --app pickarooms-495ab160017c
```
```python
from main.tasks import archive_past_guests

# Manually trigger
result = archive_past_guests()
print(result)  # Should show "Archived X guest(s), Y error(s)"
```

---

### **Step 4: Check past_guests page directly**
```bash
# Visit URL
https://www.pickarooms.com/admin-page/past-guests/

# Check browser console for errors
# Check if pagination is working (bottom of page)
```

---

## 🎯 Most Likely Causes (Ranked)

1. **Archive task not running** (Celery Beat not scaled on Heroku) - 60%
2. **No guests have checked out yet** (fresh deployment) - 20%
3. **Guests manually deleted instead of archived** - 15%
4. **Archive task has errors** (check logs) - 5%

---

## 💡 Recommended Fix

### **Quick Check Command**:
```bash
# Run this single command to diagnose:
heroku run python manage.py shell --app pickarooms-495ab160017c << EOF
from main.models import Guest
from datetime import date

archived = Guest.objects.filter(is_archived=True).count()
should_archive = Guest.objects.filter(is_archived=False, check_out_date__lt=date.today()).count()

print(f"✅ Archived guests: {archived}")
print(f"⏳ Awaiting archive: {should_archive}")

if archived == 0 and should_archive > 0:
    print("❌ ISSUE: Guests need archiving but none archived yet")
    print("Solution: Check if Celery Beat is running (heroku ps)")
elif archived > 0:
    print("✅ Archive working! Check past_guests page directly")
else:
    print("ℹ️ No guests have checked out yet")
EOF
```

---

## 🔧 Quick Fixes

### **If Celery Beat is not running**:
```bash
heroku ps:scale beat=1 --app pickarooms-495ab160017c
heroku restart --app pickarooms-495ab160017c
```

### **If guests need immediate archiving**:
```bash
heroku run python manage.py shell --app pickarooms-495ab160017c
>>> from main.tasks import archive_past_guests
>>> archive_past_guests()
```

### **If page loads but shows "No past guests"**:
- Check pagination (might be on page 2+)
- Check search filter (might be filtering out results)
- Check browser console for JavaScript errors

---

## 📝 Next Steps

Please run the **Quick Check Command** above and share the output. That will tell us exactly what's wrong! 🎯

