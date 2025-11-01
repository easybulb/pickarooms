"""
Multi-step check-in flow views for PickARooms
Replaces the single-page checkin view with a 4-step progressive flow
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django_ratelimit.decorators import ratelimit
from main.models import Guest, Reservation, CheckInAnalytics, GuestIDUpload
from main.phone_utils import normalize_phone_to_e164, validate_phone_number
from main.tasks import generate_checkin_pin_background
import pytz
import datetime
import logging

logger = logging.getLogger('main')


@ratelimit(key='ip', rate='10/m', method='POST', block=True)
def checkin_step1(request):
    """
    Step 1: Booking Reference Validation
    - Check if guest already exists (return guest → skip to room_detail)
    - Check if reservation exists (unenriched → proceed to Step 2)
    - Otherwise show error
    """
    if request.method == 'POST':
        booking_ref = request.POST.get('reservation_number', '').strip()
        
        # Track analytics - Step 1 started
        # Detect device type from User-Agent header
        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
        is_mobile = any(x in user_agent for x in ['mobile', 'android', 'iphone', 'ipad', 'ipod'])
        device_type = 'mobile' if is_mobile else 'desktop'
        
        try:
            CheckInAnalytics.objects.create(
                session_id=request.session.session_key or request.session._get_or_create_session_key(),
                booking_reference=booking_ref,
                step_reached=1,
                device_type=device_type
            )
        except Exception as e:
            # Don't fail check-in if analytics fails
            logger.warning(f"Failed to create analytics: {str(e)}")
        
        # Step 1: Check for existing active guest (return guest)
        guest = Guest.objects.filter(
            reservation_number=booking_ref,
            is_archived=False
        ).order_by('-check_in_date').first()
        
        if guest:
            # Check if guest has checked out
            uk_timezone = pytz.timezone("Europe/London")
            now_uk_time = timezone.now().astimezone(uk_timezone)
            check_out_time = guest.late_checkout_time or datetime.time(11, 0)
            check_out_datetime = uk_timezone.localize(
                datetime.datetime.combine(guest.check_out_date, check_out_time)
            )
            
            if now_uk_time > check_out_datetime:
                # Guest checked out - archive and redirect to rebook
                guest.is_archived = True
                guest.front_door_pin = None
                guest.front_door_pin_id = None
                guest.room_pin_id = None
                guest.save()
                logger.info(f"Archived guest {guest.reservation_number} during check-in")
                return redirect("rebook_guest")
            
            # Valid active guest - skip entire flow
            request.session['reservation_number'] = guest.reservation_number
            messages.success(request, f"Welcome back, {guest.full_name}!")
            return redirect('room_detail', room_token=guest.secure_token)
        
        # Step 2: Check for archived guest (past stay)
        past_guest = Guest.objects.filter(
            reservation_number=booking_ref,
            is_archived=True
        ).first()
        if past_guest:
            return redirect("rebook_guest")
        
        # Step 3: Check for unenriched reservation (iCal integration)
        reservation = Reservation.objects.filter(
            booking_reference=booking_ref,
            status='confirmed'
        ).first()
        
        if reservation:
            # Check if already enriched
            if reservation.is_enriched():
                guest = reservation.guest
                request.session['reservation_number'] = guest.reservation_number
                messages.success(request, f"Welcome back, {guest.full_name}!")
                return redirect('room_detail', room_token=guest.secure_token)
            
            # Unenriched reservation - start multi-step flow
            request.session['checkin_flow'] = {
                'booking_ref': booking_ref,
                'reservation_id': reservation.id,
                'step': 1,
            }
            return redirect('checkin_details')
        
        # Step 4: Not found
        request.session['attempted_booking_ref'] = booking_ref
        messages.error(request, "Booking reference not found. Please check and try again.")
        return render(request, 'main/checkin.html', {
            'error': 'Booking reference not found',
            'reservation_number': booking_ref,
        })
    
    # GET request - show Step 1 form
    return render(request, 'main/checkin.html', {
        'reservation_number': request.session.get('reservation_number', ''),
    })


def checkin_details(request):
    """
    Step 2: Guest Details (Name, Phone, Email)
    After submission, triggers background PIN generation
    """
    flow_data = request.session.get('checkin_flow')
    if not flow_data:
        messages.error(request, "Session expired. Please start again.")
        return redirect('checkin')
    
    # Update analytics
    try:
        CheckInAnalytics.objects.filter(
            session_id=request.session.session_key,
            booking_reference=flow_data.get('booking_ref')
        ).update(step_reached=2)
    except Exception as e:
        logger.warning(f"Failed to update analytics: {str(e)}")
    
    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        phone_number = request.POST.get('phone_number', '').strip()
        country_code = request.POST.get('country_code', '+44').strip()
        email = request.POST.get('email', '').strip() or None
        
        # Validate required fields
        if not full_name:
            messages.error(request, "Full name is required.")
            return render(request, 'main/checkin_step2.html', {'flow_data': flow_data})
        
        # Normalize and validate phone number
        if phone_number:
            phone_number = normalize_phone_to_e164(phone_number, country_code)
            if phone_number:
                is_valid, error_msg = validate_phone_number(phone_number)
                if not is_valid:
                    messages.error(request, f"Invalid phone number: {error_msg}")
                    return render(request, 'main/checkin_step2.html', {'flow_data': flow_data})
            else:
                messages.error(request, "Please enter a valid phone number.")
                return render(request, 'main/checkin_step2.html', {'flow_data': flow_data})
        else:
            messages.error(request, "Phone number is required.")
            return render(request, 'main/checkin_step2.html', {'flow_data': flow_data})
        
        # Update flow data
        flow_data.update({
            'full_name': full_name,
            'phone_number': phone_number,
            'email': email,
            'step': 2
        })
        request.session['checkin_flow'] = flow_data
        request.session.modified = True
        
        # 🔥 START BACKGROUND PIN GENERATION
        # Ensure session exists before triggering task
        if not request.session.session_key:
            request.session.create()
        session_key = request.session.session_key
        
        # Save session immediately before triggering background task
        request.session.save()
        
        generate_checkin_pin_background.delay(session_key)
        logger.info(f"Triggered background PIN generation for session {session_key}")
        
        return redirect('checkin_parking')
    
    # GET request
    return render(request, 'main/checkin_step2.html', {
        'flow_data': flow_data
    })


def checkin_parking(request):
    """
    Step 3: Additional Information (Parking + ID Upload)
    While guest fills this out, PIN is being generated in background
    """
    flow_data = request.session.get('checkin_flow')
    if not flow_data or flow_data.get('step', 0) < 2:
        messages.error(request, "Please complete previous steps first.")
        return redirect('checkin')

    # Update analytics
    try:
        CheckInAnalytics.objects.filter(
            session_id=request.session.session_key,
            booking_reference=flow_data.get('booking_ref')
        ).update(step_reached=3)
    except Exception as e:
        logger.warning(f"Failed to update analytics: {str(e)}")

    if request.method == 'POST':
        has_car = request.POST.get('has_car') == 'yes'
        car_reg = request.POST.get('car_registration', '').strip().upper() if has_car else None

        # Handle ID upload (optional)
        id_image_url = None
        id_file = request.FILES.get('id_image') or request.FILES.get('id_image_gallery')

        if id_file:
            try:
                # Validate file
                if id_file.size > 5 * 1024 * 1024:  # 5MB limit
                    messages.error(request, "ID image must be under 5MB.")
                    return render(request, 'main/checkin_step3.html', {'flow_data': flow_data})

                if not id_file.content_type.startswith('image/'):
                    messages.error(request, "Please upload a valid image file.")
                    return render(request, 'main/checkin_step3.html', {'flow_data': flow_data})

                # Upload to Cloudinary
                import cloudinary.uploader
                from django.utils import timezone as django_tz
                now = django_tz.now()

                upload_response = cloudinary.uploader.upload(
                    id_file,
                    folder=f"checkin_ids/{now.year}/{now.month}/{now.day}/",
                    resource_type="image"
                )

                if 'url' in upload_response:
                    id_image_url = upload_response['url']
                    logger.info(f"Uploaded ID for checkin session {request.session.session_key}: {id_image_url}")
                else:
                    logger.error(f"Cloudinary upload failed: {upload_response}")
                    messages.warning(request, "ID upload failed, but you can continue check-in.")

            except Exception as e:
                logger.error(f"Error uploading ID during check-in: {str(e)}")
                messages.warning(request, "ID upload failed, but you can continue check-in.")

        # Update flow data
        flow_data.update({
            'has_car': has_car,
            'car_registration': car_reg,
            'id_image_url': id_image_url,
            'step': 3
        })
        request.session['checkin_flow'] = flow_data
        request.session.modified = True

        return redirect('checkin_confirm')

    # GET request
    return render(request, 'main/checkin_step3.html', {
        'flow_data': flow_data
    })


def checkin_confirm(request):
    """
    Step 4: Confirmation Summary
    Check if PIN is ready (from background task)
    - If ready: Create guest immediately and redirect to room_detail
    - If failed: Show error page with contact info
    - If still generating: Wait briefly and check again
    """
    flow_data = request.session.get('checkin_flow')
    if not flow_data or flow_data.get('step', 0) < 3:
        messages.error(request, "Please complete previous steps first.")
        return redirect('checkin')
    
    # Update analytics
    try:
        CheckInAnalytics.objects.filter(
            session_id=request.session.session_key,
            booking_reference=flow_data.get('booking_ref')
        ).update(step_reached=4)
    except Exception as e:
        logger.warning(f"Failed to update analytics: {str(e)}")
    
    # Get reservation
    try:
        reservation = Reservation.objects.select_related('room').get(id=flow_data['reservation_id'])
    except Reservation.DoesNotExist:
        messages.error(request, "Reservation not found. Please start again.")
        del request.session['checkin_flow']
        return redirect('checkin')
    
    if request.method == 'POST':
        pin_status = flow_data.get('pin_generated')
        
        if pin_status == True:
            # ✅ PIN READY! Create guest
            try:
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
                
                # Save ID image if uploaded (using GuestIDUpload model)
                if flow_data.get('id_image_url'):
                    try:
                        GuestIDUpload.objects.create(
                            guest=guest,
                            id_image=flow_data['id_image_url']
                        )
                        logger.info(f"Saved ID upload for guest {guest.full_name}")
                    except Exception as e:
                        logger.error(f"Failed to save ID upload: {str(e)}")
                
                # Link guest to reservation
                reservation.guest = guest
                reservation.save()
                
                # Update analytics
                try:
                    CheckInAnalytics.objects.filter(
                        session_id=request.session.session_key,
                        booking_reference=flow_data.get('booking_ref')
                    ).update(
                        completed=True,
                        completed_at=timezone.now()
                    )
                except Exception as e:
                    logger.warning(f"Failed to update analytics: {str(e)}")
                
                # Clean up session
                del request.session['checkin_flow']
                request.session['reservation_number'] = guest.reservation_number
                
                logger.info(f"✅ Guest {guest.full_name} created via multi-step check-in")
                
                # 🚀 INSTANT REDIRECT
                messages.success(request, f"Welcome, {guest.full_name}!")
                return redirect('room_detail', room_token=guest.secure_token)
                
            except Exception as e:
                logger.error(f"Failed to create guest: {str(e)}")
                messages.error(request, "Failed to complete check-in. Please contact support.")
                return redirect('checkin_error')
        
        elif pin_status == False:
            # ❌ PIN GENERATION FAILED
            logger.error(f"PIN generation failed for booking {flow_data['booking_ref']}")
            return redirect('checkin_error')
        
        else:
            # ⏳ STILL GENERATING (guest was very fast)
            # Wait 2 seconds and check again
            import time
            time.sleep(2)
            
            # Reload session data
            flow_data = request.session.get('checkin_flow', {})
            if flow_data.get('pin_generated') == True:
                # Ready now - process again
                request.session['checkin_flow'] = flow_data
                return checkin_confirm(request)
            
            # Still not ready - show error
            logger.warning(f"PIN still generating after wait for booking {flow_data.get('booking_ref')}")
            return redirect('checkin_error')
    
    # GET request - show confirmation page
    return render(request, 'main/checkin_step4.html', {
        'flow_data': flow_data,
        'reservation': reservation,
    })


def checkin_pin_status(request):
    """
    AJAX endpoint to check PIN generation status
    Returns JSON with ready/failed/error status
    """
    flow_data = request.session.get('checkin_flow', {})
    
    return JsonResponse({
        'ready': flow_data.get('pin_generated') == True,
        'failed': flow_data.get('pin_generated') == False,
        'error': flow_data.get('pin_error'),
    })


def checkin_error(request):
    """
    Error page shown when PIN generation fails
    Displays contact information for manual assistance
    """
    flow_data = request.session.get('checkin_flow', {})
    
    return render(request, 'main/checkin_error.html', {
        'booking_ref': flow_data.get('booking_ref'),
        'error': flow_data.get('pin_error', 'Unknown error'),
    })
