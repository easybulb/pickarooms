# Gmail Label Filtering Setup Instructions

## Overview

The email parsing system now supports **Gmail label filtering** to prevent processing old unread emails. This feature:
- ✅ Stops Redis overload from processing hundreds of old unread emails
- ✅ Gives you control over which emails to process
- ✅ Reduces unnecessary iCal syncs and Celery tasks
- ✅ Is **optional** - works without the label filter (backward compatible)

---

## How It Works

**WITHOUT Label Filter (Default):**
```
Email polling finds: ALL unread Booking.com emails
Result: Processes old emails → Creates pending enrichments → Redis overload
```

**WITH Label Filter (Recommended):**
```
Email polling finds: ONLY unread Booking.com emails with label "Pickarooms"
Result: Only processes new emails you manually label → No old emails processed
```

---

## Setup Steps

### Step 1: Create a Gmail Label

1. **Go to Gmail**: https://mail.google.com
2. **Create a new label**:
   - Click the gear icon (Settings) → "See all settings"
   - Go to "Labels" tab
   - Click "Create new label"
   - Name it: `Pickarooms` (or any name you prefer)
   - Click "Create"

### Step 2: Set Up Gmail Filter (Recommended)

**Option A: Manual Labeling** (Simple but requires manual work)
- When you receive a new Booking.com email, manually apply the "Pickarooms" label to it
- Only labeled emails will be processed

**Option B: Auto-Labeling with Filter** (Recommended - Automatic)

1. **Create a Gmail filter**:
   - In Gmail, click the search box
   - Click the filter icon (≡) on the right
   - Fill in:
     - **From**: `noreply@booking.com`
     - **Has the words**: `New booking` OR `Booking modified` OR `Booking cancelled`
   - Click "Create filter"

2. **Configure the filter**:
   - Check: "Apply the label: Pickarooms"
   - Check: "Also apply filter to matching conversations" (applies to existing emails)
   - **IMPORTANT: Do NOT check "Mark as read"** - emails must stay unread for processing
   - Click "Create filter"

**Result**: All new Booking.com reservation emails will automatically get the "Pickarooms" label

---

### Step 3: Configure Environment Variable

#### **Local Development** (env.py):
```python
os.environ["GMAIL_LABEL_FILTER"] = "Pickarooms"
```

#### **Heroku Production**:
```bash
heroku config:set GMAIL_LABEL_FILTER="Pickarooms" --app pickarooms
```

**For labels with spaces:**
```bash
heroku config:set GMAIL_LABEL_FILTER="Booking/Process" --app pickarooms
```

---

### Step 4: Clean Up Old Emails (One-Time Cleanup)

Before deploying, you should:

1. **Delete the 34 pending enrichments** from Django admin (as you mentioned)
2. **Mark old unread Booking.com emails as read**:
   - In Gmail, search: `from:noreply@booking.com is:unread`
   - Select all old emails (NOT today's emails)
   - Click "Mark as read"
3. **Going forward, only apply the "Pickarooms" label to emails you want to process**

---

## Testing

### Test Locally (Without Pushing to Heroku):

1. **Create a test email** in Gmail:
   - Find a recent Booking.com email
   - Mark it as unread
   - Apply the "Pickarooms" label to it

2. **Check the logs**:
   - Start Celery: `celery -A pickarooms worker --loglevel=info --pool=solo`
   - Wait 2 minutes (email polling runs every 2 minutes)
   - Look for log message:
     ```
     Using Gmail label filter: 'Pickarooms' - Query: from:noreply@booking.com is:unread label:Pickarooms
     ```

3. **Verify it works**:
   - Check Django admin → Pending Enrichments
   - Should see a new pending enrichment for the test email

### Test Without Label Filter:

1. **Remove the environment variable**:
   ```bash
   # Local: Delete GMAIL_LABEL_FILTER from env.py
   # Heroku: heroku config:unset GMAIL_LABEL_FILTER --app pickarooms
   ```

2. **Check the logs**:
   - Look for log message:
     ```
     No Gmail label filter configured - processing all unread Booking.com emails
     ```

---

## Deployment Steps

### ⚠️ **BEFORE DEPLOYING TO HEROKU:**

1. **Delete pending enrichments** from Django admin (34 items)
2. **Mark old unread emails as read** in Gmail
3. **Set up Gmail label** and filter (Steps 1-2 above)
4. **Set Heroku environment variable**:
   ```bash
   heroku config:set GMAIL_LABEL_FILTER="Pickarooms" --app pickarooms
   ```

### **After Deployment:**

1. **Monitor Heroku logs**:
   ```bash
   heroku logs --tail --app pickarooms | grep -i "gmail\|label\|polling"
   ```

2. **Check for the label filter log message**:
   ```
   Using Gmail label filter: 'Pickarooms'
   ```

3. **Monitor Redis usage**:
   - Should drop dramatically (from 90% to <20%)
   - No more old emails processed

---

## Troubleshooting

### Issue: Still processing old emails

**Solution:**
- Check Heroku config: `heroku config --app pickarooms | grep GMAIL_LABEL_FILTER`
- Make sure old emails are marked as read in Gmail
- Check Gmail filter is applying the label correctly

### Issue: Not processing new emails

**Solution:**
- Make sure new emails have the "Pickarooms" label
- Make sure emails are unread
- Check Celery logs for errors

### Issue: Label with spaces not working

**Solution:**
- Use quotes: `heroku config:set GMAIL_LABEL_FILTER="Booking Process" --app pickarooms`
- Gmail will automatically add quotes in the search query

---

## Summary

**What You Need to Do:**

1. ✅ Create Gmail label "Pickarooms"
2. ✅ Create Gmail filter to auto-apply label to Booking.com emails
3. ✅ Set `GMAIL_LABEL_FILTER="Pickarooms"` on Heroku
4. ✅ Delete 34 pending enrichments from Django admin
5. ✅ Mark old unread Booking.com emails as read
6. ✅ Deploy to Heroku and monitor logs

**Result:**
- ✅ No more Redis overload
- ✅ Only new Booking.com emails are processed
- ✅ System is stable and efficient
