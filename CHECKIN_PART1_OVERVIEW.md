# CHECK-IN FLOW OVERHAUL - PART 1: OVERVIEW

## 🎯 Goal
Multi-step check-in with background PIN generation (no waiting!)

## 📊 Flow
```
Step 1: /checkin/ → Booking ref
Step 2: /checkin/details/ → Name/Phone/Email → 🔥 START PIN GENERATION
Step 3: /checkin/parking/ → Car info (PIN generating...)
Step 4: /checkin/confirm/ → Confirm → ✅ PIN READY! Instant redirect
Step 5: /room_detail/ → Show PIN
```

## 🔑 Key Innovation
After Step 2, Celery generates PIN in background while guest fills parking info (10-20 seconds). By Step 4, PIN ready = instant redirect!

## 📦 Components

### Database
```python
# Guest model
car_registration = CharField(max_length=20, null=True)

# Analytics
class CheckInAnalytics(models.Model):
    session_id, booking_reference, step_reached, 
    completed, device_type, started_at, completed_at
```

### Session
```python
request.session['checkin_flow'] = {
    'booking_ref', 'reservation_id', 'full_name',
    'phone_number', 'email', 'has_car', 'car_registration',
    'step', 'pin_generated', 'pin', 'front_door_pin_id',
    'room_pin_id', 'pin_error'
}
```

### New Files
- views.py: 7 new views
- urls.py: 7 new routes
- tasks.py: 1 background task
- 6 new templates
- checkin_flow.js + .css

## ⏱️ Time: ~18-20 hours

## 📖 Read Next
- PART 2: Backend
- PART 3: Frontend  
- PART 4: Background PIN
