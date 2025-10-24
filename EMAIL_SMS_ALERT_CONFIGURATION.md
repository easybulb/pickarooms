# 📧📱 EMAIL & SMS ALERT CONFIGURATION

## 🔑 REQUIRED ENVIRONMENT VARIABLES

### 1. Gmail API Configuration (Email Polling)

**Local Development:**
```bash
# Not needed - uses gmail_token.json and gmail_credentials.json files
```

**Heroku Production:**
```bash
# Required for email polling to work
GMAIL_TOKEN_BASE64=<base64_encoded_token_json>
```

**How to generate GMAIL_TOKEN_BASE64:**
1. Run OAuth flow locally (first time setup):
   ```bash
   python manage.py shell -c "from main.services.gmail_client import GmailClient; GmailClient()"
   ```
2. This creates `gmail_token.json`
3. Encode it for Heroku:
   ```bash
   python -c "import base64; print(base64.b64encode(open('gmail_token.json', 'rb').read()).decode())"
   ```
4. Set on Heroku:
   ```bash
   heroku config:set GMAIL_TOKEN_BASE64=<output_from_step_3>
   ```

**Gmail Label Filter (Optional):**
```bash
GMAIL_LABEL_FILTER=Pickarooms  # Only process emails with this label
```

**Current Status:**
```bash
heroku config:get GMAIL_LABEL_FILTER
# Output: (empty) - processes ALL unread Booking.com emails
```

---

### 2. Email Sending Configuration (Alerts)

**Required for sending email alerts to admin:**
```bash
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password  # Gmail app password, NOT your real password
DEFAULT_FROM_EMAIL=your-email@gmail.com
```

**Current Local:**
- EMAIL_HOST_USER: placeholder@gmail.com ⚠️

**How to get Gmail App Password:**
1. Go to: https://myaccount.google.com/apppasswords
2. Create "Django App" password
3. Use that password (NOT your Gmail password)

---

### 3. SMS Configuration (Twilio)

**Required for SMS alerts:**
```bash
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+447366285523  # Your Twilio number
```

**Current Values:**
- TWILIO_PHONE_NUMBER: +447366285523 ✅
- ADMIN_PHONE_NUMBER: +447539029629 ✅

---

### 4. Admin Contact Information

**Hardcoded in:** `main/enrichment_config.py`

```python
ADMIN_PHONE = '+447539029629'  # Receives SMS alerts
ADMIN_EMAIL = 'easybulb@gmail.com'  # Receives email alerts
```

**To Change:**
1. Edit `main/enrichment_config.py`
2. Commit and push to Heroku

---

## 📨 EMAIL POLLING WORKFLOW

### How Gmail Integration Works:

1. **Every 5 minutes:** Celery runs `poll_booking_com_emails` task
2. **Gmail API Query:**
   ```
   from:noreply@booking.com is:unread [label:"Pickarooms"]
   ```
3. **Email Parsing:**
   - Extracts booking_reference (10 digits)
   - Extracts check_in_date
   - Identifies email_type (new/modification/cancellation)
4. **Cancellation Handling:** ✅ FIXED
   - Cancellation emails are now SKIPPED
   - Marked as read immediately
   - No PendingEnrichment created
5. **New/Modification Emails:**
   - Creates PendingEnrichment
   - Triggers iCal sync
   - Attempts to match reservation

---

## 🚨 ALERT WORKFLOW (When Enrichment Fails)

### Trigger Conditions:

Email enrichment sends alerts when:
- ✅ 5 matching attempts failed (over 15 minutes)
- ✅ Booking reference not found in iCal feed
- ✅ Collision detected (multiple bookings, same date)

### What Admin Receives:

#### SMS Alert (Single Booking):
```
PickARooms Alert:
Booking #6623478393 for 24 Oct 2025 not found in iCal.

Reply format:
1-3 = Room 1, 3 nights
2-2 = Room 2, 2 nights
3-1 = Room 3, 1 night
4-5 = Room 4, 5 nights
X = Cancel

Example: Reply "2-3" for Room 2, 3 nights
```

**Sent to:** `ADMIN_PHONE` (+447539029629)  
**From:** `TWILIO_PHONE_NUMBER` (+447366285523)

#### Email Alert (Single Booking):
```
Subject: Manual Assignment Needed - Booking #6623478393

Manual Assignment Needed

Booking Reference: 6623478393
Check-in Date: 24 October 2025
Platform: Booking.com
Email Received: 24 Oct 2025 10:15
Sync Attempts: 5 (failed)

REPLY WITH ROOM NUMBER AND NIGHTS:
Reply "1-3" - Room 1, 3 nights
Reply "2-2" - Room 2, 2 nights
Reply "3-1" - Room 3, 1 night
Reply "4-5" - Room 4, 5 nights
Reply "X" - Cancel assignment

Or log in to: https://pickarooms.com/admin-page/pending-enrichments/
```

**Sent to:** `ADMIN_EMAIL` (easybulb@gmail.com)  
**From:** `DEFAULT_FROM_EMAIL`

#### SMS Alert (Collision - Multiple Bookings):
```
PickARooms Alert:
3 Bookings for 24 Oct 2025:

A) #6623478393
B) #6558646178
C) #5555555555

Reply format:
A1-3 = Booking A, Room 1, 3 nights
B2-2 = Booking B, Room 2, 2 nights
X = Cancel all

Example: Reply "A2-3"
```

---

## 🔧 TROUBLESHOOTING

### Issue 1: No Emails Being Processed

**Check:**
```bash
heroku logs --tail | grep "poll_booking_com_emails"
```

**Expected Output:**
```
Polling Booking.com emails...
Found 2 new Booking.com email(s)
Created PendingEnrichment #123 for booking 6623478393
```

**Common Issues:**
- ❌ GMAIL_TOKEN_BASE64 not set → Gmail authentication fails
- ❌ Gmail token expired → Re-generate and update GMAIL_TOKEN_BASE64
- ❌ GMAIL_LABEL_FILTER set but label doesn't exist → No emails found

**Fix:**
```bash
# Check if token is set
heroku config:get GMAIL_TOKEN_BASE64

# Re-generate token locally
python manage.py shell -c "from main.services.gmail_client import GmailClient; GmailClient()"

# Encode and update Heroku
python -c "import base64; print(base64.b64encode(open('gmail_token.json', 'rb').read()).decode())"
heroku config:set GMAIL_TOKEN_BASE64=<output>
```

---

### Issue 2: No SMS Alerts Received

**Check Twilio Configuration:**
```bash
heroku config:get TWILIO_ACCOUNT_SID
heroku config:get TWILIO_AUTH_TOKEN
heroku config:get TWILIO_PHONE_NUMBER
```

**Check Logs:**
```bash
heroku logs --tail | grep "SMS alert"
```

**Expected Output:**
```
SMS alert sent for pending 123: SMxxxxxxxxxxxxxxx
```

**Common Issues:**
- ❌ Twilio credentials incorrect
- ❌ Twilio phone number not verified
- ❌ Admin phone number incorrect in enrichment_config.py

---

### Issue 3: No Email Alerts Received

**Check Email Configuration:**
```bash
heroku config:get EMAIL_HOST_USER
heroku config:get EMAIL_HOST_PASSWORD
```

**Check Logs:**
```bash
heroku logs --tail | grep "Email alert"
```

**Common Issues:**
- ❌ EMAIL_HOST_USER not set or wrong
- ❌ EMAIL_HOST_PASSWORD not a Gmail app password
- ❌ Gmail blocking "less secure apps" (use app password instead)

**Fix:**
```bash
heroku config:set EMAIL_HOST_USER=your-email@gmail.com
heroku config:set EMAIL_HOST_PASSWORD=your-gmail-app-password
heroku config:set DEFAULT_FROM_EMAIL=your-email@gmail.com
```

---

### Issue 4: Too Many Alerts (Spam)

**Check Label Filter:**
```bash
heroku config:get GMAIL_LABEL_FILTER
```

If empty, ALL old unread Booking.com emails will be processed!

**Fix:**
1. Create Gmail label: "Pickarooms"
2. Set filter to auto-apply label to new Booking.com emails
3. Update Heroku:
   ```bash
   heroku config:set GMAIL_LABEL_FILTER=Pickarooms
   ```

---

## ✅ VERIFICATION CHECKLIST

### Local Development:
- [ ] `gmail_token.json` exists and valid
- [ ] `gmail_credentials.json` exists (OAuth client ID)
- [ ] Celery worker running
- [ ] Celery beat running
- [ ] Redis running

### Heroku Production:
- [ ] `GMAIL_TOKEN_BASE64` configured
- [ ] `EMAIL_HOST_USER` configured
- [ ] `EMAIL_HOST_PASSWORD` configured
- [ ] `TWILIO_ACCOUNT_SID` configured
- [ ] `TWILIO_AUTH_TOKEN` configured
- [ ] `TWILIO_PHONE_NUMBER` configured
- [ ] `GMAIL_LABEL_FILTER` configured (optional but recommended)
- [ ] `ADMIN_PHONE` correct in enrichment_config.py
- [ ] `ADMIN_EMAIL` correct in enrichment_config.py

---

## 📊 CURRENT CONFIGURATION STATUS

### Local:
```
EMAIL_HOST_USER: placeholder@gmail.com ⚠️ (needs updating)
GMAIL_LABEL_FILTER: (empty) ✅
TWILIO_PHONE: +447366285523 ✅
ADMIN_PHONE: +447539029629 ✅
```

### Heroku (Unknown - Need to Check):
```bash
# Run these to check:
heroku config:get GMAIL_TOKEN_BASE64
heroku config:get EMAIL_HOST_USER
heroku config:get EMAIL_HOST_PASSWORD
heroku config:get GMAIL_LABEL_FILTER
```

---

## 🎯 NEXT STEPS

1. **Verify Gmail Token on Heroku:**
   ```bash
   heroku config:get GMAIL_TOKEN_BASE64
   ```
   If empty or expired → Regenerate and set

2. **Verify Email Sending Works:**
   ```bash
   heroku run python manage.py shell -c "from django.core.mail import send_mail; send_mail('Test', 'Test email', 'noreply@pickarooms.com', ['easybulb@gmail.com'])"
   ```

3. **Test SMS Sending:**
   ```bash
   heroku run python manage.py shell -c "from twilio.rest import Client; from django.conf import settings; client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN); client.messages.create(to='+447539029629', from_=settings.TWILIO_PHONE_NUMBER, body='Test SMS from Heroku')"
   ```

4. **Monitor Email Polling:**
   ```bash
   heroku logs --tail | grep "poll_booking_com_emails"
   ```
