# MULTI-ROOM BOOKING - COMPLETE IMPLEMENTATION PLAN

## ✅ PHASE 1: DATABASE SCHEMA (COMPLETED)

**Status:** ✅ Done
- Changed `Reservation.guest` from `OneToOneField` to `ForeignKey`
- Updated `Guest.is_ical_guest()` method
- Updated `Guest._get_message_context()` method
- Migration created and applied locally

---

## 🚧 PHASE 2: MULTI-ROOM CHECK-IN LOGIC (TO DO)

### A. Guest Web Check-In Flow (`enrich_reservation`)

**Current Issue:**
- Guest enters booking ref → Finds multiple reservations
- Creates 1 Guest but only links to 1 reservation
- Other rooms remain unenriched

**Required Changes:**
1. Detect if multiple reservations exist with same booking reference
2. Create 1 Guest record
3. Link ALL reservations to that single Guest
4. Generate PINs for ALL rooms (front door + each room)

**File:** `main/views.py` - line ~392

```python
def enrich_reservation(request):
    # ... existing validation ...
    
    # NEW: Check for multi-room booking
    all_reservations = Reservation.objects.filter(
        booking_reference=reservation.booking_reference,
        status='confirmed',
        guest__isnull=True  # Only unenriched
    )
    
    # Create guest
    guest = Guest.objects.create(...)
    
    # Link ALL reservations to guest
    for res in all_reservations:
        res.guest = guest
        res.save()
    
    # Generate PINs for ALL rooms
    # - Front door (1 PIN shared)
    # - Room 1 door
    # - Room 2 door
    # etc.
```

---

### B. Admin Manual Check-In (`manual_checkin_reservation`)

**Current Issue:**
- Admin clicks "Check In" on Room 1 → Guest created ✅
- Admin clicks "Check In" on Room 2 → DATABASE ERROR ❌ (fixed by schema change)
- But Room 2 PIN not generated, not linked to existing guest

**Required Changes:**
1. Check if Guest with same booking_reference already exists
2. If YES → Link reservation to existing guest, generate PIN for new room only
3. If NO → Create new guest, check for other reservations with same booking ref, generate PINs for all

**File:** `main/views.py` - line ~1746

```python
def manual_checkin_reservation(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id)
    
    # NEW: Check if Guest already exists with this booking reference
    existing_guest = Guest.objects.filter(
        reservation_number=reservation.booking_reference
    ).first()
    
    if existing_guest:
        # Link reservation to existing guest
        reservation.guest = existing_guest
        reservation.save()
        
        # Generate PIN for this room ONLY (front door already has PIN)
        # Add room lock PIN for the new room
        
        messages.success(request, f"Linked to existing guest {existing_guest.full_name}. Generated PIN for {reservation.room.name}")
        return redirect('admin_page')
    
    # Create new guest
    guest = Guest.objects.create(...)
    
    # NEW: Check for other reservations with same booking ref
    other_reservations = Reservation.objects.filter(
        booking_reference=reservation.booking_reference,
        status='confirmed',
        guest__isnull=True
    ).exclude(id=reservation.id)
    
    # Link ALL to same guest
    reservation.guest = guest
    reservation.save()
    
    for other_res in other_reservations:
        other_res.guest = guest
        other_res.save()
    
    # Generate PINs for ALL rooms
    # - Front door (1 shared PIN)
    # - Each room door
```

---

### C. SMS Collision Resolution (`handle_multi_collision_enrichment`)

**Current Status:** Partially implemented (yesterday's work)

**File:** `main/services/sms_commands.py`

**Required Verification:**
- Ensure it creates 1 Guest (not multiple)
- Links all reservations to that 1 Guest
- Generates PINs for all rooms

---

## 🚧 PHASE 3: MULTI-ROOM PIN GENERATION (TO DO)

### Current Issue:
- System only generates 1 front door PIN + 1 room door PIN
- Multi-room guests need: Front door + Room 1 + Room 2 + Room 3...

### Solution:
Create helper function `generate_multiroom_pins(guest, reservations_list)`

**File:** `main/views.py` or new `main/pin_multi_room_utils.py`

```python
def generate_multiroom_pins(guest, reservations):
    """
    Generate PINs for multi-room bookings
    - 1 front door PIN (shared across all rooms)
    - 1 PIN per room door
    
    Returns: dict with room_id → pin_id mapping
    """
    front_door_lock = TTLock.objects.get(is_front_door=True)
    pin = generate_memorable_4digit_pin()  # Same PIN for all
    
    uk_timezone = pytz.timezone("Europe/London")
    now_uk_time = timezone.now().astimezone(uk_timezone)
    start_time = int(now_uk_time.timestamp() * 1000)
    
    # Use latest check-out date from all reservations
    latest_checkout = max([r.check_out_date for r in reservations])
    check_out_time = guest.late_checkout_time or time(11, 0)
    end_date = uk_timezone.localize(
        datetime.datetime.combine(latest_checkout, check_out_time)
    ) + timedelta(days=1)
    end_time = int(end_date.timestamp() * 1000)
    
    ttlock_client = TTLockClient()
    room_pin_ids = {}
    
    # Generate front door PIN
    front_door_response = ttlock_client.generate_temporary_pin(
        lock_id=front_door_lock.lock_id,
        pin=pin,
        start_time=start_time,
        end_time=end_time,
        name=f"Front Door - Multi-Room - {guest.full_name} - {pin}"
    )
    
    guest.front_door_pin = pin
    guest.front_door_pin_id = front_door_response["keyboardPwdId"]
    
    # Generate PIN for each room
    for reservation in reservations:
        room_lock = reservation.room.ttlock
        if room_lock:
            room_response = ttlock_client.generate_temporary_pin(
                lock_id=room_lock.lock_id,
                pin=pin,
                start_time=start_time,
                end_time=end_time,
                name=f"Room - {reservation.room.name} - {guest.full_name} - {pin}"
            )
            room_pin_ids[reservation.room.id] = room_response["keyboardPwdId"]
    
    guest.save()
    return room_pin_ids
```

---

## 🚧 PHASE 4: ROOM_DETAIL PAGE UPDATES (TO DO)

### Current Issue:
- room_detail.html only shows 1 room
- Multi-room guests need to see ALL their rooms

### Required Changes:

**File:** `main/views.py` - `room_detail` function

```python
def room_detail(request, room_token):
    guest = Guest.objects.filter(secure_token=room_token).first()
    
    # NEW: Get all reservations for this guest (multi-room)
    guest_reservations = guest.reservations.all()  # Now works because of ForeignKey
    
    # Build list of rooms guest has access to
    guest_rooms = [
        {
            'room': res.room,
            'check_in': res.check_in_date,
            'check_out': res.check_out_date,
            'booking_ref': res.booking_reference,
        }
        for res in guest_reservations
    ]
    
    context = {
        'guest': guest,
        'primary_room': guest.assigned_room,  # Main room (for backward compatibility)
        'guest_rooms': guest_rooms,  # NEW: All rooms
        'is_multiroom': len(guest_rooms) > 1,  # NEW: Flag
        # ... existing context ...
    }
```

**File:** `main/templates/main/room_detail.html`

Add section after PIN display:

```html
{% if is_multiroom %}
<div class="multi-room-section">
    <h2>🏠 Your Rooms</h2>
    <p>You have access to multiple rooms:</p>
    <div class="rooms-grid">
        {% for room_info in guest_rooms %}
        <div class="room-card">
            <h3>{{ room_info.room.name }}</h3>
            <p>Check-in: {{ room_info.check_in|date:"d M Y" }}</p>
            <p>Check-out: {{ room_info.check_out|date:"d M Y" }}</p>
            <button class="btn-unlock" onclick="unlockRoom('{{ room_info.room.id }}')">
                🔓 Unlock {{ room_info.room.name }}
            </button>
        </div>
        {% endfor %}
    </div>
    <p class="pin-note">✅ Your PIN works for all rooms: {{ front_door_pin }}</p>
</div>
{% endif %}
```

Add unlock functionality for specific rooms:

```javascript
function unlockRoom(roomId) {
    // Similar to existing unlock logic but targets specific room
    fetch(window.location.href, {
        method: 'POST',
        body: formData,
        headers: {'X-CSRFToken': csrfToken}
    })
    // ...
}
```

---

## 🚧 PHASE 5: ADMIN DASHBOARD UPDATES (TO DO)

### Current Issue:
- Dashboard shows each reservation separately
- Multi-room bookings not visually grouped

### Required Enhancement:

**File:** `main/templates/main/admin_page.html` or `all_reservations.html`

Add visual indicator for multi-room bookings:

```html
{% if entry.is_multiroom %}
<span class="badge multi-room-badge">
    🏠 Multi-Room ({{ entry.room_count }} rooms)
</span>
{% endif %}
```

**File:** `main/views.py` - `admin_page` function

Add multi-room detection:

```python
# When building todays_entries and current_entries
for entry in entries:
    if entry['type'] == 'guest':
        # Check how many reservations this guest has
        room_count = entry['object'].reservations.count()
        entry['is_multiroom'] = room_count > 1
        entry['room_count'] = room_count
```

---

## 📋 TESTING CHECKLIST

### Test Scenario 1: Guest Web Check-In (Multi-Room)
- [ ] Create 2 reservations: same booking ref, same check-in date, different rooms
- [ ] Guest enters booking ref via web
- [ ] System creates 1 Guest
- [ ] System links BOTH reservations to Guest
- [ ] System generates front door PIN (1)
- [ ] System generates Room 1 PIN
- [ ] System generates Room 2 PIN
- [ ] room_detail page shows BOTH rooms
- [ ] Guest can unlock BOTH room doors remotely

### Test Scenario 2: Admin Manual Check-In (Sequential)
- [ ] Create 2 reservations: same booking ref, same date, different rooms
- [ ] Admin clicks "Check In" on Room 1
- [ ] Guest created, PIN generated for Room 1
- [ ] Admin clicks "Check In" on Room 2
- [ ] System detects existing guest
- [ ] Links Room 2 to same guest (no error!)
- [ ] Generates PIN for Room 2 door
- [ ] Verify: Both reservations point to same Guest ID
- [ ] Verify: Guest has PINs for front door + Room 1 + Room 2

### Test Scenario 3: Admin Manual Check-In (All at Once)
- [ ] Create 3 reservations: same booking ref, same date
- [ ] Admin clicks "Check In" on any one
- [ ] System detects other unenriched reservations with same ref
- [ ] Creates 1 Guest
- [ ] Links ALL 3 reservations to Guest
- [ ] Generates PINs for front door + all 3 rooms

### Test Scenario 4: SMS Collision Resolution
- [ ] Create 2 reservations: same check-in date
- [ ] Admin replies with multi-line SMS:
   ```
   1234567890: 1-2
   1234567890: 2-2
   ```
- [ ] System creates 1 Guest
- [ ] Links BOTH reservations
- [ ] Generates PINs for both rooms

### Test Scenario 5: room_detail Page Display
- [ ] Guest with 2 rooms checks in
- [ ] Opens room_detail page
- [ ] Sees "Your Rooms" section
- [ ] Both rooms listed
- [ ] Can unlock each room individually
- [ ] PIN displayed works for all doors

---

## 🔧 FILES TO MODIFY

1. **main/views.py**
   - `enrich_reservation()` - line ~392
   - `manual_checkin_reservation()` - line ~1746
   - `room_detail()` - Add multi-room context

2. **main/templates/main/room_detail.html**
   - Add multi-room section
   - Add unlock buttons for each room

3. **main/views.py** or **main/pin_multi_room_utils.py**
   - Create `generate_multiroom_pins()` helper

4. **main/templates/main/admin_page.html**
   - Add multi-room visual indicators

5. **main/services/sms_commands.py**
   - Verify `handle_multi_collision_enrichment()` works correctly

---

## 🎯 PRIORITY ORDER

1. **PHASE 2A** - Guest Web Check-In (most common use case)
2. **PHASE 2B** - Admin Manual Check-In (blocks production right now)
3. **PHASE 3** - Multi-Room PIN Generation (helper function)
4. **PHASE 4** - room_detail Page Updates (user experience)
5. **PHASE 5** - Admin Dashboard Updates (nice-to-have)

---

## 🚀 READY TO IMPLEMENT?

**Phase 1:** ✅ COMPLETE
**Phase 2-5:** Ready to code

Shall I proceed with Phase 2A (Guest Web Check-In) first?
