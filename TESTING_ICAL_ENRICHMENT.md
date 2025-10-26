# iCal-Driven Enrichment Testing Guide

## ✅ Implementation Complete - Ready for Testing

### **What Was Changed**

**Phase 1: Core Flow Reversal**
- ✅ iCal sync now triggers enrichment workflow for new bookings
- ✅ Collision detection (immediate SMS when multiple bookings same day)
- ✅ Email search (4 attempts over 10 min)
- ✅ SMS alerts for collision and email not found

**Phase 2: SMS Handler Enhancement**
- ✅ Single ref format: `6588202211` (email not found case)
- ✅ Collision format: `6588202211: 1-2` (single booking)
- ✅ Multi-line collision support
- ✅ CHECK command: `check 6588202211` or `6588202211 check`
- ✅ CORRECT command: `6588202211: 2-2 correct`
- ✅ CANCEL command: `cancel 6588202211` or `6588202211 cancel`
- ✅ GUIDE command: `guide` or `help`

**Phase 3: Model Refactoring**
- ✅ Updated EnrichmentLog actions for iCal-driven flow
- ✅ Database migration created

**Phase 4: Enhanced Logging**
- ✅ All enrichment actions logged
- ✅ Old email-driven tasks marked as deprecated

---

## 📋 Testing Scenarios

### **Scenario 1: Single Booking - Email Found Immediately**

**Setup:**
1. Booking.com email arrives: "New booking! (6588202211, Saturday, 20 December 2025)"
2. Email is unread in Gmail

**Expected Flow:**
1. iCal sync runs (every 15 min)
2. Detects new booking → creates Reservation (unenriched)
3. Triggers `trigger_enrichment_workflow`
4. No collision detected (single booking)
5. Starts email search (attempt 1 - immediate)
6. **Email found!** → Enriches reservation with booking_ref
7. Marks email as read
8. **Result**: Reservation enriched automatically ✅

**How to Test:**
```bash
# Manually trigger iCal sync
python manage.py shell
>>> from main.tasks import poll_all_ical_feeds
>>> poll_all_ical_feeds.delay()
```

**Expected Log Entries:**
- `ical_new_booking`
- `email_search_started`
- `email_found_matched`

---

### **Scenario 2: Single Booking - Email Not Found (4 Attempts)**

**Setup:**
1. iCal shows new booking but email was already read/deleted

**Expected Flow:**
1. iCal sync creates Reservation (unenriched)
2. Email search attempt 1 (immediate) → Not found
3. Email search attempt 2 (2 min later) → Not found
4. Email search attempt 3 (5 min later) → Not found
5. Email search attempt 4 (10 min later) → Not found
6. **SMS alert sent:**
   ```
   PickARooms Alert

   New booking detected (iCal)
   Email not found after 10 min

   Room: Room 2
   Check-in: 20 Dec 2025
   Check-out: 22 Dec 2025 (2 nights)

   Reply with booking ref only:

   Example: 6588202211
   ```

**Admin Reply:**
```
6588202211
```

**Expected Result:**
- Reservation enriched with booking_ref
- Confirmation SMS sent:
  ```
  ✅ ENRICHMENT COMPLETE

  Booking: #6588202211
  Room: Room 2
  Check-in: 20 Dec 2025
  Check-out: 22 Dec 2025 (2 nights)

  Reservation ready for check-in.
  ```

**Expected Log Entries:**
- `ical_new_booking`
- `email_search_started`
- `email_not_found_alerted`
- `manual_enrichment_sms`

---

### **Scenario 3: Collision - Multiple Bookings Same Day**

**Setup:**
1. iCal shows 2+ bookings with same check_in_date

**Expected Flow:**
1. iCal sync creates first Reservation
2. iCal sync creates second Reservation
3. Triggers `trigger_enrichment_workflow` for second booking
4. **Collision detected!** (2+ bookings for same date)
5. **Immediate SMS alert:**
   ```
   PickARooms Alert

   Multiple bookings detected:
   Check-in: 20 Dec 2025

   Room 1 (2 nights)
   Room 3 (1 night)

   Reply with booking ref for EACH room:

   Format: REF: ROOM-NIGHTS

   Example:
   6588202211: 1-2
   6717790453: 3-1

   (One per line)
   ```

**Admin Reply (Multi-line):**
```
6588202211: 1-2
6717790453: 3-1
```

**Expected Result:**
- Both reservations enriched
- Confirmation SMS sent:
  ```
  ✅ ENRICHMENT COMPLETE (2 bookings)

  ✅ #6588202211
     Room 1, 2n
     20 Dec - 22 Dec

  ✅ #6717790453
     Room 3, 1n
     20 Dec - 21 Dec

  All reservations ready for check-in.
  ```

**Expected Log Entries:**
- `collision_detected`
- `multi_enrichment_sms` (x2)

---

### **Scenario 4: CHECK Command**

**Admin SMS:**
```
check 6588202211
```
OR
```
6588202211 check
```

**Expected Response (if enriched):**
```
Reservation #6588202211

Status: Confirmed ✅
Room: Room 2
Check-in: 20 Dec 2025 (2:00 PM)
Check-out: 22 Dec 2025 (11:00 AM)
Guest: John Smith
Phone: +447539029629
Email: john@example.com
PIN: 1234 (active)

Source: Booking.com iCal
```

**Expected Response (if unenriched):**
```
Reservation #6588202211

Status: Pending Enrichment ⏳
Room: Room 2
Check-in: 20 Dec 2025
Check-out: 22 Dec 2025 (2 nights)

Awaiting booking ref from email.

To enrich manually, reply:
6588202211
```

**Expected Log Entry:**
- `check_command_received`

---

### **Scenario 5: CORRECT Command**

**Setup:**
1. Previously enriched wrong room/nights

**Admin SMS:**
```
6588202211: 2-2 correct
```

**Expected Result:**
- Old reservation deleted
- New reservation created with corrected details
- Confirmation SMS:
  ```
  ✅ CORRECTION APPLIED

  Previous: Room 1, 3 nights
  Updated: Room 2, 2 nights

  Booking: #6588202211
  Room: Room 2 (corrected)
  Check-in: 20 Dec 2025
  Check-out: 22 Dec 2025 (2 nights)

  Old reservation deleted, new one created.
  ```

**Expected Log Entry:**
- `correction_applied`

---

### **Scenario 6: CANCEL Command**

**Admin SMS:**
```
cancel 6588202211
```
OR
```
6588202211 cancel
```

**Expected Result:**
- Reservation marked as cancelled
- If enriched, guest deleted (triggers PIN deletion + cancellation email)
- Confirmation SMS:
  ```
  ✅ CANCELLED

  Booking: #6588202211
  Room: Room 2
  Check-in: 20 Dec 2025

  Reservation deleted.
  ```

**Expected Log Entry:**
- `cancel_command_received`

---

### **Scenario 7: GUIDE Command**

**Admin SMS:**
```
guide
```
OR
```
help
```

**Expected Response:**
```
📘 PickARooms SMS Guide

━━━━━━━━━━━━━━━━━━━
COLLISION (Multiple Bookings)
━━━━━━━━━━━━━━━━━━━
Format: REF: ROOM-NIGHTS
(One per line)

Example:
6588202211: 1-2
6717790453: 3-1

━━━━━━━━━━━━━━━━━━━
EMAIL NOT FOUND
━━━━━━━━━━━━━━━━━━━
Reply with ref only:

Example:
6588202211

━━━━━━━━━━━━━━━━━━━
CHECK RESERVATION
━━━━━━━━━━━━━━━━━━━
check 6588202211
OR
6588202211 check

━━━━━━━━━━━━━━━━━━━
CORRECT MISTAKE
━━━━━━━━━━━━━━━━━━━
6588202211: 2-2 correct

━━━━━━━━━━━━━━━━━━━
CANCEL RESERVATION
━━━━━━━━━━━━━━━━━━━
6588202211 cancel
OR
cancel 6588202211

━━━━━━━━━━━━━━━━━━━
HELP
━━━━━━━━━━━━━━━━━━━
guide or help

Dashboard:
pickarooms.com/admin
```

**Expected Log Entry:**
- `guide_command_received`

---

## 🔧 Pre-Testing Checklist

### **1. Database Migration**
```bash
python manage.py migrate
```

### **2. Celery Workers Running**
```bash
# Terminal 1: Celery worker
celery -A pickarooms worker -l info --pool=solo

# Terminal 2: Celery beat (scheduled tasks)
celery -A pickarooms beat -l info
```

### **3. Redis Running**
```bash
# Check if Redis is running
redis-cli ping
# Should return: PONG
```

### **4. Environment Variables**
- ✅ `TWILIO_ACCOUNT_SID`
- ✅ `TWILIO_AUTH_TOKEN`
- ✅ `TWILIO_PHONE_NUMBER`
- ✅ `ADMIN_PHONE_NUMBER` (in enrichment_config.py)
- ✅ Gmail API credentials configured

### **5. Twilio Webhook**
- ✅ Twilio phone number webhook set to: `https://pickarooms.com/webhooks/twilio/sms/`

---

## 🐛 Debugging Tips

### **Check Celery Logs**
```bash
# Watch celery worker output for task execution
tail -f celery.log
```

### **Check EnrichmentLog**
```python
python manage.py shell
>>> from main.models import EnrichmentLog
>>> EnrichmentLog.objects.order_by('-timestamp')[:10]
```

### **Check Unenriched Reservations**
```python
>>> from main.models import Reservation
>>> Reservation.objects.filter(guest__isnull=True, status='confirmed')
```

### **Manually Trigger iCal Sync**
```python
>>> from main.tasks import poll_all_ical_feeds
>>> poll_all_ical_feeds.delay()
```

### **Manually Trigger Email Search**
```python
>>> from main.tasks import search_email_for_reservation
>>> search_email_for_reservation.delay(reservation_id=1, attempt=1)
```

---

## ⚠️ Known Limitations

1. **Email search requires Gmail API** - Ensure `gmail_token.json` is valid
2. **Celery must be running** - Background tasks won't execute otherwise
3. **Redis must be running** - Task queue won't work
4. **Twilio webhook must be configured** - SMS replies won't be received

---

## 📊 Success Metrics

After testing, verify:
- ✅ iCal sync creates unenriched reservations
- ✅ Email search finds and enriches automatically
- ✅ Collision detection works (immediate SMS)
- ✅ Email not found triggers SMS after 10 min
- ✅ All SMS commands work (CHECK, CORRECT, CANCEL, GUIDE)
- ✅ EnrichmentLog tracks all actions
- ✅ Old email-driven tasks don't interfere

---

## 🚀 Ready to Test!

Start with **Scenario 1** (simplest) and work up to **Scenario 3** (collision).

**Any issues?** Check logs and debug using the tips above.
