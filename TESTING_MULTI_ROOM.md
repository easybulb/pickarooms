# MULTI-ROOM BOOKING - TESTING GUIDE

## 🧪 LOCAL TESTING (Before Deployment)

### Prerequisites
```bash
python manage.py migrate  # Ensure migration 0033 is applied
python manage.py runserver
```

---

## TEST 1: Guest Web Check-In (Multi-Room) ⭐ PRIORITY

### Setup
1. Go to Django Admin → Reservations
2. Create Reservation 1:
   - Booking Reference: `TEST123456`
   - Guest Name: `John Smith`
   - Room: `Room 1`
   - Check-in: Tomorrow's date
   - Check-out: 2 days from now
   - Status: Confirmed

3. Create Reservation 2:
   - Booking Reference: `TEST123456` (SAME as above)
   - Guest Name: `John Smith`
   - Room: `Room 2` (DIFFERENT room)
   - Check-in: Tomorrow's date (SAME)
   - Check-out: 2 days from now
   - Status: Confirmed

### Test Steps
1. Open browser (incognito mode)
2. Go to `http://localhost:8000/`
3. Click "Check In Now"
4. Enter booking reference: `TEST123456`
5. Enter name: `John Smith`
6. Enter email: `test@example.com`
7. Enter phone: `+447123456789`
8. Click Continue

### Expected Results
✅ System creates 1 Guest  
✅ System links BOTH Reservation 1 and Reservation 2 to this Guest  
✅ System generates PIN (e.g., `1234`)  
✅ Redirects to room_detail page  
✅ Page shows multi-room section: "🏠 Your Rooms"  
✅ Both Room 1 and Room 2 listed  
✅ Same PIN shown for all rooms  
✅ Message: "The same PIN opens the front door and all your room doors"

### Verify in Admin
1. Go to Django Admin → Guests
2. Find guest with booking ref `TEST123456`
3. Click to view details
4. Check: `front_door_pin` has a value (e.g., `1234`)
5. Go to Django Admin → Reservations
6. Find both reservations with ref `TEST123456`
7. Verify: BOTH have `guest` linked to the SAME Guest ID

### Check Logs
```bash
# Look for these log messages:
grep "Multi-room booking detected" logs/django.log
grep "Linked reservation.*to guest" logs/django.log
grep "Generated room PIN.*for Room" logs/django.log
```

---

## TEST 2: Admin Manual Check-In (New Guest, Multi-Room)

### Setup
Same as Test 1 (2 reservations, same booking ref, different rooms)

### Test Steps
1. Login to admin dashboard: `http://localhost:8000/admin-page/`
2. Find the "Today's Guests" section
3. Locate Reservation 1 (Room 1) - should show "Pending Check-In"
4. Click "Check In" button
5. Fill form:
   - Full Name: `Jane Doe`
   - Phone: `+447987654321`
   - Email: `jane@example.com`
6. Click "Check In Guest & Generate PIN"

### Expected Results
✅ Success message: "Guest Jane Doe checked in successfully! PIN (for 2 rooms): 1234"  
✅ Both Room 1 and Room 2 now show as enriched in dashboard  
✅ Both linked to same Guest  
✅ Same PIN for all rooms

### Verify
1. Go to All Reservations
2. Find both reservations with ref `TEST123456`
3. Both should show same guest name `Jane Doe`
4. Both should show same PIN

---

## TEST 3: Admin Manual Check-In (Existing Guest) ⭐ CRITICAL

### Setup
1. Keep the guest from Test 2 (`Jane Doe` with Room 1 checked in)
2. Create new Reservation 3:
   - Booking Reference: `TEST123456` (SAME as Jane's)
   - Guest Name: `Jane Doe`
   - Room: `Room 3` (NEW room)
   - Check-in: Tomorrow
   - Check-out: 2 days from now
   - Status: Confirmed

### Test Steps
1. Go to admin dashboard
2. Find Reservation 3 (Room 3) - shows "Pending Check-In"
3. Click "Check In"
4. Fill form:
   - Full Name: `Jane Doe`
   - Phone: `+447987654321`
   - Email: `jane@example.com`
5. Click "Check In Guest & Generate PIN"

### Expected Results
✅ Success message: "Linked to existing guest Jane Doe. Room Room 3 added with PIN 1234."  
✅ NO new guest created (uses existing)  
✅ Room 3 linked to existing Jane Doe guest  
✅ PIN generated for Room 3 lock (same PIN as other rooms)  
✅ No database error!

### Verify
1. Django Admin → Guests
2. Search for `Jane Doe`
3. Should find only ONE guest (not multiple)
4. Django Admin → Reservations
5. Filter by booking ref `TEST123456`
6. Should see 3 reservations ALL linked to same Guest

### Check Guest Portal
1. As Jane, open room_detail page
2. Should now see 3 rooms:
   - Room 1
   - Room 2
   - Room 3
3. All with same PIN

---

## TEST 4: Single Room Booking (Backward Compatibility)

### Setup
1. Create Reservation:
   - Booking Reference: `SINGLE999`
   - Guest Name: `Bob Single`
   - Room: `Room 1`
   - Check-in: Tomorrow
   - Status: Confirmed

### Test Steps
1. Guest web check-in with ref `SINGLE999`
2. Enter details

### Expected Results
✅ Guest created normally  
✅ PIN generated  
✅ room_detail page does NOT show multi-room section  
✅ Only 1 room shown  
✅ Everything works as before

---

## TEST 5: PIN Functionality (If you have TTLock access)

### Test Steps
1. After completing Test 1, 2, or 3
2. Note the PIN generated (e.g., `1234`)
3. Go to front door
4. Enter PIN on keypad: `1234#`
5. Try door → Should unlock
6. Go to Room 1
7. Enter same PIN: `1234#`
8. Try door → Should unlock
9. Go to Room 2
10. Enter same PIN: `1234#`
11. Try door → Should unlock

### Expected Results
✅ Same PIN works on ALL locks  
✅ Front door unlocks  
✅ All room doors unlock

---

## TEST 6: Remote Unlock (Multi-Room)

### Test Steps
1. After completing Test 1 (2 rooms checked in)
2. Open room_detail page as guest
3. Click "Unlock Now" button
4. Click "Unlock Front Door" → Should work
5. Click "Unlock Room Door" → Should unlock assigned room

### Expected Results
✅ Remote unlock works for all doors  
✅ No errors in browser console  
✅ Success message shown

---

## TEST 7: Error Handling

### Test A: Room without TTLock
1. Create 2 reservations, same booking ref
2. Assign one to a room WITH NO TTLock configured
3. Try to check in

**Expected:** Error message, rollback, no partial guest creation

### Test B: TTLock API Failure
1. Temporarily break TTLock connection (wrong credentials)
2. Try multi-room check-in

**Expected:** Error message, rollback, helpful error shown

---

## 🔍 DEBUGGING CHECKLIST

If something doesn't work:

### Check Database
```python
python manage.py shell
from main.models import Guest, Reservation

# Find guest
g = Guest.objects.get(reservation_number='TEST123456')
print(f"Guest: {g.full_name}, PIN: {g.front_door_pin}")

# Check reservations
reservations = g.reservations.all()
print(f"Rooms: {[r.room.name for r in reservations]}")
```

### Check Logs
```bash
# Django logs
tail -f logs/django.log | grep -i "multi-room"

# Celery logs (if applicable)
tail -f logs/celery.log
```

### Check View Response
Look in Django admin logs or console for:
- `Multi-room booking detected: X rooms linked`
- `Generated room PIN {pin} for {room_name}`
- `Linked reservation {id} to guest {guest_id}`

### Common Issues

**Issue:** "Only 1 room shown on room_detail page"
- Check: Is `is_multiroom` being passed to template?
- Check: Does `guest.reservations.count()` return > 1?

**Issue:** "Database error: duplicate key"
- Check: Did migration 0033 run? `python manage.py showmigrations main`

**Issue:** "PIN doesn't work on second room"
- Check: Was PIN generated for that room's lock?
- Check logs for `Generated room PIN` for that specific room

---

## ✅ SUCCESS CRITERIA

Before deploying to production, verify:

- [ ] Test 1 passes (guest web check-in, multi-room)
- [ ] Test 2 passes (admin manual check-in, new guest)
- [ ] Test 3 passes (admin manual check-in, existing guest) ⭐ CRITICAL
- [ ] Test 4 passes (single room backward compatibility)
- [ ] No database errors
- [ ] Logs show proper multi-room detection
- [ ] room_detail page displays correctly
- [ ] Same PIN works on all doors (if TTLock available)

---

## 📊 TEST MATRIX

| Scenario | Booking Ref | Rooms | Expected Behavior | Status |
|----------|-------------|-------|-------------------|--------|
| Guest web check-in | SAME | 2 | 1 guest, 2 linked, multi-room shown | ⬜ |
| Admin new guest | SAME | 2 | 1 guest, 2 linked, 2 PINs | ⬜ |
| Admin existing guest | SAME | 3 | Link to existing, add 3rd room PIN | ⬜ |
| Single room | UNIQUE | 1 | Normal flow, no multi-room section | ⬜ |
| Different refs | DIFFERENT | 2 | 2 separate guests | ⬜ |

---

## 🚀 AFTER TESTING LOCALLY

Once all tests pass:

1. Commit changes
```bash
git add .
git commit -m "Multi-room booking implementation - tested and verified"
```

2. Deploy to production
```bash
git push heroku main
heroku run python manage.py migrate -a pickarooms
```

3. Run same tests on production with real data
4. Monitor logs for 24 hours
```bash
heroku logs --tail -a pickarooms | grep -i "multi-room"
```

---

**Ready to test? Start with TEST 1 and TEST 3 - these are the most critical!** 🚀
