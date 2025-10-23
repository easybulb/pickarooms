# Celery Worker Optimization - Complete Summary

## 🚨 Problem Identified

Your Heroku worker was exceeding 100% usage due to:

1. **Duplicate Schedules** - Tasks defined in both `celery.py` and `settings.py`
2. **Excessive Polling** - Email polling every 2 minutes (720 times/day)
3. **Task Cascading** - Each email triggered multiple child tasks with 5 retry attempts
4. **Poor Process Management** - Beat + Worker running in single dyno (not recommended)
5. **No Rate Limiting** - Tasks could spawn infinitely without throttling

## ✅ Changes Made

### 1. **Procfile - Separated Beat from Worker**
```diff
- worker: celery -A pickarooms worker --beat --loglevel=info
+ worker: celery -A pickarooms worker --loglevel=info --concurrency=2 --max-tasks-per-child=100
+ beat: celery -A pickarooms beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

**Benefits:**
- Beat and worker run independently
- Worker can be scaled separately
- Better resource management
- Concurrency=2 allows 2 parallel tasks
- Auto-restart after 100 tasks prevents memory leaks

### 2. **Consolidated Schedules in settings.py**
Removed duplicate schedule from `celery.py` and put everything in `settings.py`:

| Task | Old Frequency | New Frequency | Reduction |
|------|---------------|---------------|-----------|
| Email polling | Every 2 min (720/day) | Every 5 min (288/day) | **60% reduction** |
| iCal polling | Every 10 min (144/day) | Every 15 min (96/day) | **33% reduction** |
| Archive guests | 3x/day | 3x/day | No change |
| Cleanup | 1x/day | 1x/day | No change |

### 3. **Added Rate Limiting to Tasks**

```python
@shared_task(bind=True, max_retries=1, rate_limit='10/m')  # Max 10 per minute
def sync_booking_com_rooms_for_enrichment(self, pending_id):
    ...

@shared_task(bind=True, max_retries=2, rate_limit='5/m')  # Max 5 per minute
def send_enrichment_failure_alert(self, pending_id):
    ...
```

### 4. **Added Task Execution Limits**

```python
CELERY_TASK_ACKS_LATE = True  # Only acknowledge after completion
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # Fetch 1 task at a time
CELERY_TASK_REJECT_ON_WORKER_LOST = True  # Reject tasks if worker crashes
CELERY_TASK_TIME_LIMIT = 300  # 5 min hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 240  # 4 min soft limit
CELERY_WORKER_MAX_TASKS_PER_CHILD = 100  # Restart after 100 tasks
```

### 5. **Added Task Expiration**

All scheduled tasks now expire if not picked up within a reasonable time:
- Email polling: Expires after 2 min
- iCal polling: Expires after 5 min
- Archive guests: Expires after 10 min
- Cleanup: Expires after 30 min

This prevents task queue buildup.

## 📊 Expected Improvements

### Task Execution Reduction
- **Email polling**: 720/day → 288/day = **432 fewer tasks/day**
- **iCal polling**: 144/day → 96/day = **48 fewer tasks/day**
- **Total reduction**: ~**480 fewer scheduled tasks per day**

### Worker Load Reduction
- Rate limiting prevents task cascading
- Task expiration prevents queue buildup
- Concurrency=2 allows efficient parallel processing
- Worker restarts prevent memory leaks

### Expected CPU Usage
- **Before**: 100%+ (overloaded)
- **After**: 30-50% (healthy range)

## 🚀 Deployment Steps

### Step 1: Scale Heroku Dynos
You now have 3 process types:
```bash
# Check current state
heroku ps -a pickarooms

# Scale the new beat process (REQUIRED - do this first!)
heroku ps:scale beat=1 -a pickarooms

# Optionally scale worker if needed (already at 1)
# heroku ps:scale worker=1 -a pickarooms

# Restart all processes to apply changes
heroku restart -a pickarooms
```

### Step 2: Monitor Performance
```bash
# Watch logs in real-time
heroku logs --tail -a pickarooms

# Check specific process logs
heroku logs --tail --source app/worker -a pickarooms
heroku logs --tail --source app/beat -a pickarooms

# Check dyno status
heroku ps -a pickarooms
```

### Step 3: Check Metrics
After 1 hour, check your Heroku dashboard:
- Worker CPU usage should be 30-50%
- Beat CPU usage should be <10%
- No task queue buildup

## 🔍 What to Monitor

### Good Signs ✅
- Worker CPU: 30-50%
- Beat CPU: <10%
- Tasks completing successfully
- No "Task exceeded time limit" errors
- Queue stays near 0

### Warning Signs ⚠️
- Worker CPU still >80%
- Tasks timing out
- Queue growing >100 tasks
- Memory usage increasing

### If Issues Persist
1. **Check for stuck tasks:**
   ```bash
   heroku run python manage.py shell -a pickarooms
   >>> from main.models import Guest
   >>> Guest.objects.filter(is_archived=False, check_out_date__lt='2025-01-01').count()
   ```

2. **Clear Redis queue if needed:**
   ```bash
   heroku redis:cli -a pickarooms
   >>> FLUSHALL
   ```

3. **Check for duplicate PendingEnrichment records:**
   ```bash
   heroku run python manage.py shell -a pickarooms
   >>> from main.models import PendingEnrichment
   >>> PendingEnrichment.objects.filter(status='pending').delete()
   ```

## 📝 Configuration Summary

### Before
- 1 dyno: `worker` (beat + worker combined)
- Email polling: Every 2 minutes
- iCal polling: Every 10 minutes
- No rate limiting
- No task expiration
- No worker concurrency limits

### After
- 2 dynos: `worker` + `beat` (separated)
- Email polling: Every 5 minutes
- iCal polling: Every 15 minutes
- Rate limiting: 10/min for syncs, 5/min for alerts
- Task expiration: All tasks expire after timeout
- Worker concurrency: 2 parallel tasks
- Worker restarts: After 100 tasks

## 🎯 Next Actions

1. **IMMEDIATE**: Scale beat dyno
   ```bash
   heroku ps:scale beat=1 -a pickarooms
   ```

2. **IMMEDIATE**: Restart all processes
   ```bash
   heroku restart -a pickarooms
   ```

3. **Monitor for 24 hours** - Check CPU usage and task completion

4. **Optional tweaks** if needed:
   - Increase email polling to 10 min if 5 min still too frequent
   - Reduce worker concurrency to 1 if CPU still high
   - Adjust rate limits if tasks getting throttled

## 💰 Cost Impact

- **Before**: 1 worker dyno
- **After**: 1 worker dyno + 1 beat dyno = **2 dynos total**

If on Heroku Hobby plan ($7/dyno/month):
- Monthly cost increase: $7 → $14 (~$7 more/month)

**Worth it?** YES - Properly separated processes are more stable and won't hit 100% CPU.

Alternative: You could reduce worker to 1 dyno and beat to 1 dyno on free hours if available, but production apps should have dedicated dynos.

## 📚 Additional Resources

- [Celery Best Practices](https://docs.celeryproject.org/en/stable/userguide/tasks.html#performance-and-strategies)
- [Django Celery Beat](https://django-celery-beat.readthedocs.io/)
- [Heroku Celery Configuration](https://devcenter.heroku.com/articles/celery-heroku)

---

**Created**: 2025-10-23  
**Status**: ✅ Deployed to GitHub (main branch)  
**Next**: Scale Heroku dynos and monitor
