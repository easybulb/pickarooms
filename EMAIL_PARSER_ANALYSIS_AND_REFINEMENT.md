# Email Parser Analysis and Refinement Plan

## Current Setup Analysis

### 📧 **How Email Parsing Currently Works**

Your system uses **Gmail API** (not IMAP) to fetch Booking.com emails and enrich reservations. Here's the complete flow:

#### **Current Architecture:**

```
Gmail Inbox (noreply@booking.com emails)
    ↓
Gmail API Client (main/services/gmail_client.py)
    ↓
Email Parser (main/services/email_parser.py)
    ↓
Celery Tasks (main/tasks.py)
    ↓
Enrichment Service (main/services/enrichment_service.py)
    ↓
Database (Reservation, Guest, PendingEnrichment)
```

#### **Current Email Filtering:**

**Location in Code:** `main/services/gmail_client.py` → `get_unread_booking_emails()`

```python
# Current query (line 149-163):
query = 'from:noreply@booking.com is:unread'

# If GMAIL_LABEL_FILTER is set in settings:
if label_filter:
    query += f' label:{label_filter}'
    # Example: 'from:noreply@booking.com is:unread label:Pickarooms'
```

**What this means:**
- ✅ System already supports label filtering!
- ✅ Uses Gmail API (more reliable than IMAP)
- ✅ Currently pulls from main inbox (all unread Booking.com emails)
- ✅ Optional label filter available (via `GMAIL_LABEL_FILTER` setting)

---

## 🎯 Your Goal: Move Emails to Dedicated Label

You want to:
1. **Gmail Side:** Auto-filter booking emails into a specific label/folder
2. **App Side:** Configure email parser to ONLY look in that label

---

## ✅ Solution: It's Already Built! Just Needs Configuration

### **Step 1: Create Gmail Filter (5 minutes)**

#### **A. Go to Gmail Settings**
1. Open Gmail: https://mail.google.com
2. Click gear icon → "See all settings"
3. Go to "Filters and Blocked Addresses" tab
4. Click "Create a new filter"

#### **B. Configure Filter Criteria**

**From field:**
```
noreply@booking.com
```

**Subject field (optional but recommended):**
```
New booking! OR Modified booking! OR Cancelled booking!
```

**Why subject filter?** This ensures you ONLY capture reservation emails, not promotional/marketing emails from Booking.com.

#### **C. Create the Filter Action**

Click "Create filter" and check:
- ✅ **Apply the label:** Choose "New label..." → Name it `Bookings` (or `Pickarooms` or whatever you prefer)
- ✅ **Skip the Inbox (Archive it)** - This moves emails out of main inbox
- ⚠️ **DO NOT check "Mark as read"** - System needs unread emails to process
- ✅ **Also apply filter to # matching conversations** - This applies to existing emails (optional)

Click "Create filter"

**Result:** All future Booking.com reservation emails will:
- Automatically get the `Bookings` label
- Skip the main inbox (won't clutter it)
- Stay unread (so the system can process them)
- Be easily accessible under Gmail sidebar → Labels → Bookings

---

### **Step 2: Configure Email Parser (2 minutes)**

You need to set the `GMAIL_LABEL_FILTER` environment variable.

#### **Local Development (env.py):**

Add to your `env.py` file:
```python
os.environ["GMAIL_LABEL_FILTER"] = "Bookings"
```

#### **Heroku Production:**

```bash
heroku config:set GMAIL_LABEL_FILTER="Bookings" --app pickarooms
```

**If your label has spaces** (e.g., "Booking Confirmations"):
```bash
heroku config:set GMAIL_LABEL_FILTER="Booking Confirmations" --app pickarooms
```

**Verify it's set:**
```bash
heroku config --app pickarooms | grep GMAIL_LABEL_FILTER
```

---

### **Step 3: Clean Up Old Emails (One-Time - 5 minutes)**

Before deploying, you should handle old unread emails in your inbox:

#### **Option A: Mark Old Emails as Read (Recommended)**

1. In Gmail, search:
   ```
   from:noreply@booking.com is:unread older_than:7d
   ```
   (This finds old unread Booking.com emails from more than 7 days ago)

2. Select all → Click "Mark as read"

**Why?** Prevents system from processing ancient emails that are no longer relevant.

#### **Option B: Apply Label to Recent Emails Only**

1. In Gmail, search:
   ```
   from:noreply@booking.com is:unread newer_than:7d
   ```
   (Recent unread emails from last 7 days)

2. Select all → Apply label "Bookings"

---

### **Step 4: Test Before Deploying (10 minutes)**

#### **A. Test the Gmail Filter:**

1. Send yourself a test email with subject: "Booking.com - New booking! (1234567890, Monday, 15 January 2025)"
2. Check if it gets the "Bookings" label automatically
3. Check if it skipped the inbox

#### **B. Test the Email Parser Locally:**

1. Start Celery worker:
   ```bash
   celery -A pickarooms worker --loglevel=info --pool=solo
   ```

2. Wait for the email polling task to run (every 5 minutes), or trigger manually:
   ```python
   from main.tasks import poll_booking_com_emails
   poll_booking_com_emails.delay()
   ```

3. Check logs for:
   ```
   Using Gmail label filter: 'Bookings' - Query: from:noreply@booking.com is:unread label:Bookings
   ```

4. Verify it ONLY finds emails with the "Bookings" label

---

### **Step 5: Deploy to Production**

```bash
# Set environment variable
heroku config:set GMAIL_LABEL_FILTER="Bookings" --app pickarooms

# Deploy (if you made code changes)
git push heroku main

# Monitor logs
heroku logs --tail --app pickarooms | grep -i "gmail\|label"
```

**What to look for in logs:**
```
INFO: Using Gmail label filter: 'Bookings'
INFO: Found X unread Booking.com email(s)
```

---

## 📊 Benefits of This Approach

### **Gmail Side:**
- ✅ Main inbox stays clean (booking emails auto-archived)
- ✅ All booking emails in one dedicated label
- ✅ Easy to manually review/audit booking emails
- ✅ No accidental deletions (separate from main inbox)
- ✅ Gmail search works: `label:Bookings`

### **System Side:**
- ✅ Only processes relevant emails (no ancient unread emails)
- ✅ Reduces Redis/Celery load (fewer emails to scan)
- ✅ Faster email polling (smaller search scope)
- ✅ Bulletproof: Uses Gmail API labels (reliable)
- ✅ No code changes needed (already built!)

---

## 🔧 Advanced Configuration (Optional)

### **Multiple Labels for Different Platforms:**

If you want separate labels for Booking.com vs Airbnb:

1. Create two Gmail filters:
   - **Filter 1:** From `noreply@booking.com` → Label: `Bookings/Booking.com`
   - **Filter 2:** From `automated@airbnb.com` → Label: `Bookings/Airbnb`

2. Configure app to use nested label:
   ```python
   os.environ["GMAIL_LABEL_FILTER"] = "Bookings/Booking.com"
   ```

### **Nested Labels for Organization:**

Gmail supports nested labels (like folders):
```
Bookings/
├── Booking.com/
│   ├── New
│   ├── Modified
│   └── Cancelled
└── Airbnb/
```

**To use nested labels:**
```bash
heroku config:set GMAIL_LABEL_FILTER="Bookings/Booking.com/New" --app pickarooms
```

---

## 🛡️ Bulletproof Email Parsing (Current System)

Your system already uses the **bulletproof approach** via `get_recent_booking_emails()`:

**What makes it bulletproof:**
1. **Searches both read AND unread emails** (forgives human error)
2. **Limits to recent emails only** (last 30 days by default)
3. **Prevents matching ancient emails**
4. **Protects against duplicate booking references** (line 938-945 in tasks.py)

**Configuration in `main/enrichment_config.py`:**
```python
EMAIL_SEARCH_LOOKBACK_COUNT = 10  # Number of recent emails to search
EMAIL_SEARCH_LOOKBACK_DAYS = 30   # Only search emails from last N days
```

---

## 📝 Summary: What You Need to Do

### **Immediate Actions:**

1. ✅ **Create Gmail filter** (5 min)
   - From: `noreply@booking.com`
   - Subject: `New booking! OR Modified booking! OR Cancelled booking!`
   - Action: Apply label "Bookings" + Skip Inbox

2. ✅ **Set environment variable** (2 min)
   - Local: `os.environ["GMAIL_LABEL_FILTER"] = "Bookings"`
   - Heroku: `heroku config:set GMAIL_LABEL_FILTER="Bookings" --app pickarooms`

3. ✅ **Clean up old emails** (5 min)
   - Mark old unread Booking.com emails as read
   - OR apply "Bookings" label to recent emails only

4. ✅ **Test locally** (10 min)
   - Send test email
   - Run Celery worker
   - Check logs for label filter message

5. ✅ **Deploy to Heroku** (5 min)
   - Set config variable
   - Monitor logs

### **Total Time: ~30 minutes**

---

## 🚨 Troubleshooting

### **Issue: System still processing old emails**

**Solution:**
- Check `GMAIL_LABEL_FILTER` is set: `heroku config --app pickarooms`
- Make sure old emails are marked as read in Gmail
- Verify Gmail filter is applying label correctly

### **Issue: System not finding new emails**

**Solution:**
- Make sure new emails have the "Bookings" label
- Make sure emails are unread (system marks them as read after processing)
- Check Celery logs for errors: `heroku logs --tail --app pickarooms`

### **Issue: Label with spaces not working**

**Solution:**
- Use quotes in Heroku config: `heroku config:set GMAIL_LABEL_FILTER="Booking Process"`
- Gmail API automatically handles spaces in label names

### **Issue: Accidentally archived important emails**

**Solution:**
- Gmail filter only affects NEW emails (going forward)
- Old emails stay where they are
- You can manually move archived emails back to inbox (search `label:Bookings` → Move to Inbox)

---

## 📚 Related Files to Review

- **Gmail Client:** `main/services/gmail_client.py` (lines 120-200)
- **Email Parser:** `main/services/email_parser.py`
- **Celery Tasks:** `main/tasks.py` (search `poll_booking_com_emails`)
- **Settings:** `pickarooms/settings.py` (line with `GMAIL_LABEL_FILTER`)
- **Setup Guide:** `GMAIL_LABEL_SETUP.md` (already exists!)

---

## ✅ Conclusion

**Your system already supports exactly what you want!** You just need to:
1. Set up the Gmail filter (5 min)
2. Set the `GMAIL_LABEL_FILTER` environment variable (2 min)
3. Deploy (5 min)

**No code changes needed.** The label filtering feature was already built and documented in `GMAIL_LABEL_SETUP.md`.

Let me know if you'd like help with any of these steps!
