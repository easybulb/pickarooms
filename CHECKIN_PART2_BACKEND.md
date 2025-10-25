# CHECK-IN FLOW OVERHAUL - PART 2: BACKEND

## 🗄️ Step 1: Database

```python
# main/models.py - Add to Guest model
car_registration = models.CharField(max_length=20, null=True, blank=True)

# main/models.py - New model
class CheckInAnalytics(models.Model):
    session_id = models.CharField(max_length=100)
    booking_reference = models.CharField(max_length=20, null=True, blank=True)
    step_reached = models.IntegerField()
    completed = models.BooleanField(default=False)
    device_type = models.CharField(max_length=20)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
```

Run: `python manage.py makemigrations && python manage.py migrate`

## 🔧 Step 2: Views (main/views.py)

### View 1: checkin_step1
```python
@ratelimit(key='ip', rate='10/m', method='POST', block=True)
def checkin_step1(request):
    if request.method == 'POST':
        booking_ref = request.POST.get('booking_ref', '').strip()
        
        # Return guest? Skip to room_detail
        guest = Guest.objects.filter(
            reservation_number=booking_ref, is_archived=False
        ).first()
        if guest:
            request.session['reservation_number'] = booking_ref
            return redirect('room_detail', room_token=guest.secure_token)
        
        # Unenriched reservation?
        reservation = Reservation.objects.filter(
            booking_reference=booking_ref, status='confirmed'
        ).first()
        if reservation:
            request.session['checkin_flow'] = {
                'booking_ref': booking_ref,
                'reservation_id': reservation.id,
                'step': 1,
            }
            return redirect('checkin_details')
        
        # Not found
        return redirect('checkin_not_found')
    
    return render(request, 'main/checkin_step1.html')
```

### View 2: checkin_details
```python
def checkin_details(request):
    flow_data = request.session.get('checkin_flow')
    if not flow_data:
        return redirect('checkin')
    
    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        phone_number = normalize_phone_to_e164(
            request.POST.get('phone_number', '').strip(), '+44'
        )
        email = request.POST.get('email', '').strip() or None
        
        if not phone_number:
            messages.error(request, "Invalid phone number")
            return render(request, 'main/checkin_step2.html')
        
        flow_data.update({
            'full_name': full_name,
            'phone_number': phone_number,
            'email': email,
            'step': 2
        })
        request.session['checkin_flow'] = flow_data
        request.session.modified = True
        
        # 🔥 START BACKGROUND PIN GENERATION
        from main.tasks import generate_checkin_pin_background
        generate_checkin_pin_background.delay(request.session.session_key)
        
        return redirect('checkin_parking')
    
    return render(request, 'main/checkin_step2.html', {'flow_data': flow_data})
```

### View 3: checkin_parking
```python
def checkin_parking(request):
    flow_data = request.session.get('checkin_flow')
    if not flow_data or flow_data.get('step', 0) < 2:
        return redirect('checkin')
    
    if request.method == 'POST':
        has_car = request.POST.get('has_car') == 'yes'
        car_reg = request.POST.get('car_registration', '').strip().upper() if has_car else None
        
        flow_data.update({
            'has_car': has_car,
            'car_registration': car_reg,
            'step': 3
        })
        request.session['checkin_flow'] = flow_data
        request.session.modified = True
        
        return redirect('checkin_confirm')
    
    return render(request, 'main/checkin_step3.html', {'flow_data': flow_data})
```

### View 4: checkin_confirm
```python
def checkin_confirm(request):
    flow_data = request.session.get('checkin_flow')
    if not flow_data or flow_data.get('step', 0) < 3:
        return redirect('checkin')
    
    reservation = Reservation.objects.get(id=flow_data['reservation_id'])
    
    if request.method == 'POST':
        pin_status = flow_data.get('pin_generated')
        
        if pin_status == True:
            # ✅ PIN READY! Create guest
            guest = Guest.objects.create(
                full_name=flow_data['full_name'],
                phone_number=flow_data['phone_number'],
                email=flow_data.get('email'),
                reservation_number=flow_data['booking_ref'],
                check_in_date=reservation.check_in_date,
                check_out_date=reservation.check_out_date,
                assigned_room=reservation.room,
                car_registration=flow_data.get('car_registration'),
                early_checkin_time=reservation.early_checkin_time,
                late_checkout_time=reservation.late_checkout_time,
                front_door_pin=flow_data['pin'],
                front_door_pin_id=flow_data['front_door_pin_id'],
                room_pin_id=flow_data['room_pin_id'],
            )
            
            reservation.guest = guest
            reservation.save()
            
            del request.session['checkin_flow']
            request.session['reservation_number'] = guest.reservation_number
            
            # 🚀 INSTANT REDIRECT
            return redirect('room_detail', room_token=guest.secure_token)
            
        elif pin_status == False:
            # ❌ FAILED
            return redirect('checkin_error')
        else:
            # ⏳ STILL GENERATING (guest was fast)
            import time
            time.sleep(2)
            flow_data = request.session.get('checkin_flow')
            if flow_data.get('pin_generated') == True:
                return checkin_confirm(request)
            return redirect('checkin_error')
    
    return render(request, 'main/checkin_step4.html', {
        'flow_data': flow_data,
        'reservation': reservation,
    })
```

### View 5-7: Error pages
```python
def checkin_not_found(request):
    booking_ref = request.session.get('attempted_booking_ref', '')
    return render(request, 'main/checkin_not_found.html', {'booking_ref': booking_ref})

def checkin_error(request):
    flow_data = request.session.get('checkin_flow', {})
    return render(request, 'main/checkin_error.html', {
        'booking_ref': flow_data.get('booking_ref'),
        'error': flow_data.get('pin_error'),
    })

def checkin_pin_status(request):
    flow_data = request.session.get('checkin_flow', {})
    return JsonResponse({
        'ready': flow_data.get('pin_generated') == True,
        'failed': flow_data.get('pin_generated') == False,
        'error': flow_data.get('pin_error'),
    })
```

## 🔗 Step 3: URLs (main/urls.py)

```python
urlpatterns = [
    path('checkin/', views.checkin_step1, name='checkin'),
    path('checkin/details/', views.checkin_details, name='checkin_details'),
    path('checkin/parking/', views.checkin_parking, name='checkin_parking'),
    path('checkin/confirm/', views.checkin_confirm, name='checkin_confirm'),
    path('checkin/not-found/', views.checkin_not_found, name='checkin_not_found'),
    path('checkin/error/', views.checkin_error, name='checkin_error'),
    path('checkin/pin-status/', views.checkin_pin_status, name='checkin_pin_status'),
    # ... existing routes
]
```

## 📖 Read Next: PART 3 (Frontend), PART 4 (Background Task)
