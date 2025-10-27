# MULTI-ROOM BOOKING - IMMEDIATE NEXT STEPS

## ✅ PHASE 1: COMPLETE
- Database schema fixed (OneToOneField → ForeignKey)
- Migration created and run locally
- Guest model methods updated
- **READY FOR DEPLOYMENT**

---

## 🚧 PHASE 2: CODE LOGIC UPDATES (REQUIRED NOW)

Based on MULTI_ROOM_FIX_NEEDED.txt, here's what MUST be implemented:

### Critical Files to Modify:

#### 1. `main/views.py` - `enrich_reservation()` (line ~392)
**Current behavior:** Creates 1 Guest, links to 1 Reservation
**Required behavior:** 
- Find ALL reservations with same booking_reference
- Create 1 Guest
- Link ALL reservations to that guest
- Generate PINs for ALL room doors

#### 2. `main/views.py` - `manual_checkin_reservation()` (line ~1746) 
**Current behavior:** Creates new guest regardless
**Required behavior:**
- Check if Guest with booking_reference already exists
- IF EXISTS → Link reservation to existing guest, generate PIN for this room only
- IF NOT EXISTS → Create new guest, find other reservations with same booking_ref, link all, generate PINs for all

#### 3. `main/templates/main/room_detail.html`
**Current behavior:** Shows 1 room
**Required behavior:**
- Show ALL rooms guest has access to
- List all room PINs (front door + each room)
- Allow unlocking each room individually

#### 4. `main/views.py` - `room_detail()` function
**Required changes:**
- Get all reservations for guest: `guest.reservations.all()`
- Build list of rooms
- Pass to template with multi-room flag

---

## 📝 IMPLEMENTATION PRIORITY

1. **DEPLOY Phase 1 FIRST** (database schema change)
   ```bash
   git add .
   git commit -m "Fix multi-room bookings - Change Reservation.guest from OneToOneField to ForeignKey"
   git push origin main
   git push heroku main
   heroku run python manage.py migrate -a pickarooms
   ```

2. **Then implement Phase 2** (logic changes)
   - Start with `manual_checkin_reservation` (most urgent - admin use)
   - Then `enrich_reservation` (guest web check-in)
   - Then `room_detail` page updates (user experience)

---

## ⚠️ CRITICAL: Don't Over-Complicate

The fix is simpler than it looks:

### For `manual_checkin_reservation`:
```python
# NEW: Check if guest already exists
existing_guest = Guest.objects.filter(
    reservation_number=reservation.booking_reference
).first()

if existing_guest:
    # Guest exists - just link this reservation
    reservation.guest = existing_guest
    reservation.save()
    
    # Generate PIN for THIS room only (if needed)
    # Front door PIN already exists on guest
    
    messages.success(request, f"Linked to existing guest {existing_guest.full_name}")
    return redirect('admin_page')

# else: create new guest (existing code continues)
```

### For `enrich_reservation`:
```python
# After creating guest, before generating PINs:

# NEW: Find all reservations with same booking ref
all_reservations = Reservation.objects.filter(
    booking_reference=reservation.booking_reference,
    status='confirmed',
    guest__isnull=True  # Only unenriched
)

# Link ALL to this guest
for res in all_reservations:
    res.guest = guest
    res.save()

# Then generate PINs for all rooms in all_reservations
```

### For `room_detail`:
```python
# In context dict:
guest_reservations = guest.reservations.all()  # NEW: Works because of ForeignKey
is_multiroom = guest_reservations.count() > 1

context = {
    'guest_reservations': guest_reservations,
    'is_multiroom': is_multiroom,
    # ... existing context
}
```

---

## 🎯 WHAT TO DO RIGHT NOW

**Option A: Deploy Phase 1 now, implement Phase 2 after**
- Safest approach
- Database schema will be ready
- Admin can manually link reservations if needed
- Then add full multi-room logic

**Option B: Implement Phase 2 now, test locally, deploy everything**
- Faster
- More testing required
- Deploy database + logic together

**My Recommendation:** Option A
1. Deploy database schema fix NOW (blocks production)
2. Test manually that admin can check in Room 1, then Room 2 (no more database error)
3. Then implement full multi-room logic

---

## WHAT DO YOU WANT TO DO?

1. Deploy Phase 1 (schema) now?
2. Implement Phase 2 (logic) first, then deploy both?
3. Or shall I start implementing Phase 2 code changes right now?
