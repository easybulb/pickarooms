# Visual Testing Guide - GDPR Updates

## 🎯 Quick Test Path

### **1. Home Page** (`http://localhost:8000/`)

**Expected:**
```
┌─────────────────────────────────────────────┐
│           🏠 Welcome Page                    │
├─────────────────────────────────────────────┤
│                                             │
│  Welcome, Your Stay Starts Here!           │
│                                             │
│  Ready to check in? Click below to start   │
│  your seamless check-in experience.        │
│                                             │
│     ┌───────────────────────────┐          │
│     │ 🔑 Check In Now      →    │          │
│     └───────────────────────────┘          │
│           (purple gradient)                 │
│                                             │
│  Have your Booking.com confirmation        │
│  number ready                               │
│                                             │
│  [How to Use] | [Contact Us]               │
└─────────────────────────────────────────────┘
```

**What to Check:**
- ✅ Large purple gradient button
- ✅ Button has hover effect (lifts up)
- ✅ Arrow (→) slides right on hover
- ✅ No form fields visible
- ✅ FAQ section below (scroll down)
- ✅ Image slider present
- ✅ Button links to `/checkin/`

---

### **2. Step 1** (`http://localhost:8000/checkin/`)

**Expected:**
```
Progress: [1●] ─ [2○] ─ [3○] ─ [4○]

Check-In

Enter your booking reference to begin check-in.

┌─────────────────────────┐
│ [10-digit number]       │
└─────────────────────────┘
10-digit number from your Booking.com confirmation

[Continue →]

[How to Use] | [Contact Us]
```

**What to Check:**
- ✅ Step 1 is active (blue glow)
- ✅ Input accepts only numbers
- ✅ Green border when 10 digits entered
- ✅ Red border if less than 10 digits
- ✅ Button says "Continue →"

---

### **3. Step 2** (`/checkin/details/`)

**Expected:**
```
Progress: [1✓] ─ [2●] ─ [3○] ─ [4○]

Your Details

Please provide your contact information to complete check-in.

┌─────────────────────────────────────────────┐
│ 🔒 We use your contact details to provide  │
│    your access code and manage your stay.  │
│    Your details are stored securely and    │
│    can be deleted at any time by           │
│    contacting us.                           │
└─────────────────────────────────────────────┘
      (Blue-tinted privacy notice box)

Full Name *
┌─────────────────────────┐
│ [John Smith]            │
└─────────────────────────┘

Phone Number *
[🇬🇧 UK (+44) ▼] [7123456789]

Email Address (optional)
┌─────────────────────────┐
│ [john@example.com]      │
└─────────────────────────┘

[Continue →]

← Back to Step 1

📄 Read our Privacy Policy
```

**What to Check:**
- ✅ Blue-tinted privacy notice box at top
- ✅ Lock icon (🔒) visible
- ✅ Text is readable and reassuring
- ✅ Country code dropdown works
- ✅ Phone input removes leading 0
- ✅ Privacy Policy link at bottom
- ✅ Link opens in new tab
- ✅ Form submits when all required fields filled

---

### **4. Step 3** (`/checkin/parking/`)

**Expected:**
```
Progress: [1✓] ─ [2✓] ─ [3●] ─ [4○]

Parking Information

○ Yes, I have a car
  ┌─────────────────────────┐
  │ [AB12 CDE]              │
  └─────────────────────────┘

○ No car

[Continue →]

← Back
```

**What to Check:**
- ✅ Step 3 is active
- ✅ Radio buttons work
- ✅ Car registration field appears when "Yes" selected
- ✅ Car registration formats to uppercase
- ✅ Can proceed without car
- ✅ Background task is running (check Celery logs)

---

### **5. Step 4** (`/checkin/confirm/`)

**Expected:**
```
Progress: [1✓] ─ [2✓] ─ [3✓] ─ [4●]

✅ Almost There!

Please confirm your details before completing check-in.

┌─────────────────────────────────────────────┐
│         Your Booking Summary                │
├─────────────────────────────────────────────┤
│ Name:              John Smith               │
│ Phone:             +447123456789            │
│ Email:             john@example.com         │
│ Room:              Room 1                   │
│ Check-In:          25 Oct 2025              │
│ Check-Out:         27 Oct 2025              │
│ 🚗 Car Registration: AB12 CDE               │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│ ✅ Your access PIN is ready! Please accept │
│    the privacy terms below to continue.     │
└─────────────────────────────────────────────┘
      (Green success box)

┌─────────────────────────────────────────────┐
│ 📋 Data Privacy & Consent                   │
│                                             │
│ We use your contact details to:            │
│ • Provide your room access PIN             │
│ • Send check-in instructions               │
│ • Manage your stay and support requests    │
│                                             │
│ Your data is stored securely and can be    │
│ deleted at any time by contacting us.      │
│                                             │
│ ☑ I agree to the Privacy Policy and        │
│   Terms of Service                          │
└─────────────────────────────────────────────┘
      (Gold-tinted GDPR box)

[✅ Confirm & Complete Check-In]
     (disabled until checkbox checked)

← Back
```

**What to Check:**
- ✅ All steps show checkmarks
- ✅ Step 4 is active
- ✅ Booking summary displays correctly
- ✅ PIN status box shows green "ready" message
- ✅ Gold-tinted GDPR consent box appears
- ✅ Bullet points are visible
- ✅ Checkbox is unchecked by default
- ✅ Privacy Policy link works (new tab)
- ✅ Terms of Service link works (new tab)
- ✅ Submit button is disabled initially
- ✅ Submit button enables when checkbox checked
- ✅ Submit button stays disabled if checkbox unchecked
- ✅ Form submits successfully when all conditions met

---

## 🎨 Visual Elements to Verify

### **Colors:**

| Element | Color | Visual |
|---------|-------|--------|
| Home button | Purple gradient (`#667eea` → `#764ba2`) | 🟣 |
| Step 1 active | Blue (`#667eea`) | 🔵 |
| Completed steps | Green (`#28a745`) | 🟢 |
| Privacy notice (Step 2) | Blue tint (`rgba(102, 126, 234, 0.15)`) | 🔵 |
| PIN ready status | Green (`#28a745`) | 🟢 |
| PIN loading status | Blue (`#667eea`) | 🔵 |
| PIN failed status | Red (`#dc3545`) | 🔴 |
| GDPR box (Step 4) | Gold tint (`rgba(255, 215, 0, 0.08)`) | 🟡 |
| Privacy links | Gold (`#FFD700`) | 🟡 |

### **Icons:**

| Icon | Meaning | Location |
|------|---------|----------|
| 🔑 | Check-in access | Home button |
| 🔒 | Privacy/security | Step 2 privacy notice |
| 📋 | Data consent | Step 4 GDPR box |
| ✅ | Success/ready | PIN status, submit button |
| ⏳ | Loading/waiting | PIN generating status |
| ❌ | Error/failed | PIN generation failed |
| ✓ | Step completed | Progress bar checkmarks |

---

## 📱 Mobile Testing

Test on:
- Chrome DevTools (iPhone SE, iPhone 12, iPad)
- Actual mobile device if available

**Expected on Mobile:**
- ✅ All text is readable (minimum 12px)
- ✅ Buttons are easily tappable (min 44x44px)
- ✅ GDPR box text doesn't overflow
- ✅ Checkbox is easy to tap (18x18px)
- ✅ Links are easily tappable
- ✅ Progress bar scales appropriately
- ✅ No horizontal scrolling

---

## 🐛 Common Issues to Watch For

### **Issue 1: Button Not Enabling**
**Symptoms:** Step 4 submit button stays disabled even after checking checkbox

**Debug:**
1. Open browser console (F12)
2. Check for JavaScript errors
3. Verify PIN status: `/checkin/pin-status/`
4. Check if `pinReady` variable is `true`

**Solution:**
- Ensure Celery worker is running
- Check background task completed successfully
- Verify session has PIN data

---

### **Issue 2: Privacy Box Not Showing**
**Symptoms:** Blue box on Step 2 or gold box on Step 4 is missing

**Debug:**
1. View page source
2. Look for `<div class="privacy-notice">` or `<div class="gdpr-consent-box">`
3. Check CSS is loading

**Solution:**
- Hard refresh (Ctrl+F5)
- Clear browser cache
- Check template rendering

---

### **Issue 3: Checkbox State Not Saved**
**Symptoms:** Checkbox unchecks on page refresh or back button

**Expected Behavior:**
- Checkbox should **NOT** persist (GDPR requirement)
- User must actively consent each time
- This is correct behavior!

---

## ✅ Final Checklist

Before considering complete:

- [ ] Home page shows check-in button (no form)
- [ ] Home button links to `/checkin/`
- [ ] Step 1 shows progress bar
- [ ] Step 2 shows blue privacy notice box
- [ ] Step 2 privacy policy link works
- [ ] Step 3 shows parking form
- [ ] Step 4 shows booking summary
- [ ] Step 4 shows PIN ready status
- [ ] Step 4 shows gold GDPR consent box
- [ ] Step 4 checkbox is unchecked by default
- [ ] Step 4 button disabled until conditions met
- [ ] Step 4 privacy policy link works (new tab)
- [ ] Step 4 terms of service link works (new tab)
- [ ] Step 4 form submits when checkbox checked
- [ ] Mobile: All elements readable and tappable
- [ ] No console errors in browser
- [ ] Celery task completes successfully

---

## 🎬 Full Flow Demo Script

**Copy-paste this for quick testing:**

1. Go to `http://localhost:8000/`
2. Click "Check In Now" button
3. Enter booking ref: `5735307998` (or your test booking)
4. Click "Continue"
5. Enter name: `Test Guest`
6. Enter phone: `7539029629`
7. Enter email: `test@example.com`
8. Click "Continue"
9. Select "Yes, I have a car"
10. Enter car reg: `AB12 CDE`
11. Click "Continue"
12. Wait for green "PIN ready" message
13. Review booking summary
14. Check the GDPR consent checkbox
15. Verify button is now enabled
16. Click "Confirm & Complete Check-In"
17. Should redirect to room detail page instantly

**Expected Time:** 2-3 minutes (including PIN generation)

---

**Happy Testing!** 🚀
