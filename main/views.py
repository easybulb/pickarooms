# main/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required, user_passes_test
import requests

# Import new multi-step check-in views
from main.checkin_views import (
    checkin_step1,
    checkin_details,
    checkin_parking,
    checkin_confirm,
    checkin_pin_status,
    checkin_error
)
from django.core.mail import EmailMessage, BadHeaderError
from django.conf import settings
from django.http import HttpResponse
from django.utils.timezone import now, localtime
from django.utils import timezone
from datetime import date, datetime, time, timedelta
from django.core.mail import send_mail
from django.http import Http404, JsonResponse
from django.db import IntegrityError
from django.db.models import Q
from django_ratelimit.decorators import ratelimit
from django.core.paginator import Paginator
from django.contrib import messages
import pandas as pd
import random
from django.utils.translation import gettext as _
from django.utils.safestring import mark_safe
from langdetect import detect
import uuid
import pytz
import datetime
import re
from .models import Guest, Room, ReviewCSVUpload, TTLock, AuditLog, GuestIDUpload, PopularEvent, Reservation, RoomICalConfig
from .ttlock_utils import TTLockClient
from .pin_utils import generate_memorable_4digit_pin, add_wakeup_prefix
from .phone_utils import normalize_phone_to_e164, validate_phone_number
from .dashboard_helpers import get_current_guests_data, build_entries_list, get_guest_status, get_night_progress
import logging
from django.views.decorators.csrf import csrf_exempt
import json
from django.contrib.auth.models import User, Group, Permission
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.urls import reverse
import os
import time as time_module
import cloudinary
import cloudinary.uploader
import cloudinary.api
from cloudinary.utils import cloudinary_url
from django.core.files.storage import default_storage
from cloudinary.uploader import upload as cloudinary_upload
from twilio.rest import Client

# Set up logging for TTLock interactions
logger = logging.getLogger('main')

def home(request):
    latest_file = ReviewCSVUpload.objects.last()
    
    if latest_file and latest_file.data:
        reviews = latest_file.data

        # Filter out non-English reviews
        def is_english(review_text):
            try:
                return detect(review_text) == "en"
            except:
                return False  # If detection fails, exclude the review

        english_reviews = [r for r in reviews if is_english(r["text"])]

        # Separate 10/10 reviews from 9/10 reviews
        perfect_reviews = [r for r in english_reviews if r["score"] == 10]
        good_reviews = [r for r in english_reviews if r["score"] == 9]

        random.shuffle(perfect_reviews)
        random.shuffle(good_reviews)

        selected_reviews = perfect_reviews[:3] + good_reviews[:2]
        random.shuffle(selected_reviews)

        latest_reviews = selected_reviews
    else:
        latest_reviews = []  # Empty list if no CSV is available

    context = {
        "latest_reviews": latest_reviews,
        "welcome_text": _("Welcome, Your Stay Starts Here!"),
        "instructions": _("Enter your phone number to access your PIN, check-in guide, and all the details for a smooth experience"),
        "LANGUAGES": settings.LANGUAGES,
        "GOOGLE_MAPS_API_KEY": settings.GOOGLE_MAPS_API_KEY,
        "reservation_number": request.session.get("reservation_number", ""),
    }

    return render(request, "main/home.html", context)

def awards_reviews(request):
    latest_file = ReviewCSVUpload.objects.last()
    
    if latest_file and latest_file.data:
        reviews = latest_file.data
        filtered_reviews = [r for r in reviews if r["score"] >= 9 and r["text"].strip()]
        all_reviews = sorted(filtered_reviews, key=lambda x: x["score"], reverse=True)[:20]
    else:
        all_reviews = []

    return render(request, "main/awards_reviews.html", {"all_reviews": all_reviews})

def about(request):
    return render(request, 'main/about.html')

def explore_manchester(request):
    return render(request, 'main/explore_manchester.html', {
        'GOOGLE_MAPS_API_KEY': settings.GOOGLE_MAPS_API_KEY
    })

# Legacy check-in view (replaced by multi-step flow)
# Kept for reference - DELETE after testing new flow
@ratelimit(key='ip', rate='7/m', method='POST', block=True)
def checkin_legacy(request):
    if request.method == "POST":
        reservation_number = request.POST.get('reservation_number', '').strip()

        # Step 1: Check for non-archived (active) guest
        guest = Guest.objects.filter(reservation_number=reservation_number, is_archived=False).order_by('-check_in_date').first()

        if guest:
            # Check if the guest has checked out (even if not archived)
            uk_timezone = pytz.timezone("Europe/London")
            now_uk_time = timezone.now().astimezone(uk_timezone)
            check_out_time = guest.late_checkout_time if guest.late_checkout_time else datetime.time(11, 0)
            check_out_datetime = uk_timezone.localize(
                datetime.datetime.combine(guest.check_out_date, check_out_time)
            )

            if now_uk_time > check_out_datetime:
                # Guest has checked out but hasn't been archived yet
                # Optionally, we can archive them here to keep the system consistent
                guest.is_archived = True
                guest.front_door_pin = None
                guest.front_door_pin_id = None
                guest.room_pin_id = None
                guest.save()
                logger.info(f"Archived guest {guest.reservation_number} during check-in as check-out time {check_out_datetime} has passed")
                return redirect("rebook_guest")

            # Proceed with regular check-in logic
            request.session['reservation_number'] = guest.reservation_number

            # Generate a PIN if the guest doesn't have one AND it's on or after check-in date
            if not guest.front_door_pin:
                # Check if it's the check-in day (or later) before generating PIN
                uk_timezone = pytz.timezone("Europe/London")
                now_uk_time = timezone.now().astimezone(uk_timezone)

                # Only generate PIN on or after check-in date
                if now_uk_time.date() < guest.check_in_date:
                    # Too early - show message and redirect to room_detail without PIN
                    messages.info(request, f"Your reservation starts on {guest.check_in_date.strftime('%d %b %Y')}. You can access your PIN on that day.")
                    return redirect('room_detail', room_token=guest.secure_token)
                try:
                    front_door_lock = TTLock.objects.get(is_front_door=True)
                    room_lock = guest.assigned_room.ttlock
                    if not room_lock:
                        logger.error(f"No TTLock assigned to room {guest.assigned_room.name} for guest {guest.reservation_number}")
                        messages.error(request, f"No lock assigned to room {guest.assigned_room.name}. Please contact support.")
                        return redirect("checkin")

                    client = TTLockClient()
                    uk_timezone = pytz.timezone("Europe/London")
                    now_uk_time = timezone.now().astimezone(uk_timezone)

                    # Set start_time to NOW so PIN is immediately active in TTLock
                    # (PIN visibility to guest is controlled separately in room_detail view with early_checkin_time)
                    start_time = int(now_uk_time.timestamp() * 1000)

                    check_out_time = guest.late_checkout_time if guest.late_checkout_time else datetime.time(11, 0)
                    end_date = uk_timezone.localize(
                        datetime.datetime.combine(guest.check_out_date, check_out_time)
                    ) + datetime.timedelta(days=1)
                    end_time = int(end_date.timestamp() * 1000)
                    pin = generate_memorable_4digit_pin()  # 4-digit memorable PIN

                    # Generate PIN for front door
                    front_door_response = client.generate_temporary_pin(
                        lock_id=str(front_door_lock.lock_id),
                        pin=pin,
                        start_time=start_time,
                        end_time=end_time,
                        name=f"Front Door - {guest.assigned_room.name} - {guest.full_name} - {pin}",
                    )
                    if "keyboardPwdId" not in front_door_response:
                        logger.error(f"Failed to generate front door PIN for guest {guest.reservation_number}: {front_door_response.get('errmsg', 'Unknown error')}")
                        messages.error(request, f"Failed to generate front door PIN: {front_door_response.get('errmsg', 'Unknown error')}")
                        return redirect("checkin")
                    guest.front_door_pin = pin
                    guest.front_door_pin_id = front_door_response["keyboardPwdId"]
                    logger.info(f"Generated front door PIN {pin} for guest {guest.reservation_number} (Keyboard Password ID: {front_door_response['keyboardPwdId']})")

                    # Generate the same PIN for the room lock
                    room_response = client.generate_temporary_pin(
                        lock_id=str(room_lock.lock_id),
                        pin=pin,
                        start_time=start_time,
                        end_time=end_time,
                        name=f"Room - {guest.assigned_room.name} - {guest.full_name} - {pin}",
                    )
                    if "keyboardPwdId" not in room_response:
                        logger.error(f"Failed to generate room PIN for guest {guest.reservation_number}: {room_response.get('errmsg', 'Unknown error')}")
                        try:
                            client.delete_pin(
                                lock_id=str(front_door_lock.lock_id),
                                keyboard_pwd_id=guest.front_door_pin_id,
                            )
                            logger.info(f"Rolled back front door PIN for guest {guest.reservation_number}")
                        except Exception as e:
                            logger.error(f"Failed to roll back front door PIN for guest {guest.reservation_number}: {str(e)}")
                        guest.front_door_pin = None
                        guest.front_door_pin_id = None
                        guest.save()
                        messages.error(request, f"Failed to generate room PIN: {room_response.get('errmsg', 'Unknown error')}")
                        return redirect("checkin")
                    guest.room_pin_id = room_response["keyboardPwdId"]
                    logger.info(f"Generated room PIN {pin} for guest {guest.reservation_number} (Keyboard Password ID: {room_response['keyboardPwdId']})")
                    guest.save()

                    # Unlock the front door remotely
                    try:
                        unlock_response = client.unlock_lock(lock_id=str(front_door_lock.lock_id))
                        if "errcode" in unlock_response and unlock_response["errcode"] != 0:
                            logger.error(f"Failed to unlock front door for guest {guest.reservation_number}: {unlock_response.get('errmsg', 'Unknown error')}")
                            messages.warning(request, f"Generated PIN {pin}, but failed to unlock the front door remotely: {unlock_response.get('errmsg', 'Unknown error')}")
                        else:
                            logger.info(f"Successfully unlocked front door for guest {guest.reservation_number}")
                            messages.info(request, "The front door has been unlocked for you. You can also use your PIN or the unlock button on the next page.")
                    except Exception as e:
                        logger.error(f"Failed to unlock front door for guest {guest.reservation_number}: {str(e)}")
                        messages.warning(request, f"Generated PIN {pin}, but failed to unlock the front door remotely: {str(e)}")

                    # Unlock the room door remotely
                    try:
                        unlock_response = client.unlock_lock(lock_id=str(room_lock.lock_id))
                        if "errcode" in unlock_response and unlock_response["errcode"] != 0:
                            logger.error(f"Failed to unlock room door for guest {guest.reservation_number}: {unlock_response.get('errmsg', 'Unknown error')}")
                            messages.warning(request, f"Generated PIN {pin}, but failed to unlock the room door remotely: {unlock_response.get('errmsg', 'Unknown error')}")
                        else:
                            logger.info(f"Successfully unlocked room door for guest {guest.reservation_number}")
                            messages.info(request, "The room door has been unlocked for you.")
                    except Exception as e:
                        logger.error(f"Failed to unlock room door for guest {guest.reservation_number}: {str(e)}")
                        messages.warning(request, f"Generated PIN {pin}, but failed to unlock the room door remotely: {str(e)}")

                except TTLock.DoesNotExist:
                    logger.error("Front door lock not configured in the database.")
                    messages.error(request, "Front door lock not configured. Please contact support.")
                    return redirect("checkin")
                except Exception as e:
                    logger.error(f"Failed to generate PIN for guest {guest.reservation_number}: {str(e)}")
                    messages.error(request, f"Failed to generate PIN: {str(e)}")
                    return redirect("checkin")

            if not guest.has_access():
                messages.error(request, "Check-in period has expired or guest is archived.")
                return redirect("checkin")

            messages.success(request, f"Welcome")
            return redirect('room_detail', room_token=guest.secure_token)

        # Step 2: Check if the reservation number matches a past (archived) guest
        past_guest = Guest.objects.filter(reservation_number=reservation_number, is_archived=True).first()
        if past_guest:
            # Quick check using is_archived to avoid datetime calculation
            return redirect("rebook_guest")

        # Step 3: Fallback Check for Any Guest
        guest = Guest.objects.filter(reservation_number=reservation_number).first()
        if guest:
            # Guest exists but was either archived (already handled above) or not archived
            # Double-check the check-out status to be sure
            uk_timezone = pytz.timezone("Europe/London")
            now_uk_time = timezone.now().astimezone(uk_timezone)
            check_out_time = guest.late_checkout_time if guest.late_checkout_time else datetime.time(11, 0)
            check_out_datetime = uk_timezone.localize(
                datetime.datetime.combine(guest.check_out_date, check_out_time)
            )

            if now_uk_time > check_out_datetime:
                # Guest has checked out; ensure they are archived for consistency
                if not guest.is_archived:
                    guest.is_archived = True
                    guest.front_door_pin = None
                    guest.front_door_pin_id = None
                    guest.room_pin_id = None
                    guest.save()
                    logger.info(f"Archived guest {guest.reservation_number} during check-in as check-out time {check_out_datetime} has passed")
                return redirect("rebook_guest")

        # Step 4: Check if reservation_number matches a Reservation.booking_reference (iCal integration)
        reservation = Reservation.objects.filter(
            booking_reference=reservation_number,
            status='confirmed'
        ).first()

        if reservation:
            # Check if reservation is already enriched (has linked guest)
            if reservation.is_enriched():
                # Guest already exists, redirect to room_detail
                guest = reservation.guest
                request.session['reservation_number'] = guest.reservation_number
                messages.success(request, f"Welcome back, {guest.full_name}!")
                return redirect('room_detail', room_token=guest.secure_token)

            # Reservation found but not enriched - need contact details
            full_name = request.POST.get('full_name', '').strip()
            email = request.POST.get('email', '').strip()
            phone_number = request.POST.get('phone_number', '').strip()
            country_code = request.POST.get('country_code', '+44').strip()  # Default to UK

            # Normalize phone number to E.164 format if provided
            if phone_number:
                phone_number = normalize_phone_to_e164(phone_number, country_code)
                if phone_number:
                    is_valid, error_msg = validate_phone_number(phone_number)
                    if not is_valid:
                        error_message = _(f"Invalid phone number: {error_msg}")
                        return render(request, 'main/home.html', {
                            'error_message': error_message,
                            'reservation_number': reservation_number,
                            'full_name': full_name,
                            'email': email,
                            'phone_number': request.POST.get('phone_number', '').strip(),
                        })

            # Check if any contact details were provided
            if full_name and (email or phone_number):
                # Redirect to enrich_reservation view with all data
                request.session['reservation_to_enrich'] = {
                    'reservation_id': reservation.id,
                    'reservation_number': reservation_number,
                    'full_name': full_name,
                    'email': email,
                    'phone_number': phone_number,
                }
                return redirect('enrich_reservation')
            else:
                # Show error asking for contact details
                error_message = mark_safe(
                    _("Reservation found! To complete check-in, please provide your contact details below.") +
                    "<br><small>" +
                    _("We need at least your name and either email or phone number.") +
                    "</small>"
                )
                return render(request, 'main/checkin.html', {
                    'error': error_message,
                    'reservation_number': reservation_number,
                    'show_additional_fields': True,
                    "GOOGLE_MAPS_API_KEY": settings.GOOGLE_MAPS_API_KEY,
                })

        # Step 5: If no guest or reservation is found, show error
        request.session['reservation_number'] = reservation_number

        error_message = mark_safe(
            _("No reservation found. Please enter the correct Booking.com confirmation number.") +
            "<br>"
            '<a href="#faq-booking-confirmation" class="faq-link" style="color: #FFD700; font-weight: 400; font-size: 15px">' +
            _("Where can I find my confirmation number?") +
            '</a>'
        )

        return render(request, 'main/checkin.html', {
            'error': error_message,
            'reservation_number': reservation_number,
            "GOOGLE_MAPS_API_KEY": settings.GOOGLE_MAPS_API_KEY,
        })

    return render(request, 'main/checkin.html', {
        "GOOGLE_MAPS_API_KEY": settings.GOOGLE_MAPS_API_KEY,
        "reservation_number": request.session.get("reservation_number", ""),
    })

# Alias for backward compatibility - redirect checkin to step1
checkin = checkin_step1


def enrich_reservation(request):
    """
    Enriches a Reservation with full guest details and creates a Guest record.
    This view handles the new iCal integration flow where reservations are auto-synced
    but need manual enrichment with contact details.
    """
    # Get reservation data from session
    reservation_data = request.session.get('reservation_to_enrich')
    if not reservation_data:
        messages.error(request, "No reservation data found. Please try checking in again.")
        return redirect('checkin')

    try:
        # Get the reservation
        reservation = Reservation.objects.get(id=reservation_data['reservation_id'])

        # Validate reservation is still valid
        if reservation.status != 'confirmed':
            messages.error(request, "This reservation is no longer confirmed.")
            del request.session['reservation_to_enrich']
            return redirect('checkin')

        # Extract guest details from session
        full_name = reservation_data['full_name']
        email = reservation_data.get('email', '') or None  # Convert empty string to None
        phone_number = reservation_data.get('phone_number', '') or None  # Convert empty string to None

        if reservation.is_enriched():
            # Guest already exists (early enrichment by admin)
            # Update with guest-provided contact details
            guest = reservation.guest

            # Update name if provided (guest's input takes precedence)
            if full_name:
                guest.full_name = full_name

            # Update contact info if provided and not already set
            if phone_number and not guest.phone_number:
                guest.phone_number = phone_number
            elif phone_number:
                # Update phone if guest provides a different one
                guest.phone_number = phone_number

            if email and not guest.email:
                guest.email = email
            elif email:
                # Update email if guest provides a different one
                guest.email = email

            guest.save()
            logger.info(f"Updated existing guest {guest.id} with app check-in details for reservation {reservation.booking_reference}")

            request.session['reservation_number'] = guest.reservation_number
            del request.session['reservation_to_enrich']
            messages.success(request, f"Welcome back, {guest.full_name}! Your details have been updated.")
            return redirect('room_detail', room_token=guest.secure_token)

        # MULTI-ROOM: Find ALL reservations with same booking reference
        all_reservations = Reservation.objects.filter(
            booking_reference=reservation.booking_reference,
            status='confirmed',
            guest__isnull=True  # Only unenriched reservations
        ).select_related('room')

        # Create new Guest record with reservation details
        guest = Guest.objects.create(
            full_name=full_name,
            email=email,
            phone_number=phone_number,
            reservation_number=reservation.booking_reference,
            check_in_date=reservation.check_in_date,
            check_out_date=reservation.check_out_date,
            assigned_room=reservation.room,
            early_checkin_time=reservation.early_checkin_time,  # Copy from reservation
            late_checkout_time=reservation.late_checkout_time,  # Copy from reservation
        )
        logger.info(f"Created new guest {guest.id} for reservation {reservation.booking_reference}")

        # MULTI-ROOM: Link ALL reservations to this guest
        room_count = 0
        for res in all_reservations:
            res.guest = guest
            res.save()
            room_count += 1
            logger.info(f"Linked reservation {res.id} ({res.room.name}) to guest {guest.id}")
        
        if room_count > 1:
            logger.info(f"Multi-room booking detected: {room_count} rooms linked to guest {guest.id}")

        # Check if it's the check-in day (or later) before generating PIN
        uk_timezone = pytz.timezone("Europe/London")
        now_uk_time = timezone.now().astimezone(uk_timezone)

        # Only generate PIN on or after check-in date
        if now_uk_time.date() < guest.check_in_date:
            # Too early - all reservations already linked above
            # No need to link reservation again
            request.session['reservation_number'] = guest.reservation_number
            del request.session['reservation_to_enrich']
            logger.info(f"Guest {guest.id} created but PIN generation deferred until check-in date {guest.check_in_date}")
            messages.info(request, f"Your reservation starts on {guest.check_in_date.strftime('%d %b %Y')}. You can access your PIN on that day.")
            return redirect('room_detail', room_token=guest.secure_token)

        # Generate TTLock PINs (reuse logic from checkin view)
        try:
            front_door_lock = TTLock.objects.get(is_front_door=True)
            room_lock = guest.assigned_room.ttlock
            if not room_lock:
                logger.error(f"No TTLock assigned to room {guest.assigned_room.name} for guest {guest.reservation_number}")
                messages.error(request, f"No lock assigned to room {guest.assigned_room.name}. Please contact support.")
                guest.delete()  # Rollback guest creation
                # Clear enrichment data but keep reservation_number for retry
                if 'reservation_to_enrich' in request.session:
                    del request.session['reservation_to_enrich']
                return redirect("checkin")

            client = TTLockClient()
            uk_timezone = pytz.timezone("Europe/London")
            now_uk_time = timezone.now().astimezone(uk_timezone)

            # Set start_time to NOW so PIN is immediately active
            start_time = int(now_uk_time.timestamp() * 1000)

            check_out_time = guest.late_checkout_time if guest.late_checkout_time else datetime.time(11, 0)
            end_date = uk_timezone.localize(
                datetime.datetime.combine(guest.check_out_date, check_out_time)
            ) + datetime.timedelta(days=1)
            end_time = int(end_date.timestamp() * 1000)
            pin = generate_memorable_4digit_pin()  # 4-digit memorable PIN

            # Generate PIN for front door
            front_door_response = client.generate_temporary_pin(
                lock_id=str(front_door_lock.lock_id),
                pin=pin,
                start_time=start_time,
                end_time=end_time,
                name=f"Front Door - {guest.assigned_room.name} - {guest.full_name} - {pin}",
            )
            if "keyboardPwdId" not in front_door_response:
                logger.error(f"Failed to generate front door PIN for guest {guest.reservation_number}: {front_door_response.get('errmsg', 'Unknown error')}")
                messages.error(request, f"Failed to generate front door PIN: {front_door_response.get('errmsg', 'Unknown error')}")
                guest.delete()  # Rollback guest creation
                # Clear enrichment data but keep reservation_number for retry
                if 'reservation_to_enrich' in request.session:
                    del request.session['reservation_to_enrich']
                return redirect("checkin")
            guest.front_door_pin = pin
            guest.front_door_pin_id = front_door_response["keyboardPwdId"]
            logger.info(f"Generated front door PIN {pin} for guest {guest.reservation_number} (Keyboard Password ID: {front_door_response['keyboardPwdId']})")

            # MULTI-ROOM: Generate the same PIN for ALL room locks
            room_pin_ids = []
            failed_rooms = []
            
            for res in all_reservations:
                room_lock = res.room.ttlock
                if not room_lock:
                    logger.warning(f"No TTLock assigned to room {res.room.name} - skipping PIN generation")
                    failed_rooms.append(res.room.name)
                    continue
                
                room_response = client.generate_temporary_pin(
                    lock_id=str(room_lock.lock_id),
                    pin=pin,
                    start_time=start_time,
                    end_time=end_time,
                    name=f"Room - {res.room.name} - {guest.full_name} - {pin}",
                )
                
                if "keyboardPwdId" not in room_response:
                    logger.error(f"Failed to generate room PIN for {res.room.name}: {room_response.get('errmsg', 'Unknown error')}")
                    failed_rooms.append(res.room.name)
                else:
                    room_pin_ids.append({
                        'room_name': res.room.name,
                        'pin_id': room_response["keyboardPwdId"]
                    })
                    logger.info(f"Generated room PIN {pin} for {res.room.name} (Keyboard Password ID: {room_response['keyboardPwdId']})")
            
            if failed_rooms:
                # Rollback: Delete all created PINs
                logger.error(f"Failed to generate PINs for rooms: {', '.join(failed_rooms)}. Rolling back...")
                try:
                    client.delete_pin(
                        lock_id=str(front_door_lock.lock_id),
                        keyboard_pwd_id=guest.front_door_pin_id,
                    )
                except Exception as e:
                    logger.error(f"Failed to roll back front door PIN: {str(e)}")
                
                for pin_info in room_pin_ids:
                    try:
                        # Find the room lock to delete PIN
                        for res in all_reservations:
                            if res.room.name == pin_info['room_name'] and res.room.ttlock:
                                client.delete_pin(
                                    lock_id=str(res.room.ttlock.lock_id),
                                    keyboard_pwd_id=pin_info['pin_id'],
                                )
                                break
                    except Exception as e:
                        logger.error(f"Failed to roll back room PIN for {pin_info['room_name']}: {str(e)}")
                
                guest.delete()  # Rollback guest creation
                messages.error(request, f"Failed to generate PINs for some rooms. Please contact support.")
                if 'reservation_to_enrich' in request.session:
                    del request.session['reservation_to_enrich']
                return redirect("checkin")
            
            # Store the first room's PIN ID (for backward compatibility with Guest.room_pin_id field)
            guest.room_pin_id = room_pin_ids[0]['pin_id'] if room_pin_ids else None
            guest.save()
            
            if room_count > 1:
                logger.info(f"Multi-room PIN generation complete: {room_count} rooms configured with PIN {pin}")

            # Unlock the front door remotely
            try:
                unlock_response = client.unlock_lock(lock_id=str(front_door_lock.lock_id))
                if "errcode" in unlock_response and unlock_response["errcode"] != 0:
                    logger.error(f"Failed to unlock front door for guest {guest.reservation_number}: {unlock_response.get('errmsg', 'Unknown error')}")
                    messages.warning(request, f"Generated PIN {pin}, but failed to unlock the front door remotely: {unlock_response.get('errmsg', 'Unknown error')}")
                else:
                    logger.info(f"Successfully unlocked front door for guest {guest.reservation_number}")
                    messages.info(request, "The front door has been unlocked for you. You can also use your PIN or the unlock button on the next page.")
            except Exception as e:
                logger.error(f"Failed to unlock front door for guest {guest.reservation_number}: {str(e)}")
                messages.warning(request, f"Generated PIN {pin}, but failed to unlock the front door remotely: {str(e)}")

            # MULTI-ROOM: Unlock ALL room doors remotely
            unlocked_rooms = []
            failed_unlocks = []
            for res in all_reservations:
                if res.room.ttlock:
                    try:
                        unlock_response = client.unlock_lock(lock_id=str(res.room.ttlock.lock_id))
                        if "errcode" in unlock_response and unlock_response["errcode"] != 0:
                            logger.error(f"Failed to unlock {res.room.name} for guest {guest.reservation_number}: {unlock_response.get('errmsg', 'Unknown error')}")
                            failed_unlocks.append(res.room.name)
                        else:
                            logger.info(f"Successfully unlocked {res.room.name} for guest {guest.reservation_number}")
                            unlocked_rooms.append(res.room.name)
                    except Exception as e:
                        logger.error(f"Failed to unlock {res.room.name} for guest {guest.reservation_number}: {str(e)}")
                        failed_unlocks.append(res.room.name)
            
            if unlocked_rooms:
                rooms_str = ", ".join(unlocked_rooms)
                messages.info(request, f"Remote unlock successful for: {rooms_str}")
            if failed_unlocks:
                rooms_str = ", ".join(failed_unlocks)
                messages.warning(request, f"Failed to unlock: {rooms_str}. You can use your PIN or the unlock button on the room page.")

        except TTLock.DoesNotExist:
            logger.error("Front door lock not configured in the database.")
            messages.error(request, "Front door lock not configured. Please contact support.")
            guest.delete()  # Rollback guest creation
            # Clear enrichment data but keep reservation_number for retry
            if 'reservation_to_enrich' in request.session:
                del request.session['reservation_to_enrich']
            return redirect("checkin")
        except Exception as e:
            logger.error(f"Failed to generate PIN for guest {guest.reservation_number}: {str(e)}")
            messages.error(request, f"Failed to generate PIN: {str(e)}")
            guest.delete()  # Rollback guest creation
            # Clear enrichment data but keep reservation_number for retry
            if 'reservation_to_enrich' in request.session:
                del request.session['reservation_to_enrich']
            return redirect("checkin")

        # All reservations already linked at line 472-476
        # Store reservation_number in session and clean up enrichment data
        request.session['reservation_number'] = guest.reservation_number
        del request.session['reservation_to_enrich']

        # Redirect to room_detail
        messages.success(request, f"Welcome, {guest.full_name}!")
        return redirect('room_detail', room_token=guest.secure_token)

    except Reservation.DoesNotExist:
        messages.error(request, "Reservation not found. Please try checking in again.")
        if 'reservation_to_enrich' in request.session:
            del request.session['reservation_to_enrich']
        return redirect('checkin')
    except IntegrityError as e:
        logger.error(f"Database integrity error during reservation enrichment: {str(e)}")
        messages.error(request, "A guest with this booking reference already exists. Please contact support if you need assistance.")
        if 'reservation_to_enrich' in request.session:
            del request.session['reservation_to_enrich']
        return redirect('checkin')
    except Exception as e:
        logger.error(f"Unexpected error during reservation enrichment: {str(e)}")
        messages.error(request, f"An error occurred during check-in: {str(e)}")
        if 'reservation_to_enrich' in request.session:
            del request.session['reservation_to_enrich']
        return redirect('checkin')

def room_detail(request, room_token):
    reservation_number = request.session.get("reservation_number", None)
    guest = Guest.objects.filter(secure_token=room_token).first()

    if not guest or not reservation_number or guest.reservation_number != reservation_number:
        return redirect("unauthorized")

    room = guest.assigned_room
    uk_timezone = pytz.timezone("Europe/London")
    now_uk_time = timezone.now().astimezone(uk_timezone)

    check_in_time = guest.early_checkin_time if guest.early_checkin_time else datetime.time(14, 0)
    try:
        check_in_datetime = uk_timezone.localize(
            datetime.datetime.combine(guest.check_in_date, check_in_time)
        )
    except Exception as e:
        logger.error(f"Error localizing check-in datetime for guest {guest.reservation_number}: {str(e)}")
        # Fallback: Use replace instead of localize for DST safety
        check_in_datetime = datetime.datetime.combine(guest.check_in_date, check_in_time).replace(tzinfo=uk_timezone)

    check_out_time = guest.late_checkout_time if guest.late_checkout_time else datetime.time(11, 0)
    try:
        check_out_datetime = uk_timezone.localize(
            datetime.datetime.combine(guest.check_out_date, check_out_time)
        )
    except Exception as e:
        logger.error(f"Error localizing check-out datetime for guest {guest.reservation_number}: {str(e)}")
        # Fallback: Use replace instead of localize for DST safety
        check_out_datetime = datetime.datetime.combine(guest.check_out_date, check_out_time).replace(tzinfo=uk_timezone)

    if now_uk_time > check_out_datetime:
        request.session.pop("reservation_number", None)
        return redirect("rebook_guest")

    enforce_2pm_rule = now_uk_time < check_in_datetime

    # Debug logging for early check-in troubleshooting
    logger.info(f"Guest {guest.reservation_number} - Check-in time comparison:")
    logger.info(f"  Current UK time: {now_uk_time}")
    logger.info(f"  Check-in datetime: {check_in_datetime}")
    logger.info(f"  Early check-in time set: {guest.early_checkin_time}")
    logger.info(f"  Enforce 2PM rule: {enforce_2pm_rule}")
    logger.info(f"  Show PIN: {not enforce_2pm_rule}")

    # Add wakeup prefix to PIN for display (2 dummy digits + 4 actual PIN digits)
    display_pin = add_wakeup_prefix(guest.front_door_pin) if guest.front_door_pin else None

    # MULTI-ROOM: Get all reservations for this guest
    guest_reservations = guest.reservations.all().select_related('room')
    is_multiroom = guest_reservations.count() > 1
    
    # Build list of rooms with their details
    guest_rooms = []
    for res in guest_reservations:
        guest_rooms.append({
            'room': res.room,
            'reservation': res,
            'check_in': res.check_in_date,
            'check_out': res.check_out_date,
        })

    if request.method == "GET" and request.GET.get('modal'):
        return render(request, "main/room_detail.html", {
            "room": room,
            "guest": guest,
            "image_url": room.image or None,
            "expiration_message": f"Your access will expire on {guest.check_out_date.strftime('%d %b %Y')} at {check_out_time.strftime('%I:%M %p')}.",
            "show_pin": not enforce_2pm_rule,
            "front_door_pin": display_pin,
            "id_uploads": guest.id_uploads.all(),
        }, content_type="text/html", status=200)

    if request.method == "POST":
        if "upload_id" in request.POST and request.FILES.get('id_image'):
            id_image = request.FILES['id_image']
            logger.debug(f"Received file: {id_image.name}, size: {id_image.size} bytes, content_type: {id_image.content_type}")
            if not id_image or id_image.size == 0:
                logger.error(f"Empty file received for guest {guest.reservation_number}")
                messages.error(request, "No file was uploaded or the file is empty. Please try again.")
                return redirect('room_detail', room_token=room_token)

            upload_count = guest.id_uploads.count()
            if upload_count >= 3:
                messages.error(request, "You’ve reached the maximum of 3 ID uploads.")
                return redirect('room_detail', room_token=room_token)

            if id_image.size > 5 * 1024 * 1024:
                messages.error(request, "ID image must be under 5MB.")
                return redirect('room_detail', room_token=room_token)
            if not id_image.content_type.startswith('image/'):
                messages.error(request, "Please upload a valid image file (e.g., JPG, PNG).")
                return redirect('room_detail', room_token=room_token)

            try:
                # Upload to Cloudinary (already configured in settings.py)
                upload_response = cloudinary_upload(
                    id_image,
                    folder=f"guest_ids/{now_uk_time.year}/{now_uk_time.month}/{now_uk_time.day}/",
                    resource_type="image"
                )

                # Save the Cloudinary URL to the model
                if 'url' in upload_response:
                    guest_upload = GuestIDUpload(
                        guest=guest,
                        id_image=upload_response['url']  # Store the Cloudinary URL directly
                    )
                    guest_upload.save()
                    logger.info(f"Successfully saved ID for guest {guest.reservation_number}: {guest_upload.id_image}")
                    messages.success(request, "ID uploaded successfully!")
                else:
                    logger.error(f"Cloudinary upload failed for guest {guest.reservation_number}: {upload_response.get('error', 'Unknown error')}")
                    messages.error(request, "Failed to upload ID to Cloudinary. Please try again.")
                    return redirect('room_detail', room_token=room_token)

            except Exception as e:
                logger.error(f"Error uploading ID for guest {guest.reservation_number}: {str(e)}")
                messages.error(request, f"An error occurred while uploading your ID: {str(e)}. Please try again.")
                return redirect('room_detail', room_token=room_token)

            return redirect('room_detail', room_token=room_token)

        if "unlock_door" in request.POST:
            if getattr(request, 'limited', False):
                logger.warning(f"Rate limit exceeded for IP {request.META.get('REMOTE_ADDR')} on unlock attempt for guest {guest.reservation_number}")
                return JsonResponse({"error": "Too many attempts, please wait a moment."}, status=429)

            try:
                front_door_lock = TTLock.objects.get(is_front_door=True)
                room_lock = guest.assigned_room.ttlock
                client = TTLockClient()
                max_retries = 3
                door_type = request.POST.get("door_type")

                if door_type == "front":
                    for attempt in range(max_retries):
                        try:
                            unlock_response = client.unlock_lock(lock_id=str(front_door_lock.lock_id))
                            if "errcode" in unlock_response and unlock_response["errcode"] != 0:
                                logger.error(f"Failed to unlock front door for guest {guest.reservation_number}: {unlock_response.get('errmsg', 'Unknown error')}")
                                if attempt == max_retries - 1:
                                    return JsonResponse({"error": "Failed to unlock the front door. Please try again or contact support."}, status=400)
                                else:
                                    logger.info(f"Retrying unlock front door for guest {guest.reservation_number} (attempt {attempt + 1}/{max_retries})")
                                    continue
                            else:
                                logger.info(f"Successfully unlocked front door for guest {guest.reservation_number}")
                                return JsonResponse({"success": "The front door has been unlocked for you."})
                        except Exception as e:
                            logger.error(f"Failed to unlock front door for guest {guest.reservation_number}: {str(e)}")
                            if attempt == max_retries - 1:
                                return JsonResponse({"error": "Failed to unlock the front door. Please try again or contact support."}, status=400)
                            else:
                                logger.info(f"Retrying unlock front door for guest {guest.reservation_number} (attempt {attempt + 1}/{max_retries})")
                                continue
                elif door_type == "room" and room_lock:
                    for attempt in range(max_retries):
                        try:
                            unlock_response = client.unlock_lock(lock_id=str(room_lock.lock_id))
                            if "errcode" in unlock_response and unlock_response["errcode"] != 0:
                                logger.error(f"Failed to unlock room door for guest {guest.reservation_number}: {unlock_response.get('errmsg', 'Unknown error')}")
                                if attempt == max_retries - 1:
                                    return JsonResponse({"error": "Failed to unlock the room door. Please try again or contact support."}, status=400)
                                else:
                                    logger.info(f"Retrying unlock room door for guest {guest.reservation_number} (attempt {attempt + 1}/{max_retries})")
                                    continue
                            else:
                                logger.info(f"Successfully unlocked room door for guest {guest.reservation_number}")
                                return JsonResponse({"success": "The room door has been unlocked for you."})
                        except Exception as e:
                            logger.error(f"Failed to unlock room door for guest {guest.reservation_number}: {str(e)}")
                            if attempt == max_retries - 1:
                                return JsonResponse({"error": "Failed to unlock the room door. Please try again or contact support."}, status=400)
                            else:
                                logger.info(f"Retrying unlock room door for guest {guest.reservation_number} (attempt {attempt + 1}/{max_retries})")
                                continue
                else:
                    logger.warning(f"Invalid door_type or no room lock assigned for guest {guest.reservation_number}")
                    return JsonResponse({"error": "Invalid unlock request or no room lock assigned. Please contact support."}, status=400)

            except TTLock.DoesNotExist:
                logger.error("Front door lock not configured in the database.")
                return JsonResponse({"error": "Front door lock not configured. Please contact support."}, status=400)

    return render(
        request,
        "main/room_detail.html",
        {
            "room": room,
            "guest": guest,
            "image_url": room.image or None,
            "expiration_message": f"Your access will expire on {guest.check_out_date.strftime('%d %b %Y')} at {check_out_time.strftime('%I:%M %p')}.",
            "show_pin": not enforce_2pm_rule,
            "front_door_pin": display_pin,
            "id_uploads": guest.id_uploads.all(),
            # MULTI-ROOM: Add multi-room booking info
            "guest_rooms": guest_rooms,
            "is_multiroom": is_multiroom,
        },
    )

room_detail = ratelimit(key='ip', rate='6/m', method='POST', block=True)(room_detail)

@ratelimit(key='ip', rate='3/m', method='POST', block=True)
def report_pin_issue(request):
    if request.method == 'POST':
        reservation_number = request.session.get("reservation_number", None)
        
        if not reservation_number:
            return JsonResponse({"error": "No active reservation found."}, status=400)

        try:
            guest = Guest.objects.get(reservation_number=reservation_number)
        except Guest.DoesNotExist:
            return JsonResponse({"error": "Guest not found."}, status=404)

        subject = "🔴 URGENT: Guest Reporting PIN Issue!"
        message = (
            f"Guest Name: {guest.full_name}\n"
            f"Phone Number: {guest.phone_number if guest.phone_number else 'Not provided'}\n"
            f"Reservation Number: {guest.reservation_number}\n"
            f"Room: {guest.assigned_room.name}\n"
            f"Check-in: {guest.check_in_date.strftime('%d %b %Y')}\n"
            f"Check-out: {guest.check_out_date.strftime('%d %b %Y')}\n\n"
            "🔴 Guest is unable to use their PIN and requires urgent assistance.\n\n"
            "Please contact the guest as soon as possible."
        )

        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                ["easybulb@gmail.com"],
                fail_silently=False,
            )
        except Exception as e:
            logger.error(f"Failed to send PIN issue email for guest {guest.reservation_number}: {str(e)}")
            return JsonResponse({"error": f"Email failed: {str(e)}"}, status=500)

        logger.info(f"Sent PIN issue email for guest {guest.reservation_number}")
        return JsonResponse({"success": "Admin has been notified. We will contact you shortly. If you do not hear from us please call +44 0 7539029629"})
    
    return JsonResponse({"error": "Invalid request method."}, status=405)

def rebook_guest(request):
    return render(request, 'main/rebook_guest.html', {
        'booking_link': "https://www.booking.com/hotel/gb/double-bed-room-with-on-suite-near-etihad-manchester-city.en-gb.html?label=gen173nr-1BCAsoUEI5ZG91YmxlLWJlZC1yb29tLXdpdGgtb24tc3VpdGUtbmVhci1ldGloYWQtbWFuY2hlc3Rlci1jaXR5SDNYBGhQiAEBmAEJuAEYyAEM2AEB6AEBiAIBqAIEuAKSxdG9BsACAdICJGM2MGZlZWIxLWFhN2QtNGNjMC05MGVjLWMxNWYwZmM1ZDcyMdgCBeACAQ&sid=7613f9a14781ff8d39041ce2257bfde6&dist=0&keep_landing=1&sb_price_type=total&type=total&",
    })

@ratelimit(key='ip', rate='3/m', method='POST', block=True)
def contact(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        message = request.POST.get('message')
        recaptcha_response = request.POST.get('g-recaptcha-response')

        recaptcha_secret = settings.RECAPTCHA_PRIVATE_KEY
        recaptcha_url = "https://www.google.com/recaptcha/api/siteverify"
        recaptcha_data = {'secret': recaptcha_secret, 'response': recaptcha_response}
        recaptcha_verify = requests.post(recaptcha_url, data=recaptcha_data).json()

        if not recaptcha_verify.get('success'):
            return render(request, 'main/contact.html', {
                'error': "reCAPTCHA verification failed. Please try again.",
                "GOOGLE_MAPS_API_KEY": settings.GOOGLE_MAPS_API_KEY,
                "RECAPTCHA_PUBLIC_KEY": settings.RECAPTCHA_PUBLIC_KEY,
            })

        subject = f"Pick-A-Rooms Contact Us Message from {name}"
        body = f"Name: {name}\nEmail: {email}\n\nMessage:\n{message}"

        try:
            email_message = EmailMessage(
                subject=subject,
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=['easybulb@gmail.com'],
                reply_to=[email]
            )
            email_message.send()
        except BadHeaderError:
            return HttpResponse("Invalid header found.", status=400)
        except Exception as e:
            logger.error(f"Failed to send contact email from {email}: {str(e)}")
            return HttpResponse(f"Error: {str(e)}", status=500)

        return render(request, 'main/contact.html', {
            'success': True,
            "GOOGLE_MAPS_API_KEY": settings.GOOGLE_MAPS_API_KEY,
            "RECAPTCHA_PUBLIC_KEY": settings.RECAPTCHA_PUBLIC_KEY,
        })

    return render(request, 'main/contact.html', {
        "GOOGLE_MAPS_API_KEY": settings.GOOGLE_MAPS_API_KEY,
        "RECAPTCHA_PUBLIC_KEY": settings.RECAPTCHA_PUBLIC_KEY,
    })

class AdminLoginView(LoginView):
    template_name = 'main/admin_login.html'

    def get_success_url(self):
        return '/admin-page/'

    def form_valid(self, form):
        user = form.get_user()
        if not user.is_staff:  # Ensure only staff users (admins) can log in
            messages.error(self.request, "You do not have permission to access the admin dashboard.")
            return redirect('admin_login')
        return super().form_valid(form)

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.has_perm('main.view_admin_dashboard'), login_url='/unauthorized/')
def admin_page(request):
    """Admin Dashboard to manage guests, rooms, and assignments."""
    # Note: Guest archiving is now handled by Celery task 'archive_past_guests' (runs every hour)
    # This removes the performance bottleneck of checking all guests on every page load

    # Get today's date for filtering
    today = date.today()

    # Get today's enriched guests (checking in today only)
    todays_guests = Guest.objects.filter(
        is_archived=False,
        check_in_date=today
    ).select_related('assigned_room').order_by('full_name')

    # Get today's unenriched reservations (checking in today only)
    todays_reservations = Reservation.objects.filter(
        check_in_date=today,
        status='confirmed',
        guest__isnull=True  # Not yet enriched
    ).select_related('room').order_by('booking_reference')

    # Combine into unified list for "Today's Guests" table
    todays_entries = []

    # Add enriched guests
    for guest in todays_guests:
        todays_entries.append({
            'type': 'guest',
            'id': guest.id,
            'guest_id': guest.id,
            'object': guest,
            'is_enriched': True,
            'is_returning': guest.is_returning,
            'full_name': guest.full_name,
            'phone_number': guest.phone_number or '---',
            'email': guest.email or '---',
            'booking_ref': guest.reservation_number,
            'room': guest.assigned_room,
            'pin': guest.front_door_pin,
            'check_in_date': guest.check_in_date,
            'check_out_date': guest.check_out_date,
            'early_checkin_time': guest.early_checkin_time,
            'late_checkout_time': guest.late_checkout_time,
            'platform': '👤 Manual',  # Manually created or from old system
            'secure_token': guest.secure_token,
        })

    # Add unenriched reservations
    for reservation in todays_reservations:
        platform_badge = '📘 Booking.com' if reservation.platform == 'booking' else '🏠 Airbnb'

        todays_entries.append({
            'type': 'reservation',
            'id': reservation.id,
            'reservation_id': reservation.id,
            'object': reservation,
            'is_enriched': False,
            'is_returning': False,
            'full_name': reservation.guest_name or '(Guest Name Not Available)',
            'phone_number': '---',
            'email': '---',
            'booking_ref': reservation.booking_reference or '---',
            'room': reservation.room,
            'pin': None,
            'check_in_date': reservation.check_in_date,
            'check_out_date': reservation.check_out_date,
            'early_checkin_time': reservation.early_checkin_time,  # Include from reservation
            'late_checkout_time': reservation.late_checkout_time,  # Include from reservation
                        'platform': platform_badge,
            'platform_raw': reservation.platform,
        })

    # Get current guests data (all active stays - not just today's check-ins)
    current_guests_data = get_current_guests_data(today)
    current_entries = build_entries_list(
        current_guests_data['current_guests'],
        current_guests_data['current_reservations']
    )

    # Add status and night progress to both todays_entries and current_entries
    for entry in todays_entries:
        entry['status'] = get_guest_status(entry, today)
        entry['night_progress'] = get_night_progress(entry['check_in_date'], entry['check_out_date'], today)

    for entry in current_entries:
        entry['status'] = get_guest_status(entry, today)
        entry['night_progress'] = get_night_progress(entry['check_in_date'], entry['check_out_date'], today)

    # Keep old guests query for backward compatibility (if needed elsewhere)
    guests = Guest.objects.filter(is_archived=False).order_by('check_in_date')

    check_in_date = request.POST.get('check_in_date') or request.GET.get('check_in_date')
    check_out_date = request.POST.get('check_out_date') or request.GET.get('check_out_date')

    if check_in_date and check_out_date:
        check_in_date = date.fromisoformat(check_in_date)
        check_out_date = date.fromisoformat(check_out_date)
        available_rooms = get_available_rooms(check_in_date, check_out_date)
    else:
        available_rooms = Room.objects.all()

    if request.method == 'POST':
        # Check if this is an iCal configuration submission
        if 'ical_action' in request.POST:
            action = request.POST.get('ical_action')
            room_id = request.POST.get('ical_room_id')
            platform = request.POST.get('platform', 'booking')  # 'booking' or 'airbnb'

            if action == 'save_ical':
                ical_url = request.POST.get('ical_url', '').strip()
                is_active = request.POST.get('is_active') == 'on'

                try:
                    room = Room.objects.get(id=room_id)
                    config, created = RoomICalConfig.objects.get_or_create(room=room)

                    # Update platform-specific fields
                    if platform == 'booking':
                        config.booking_ical_url = ical_url
                        config.booking_active = is_active
                    elif platform == 'airbnb':
                        config.airbnb_ical_url = ical_url
                        config.airbnb_active = is_active

                    config.save()

                    platform_name = "Booking.com" if platform == 'booking' else "Airbnb"
                    action_text = "created" if created else "updated"
                    messages.success(request, f"{platform_name} configuration {action_text} for {room.name}.")
                    logger.info(f"{platform_name} config {action_text} for room {room.name} by {request.user.username}")
                except Room.DoesNotExist:
                    messages.error(request, "Room not found.")
                except Exception as e:
                    messages.error(request, f"Failed to save iCal configuration: {str(e)}")
                    logger.error(f"Failed to save iCal config for room {room_id}: {str(e)}")

                return redirect('admin_page')

            elif action == 'sync_now':
                try:
                    config = RoomICalConfig.objects.get(id=request.POST.get('config_id'))
                    # Import the task here to avoid circular imports
                    from main.tasks import sync_room_ical_feed
                    sync_room_ical_feed.delay(config.id, platform=platform)
                    platform_name = "Booking.com" if platform == 'booking' else "Airbnb"
                    messages.success(request, f"{platform_name} sync started for {config.room.name}. Check back in a moment.")
                    logger.info(f"Manual {platform_name} sync triggered for {config.room.name} by {request.user.username}")
                except RoomICalConfig.DoesNotExist:
                    messages.error(request, "iCal configuration not found.")
                except Exception as e:
                    messages.error(request, f"Failed to trigger sync: {str(e)}")
                    logger.error(f"Failed to trigger iCal sync: {str(e)}")

                return redirect('admin_page')

        # Original guest creation logic
        reservation_number = request.POST.get('reservation_number', '').strip()
        phone_number = request.POST.get('phone_number', '').strip() or None
        email = request.POST.get('email', '').strip() or None
        full_name = request.POST.get('full_name', 'Guest').strip()
        room_id = request.POST.get('room')
        early_checkin_time = request.POST.get('early_checkin_time')
        late_checkout_time = request.POST.get('late_checkout_time')

        # Validate reservation_number length
        if len(reservation_number) > 15:
            messages.error(request, "Reservation number must not exceed 15 characters.")
            return redirect('admin_page')

        if not reservation_number:
            messages.error(request, "Reservation number is required.")
            return redirect('admin_page')

        # Normalize and validate phone number
        if phone_number:
            # Normalize to E.164 format (default UK +44)
            phone_number = normalize_phone_to_e164(phone_number, '+44')
            if phone_number:
                is_valid, error_msg = validate_phone_number(phone_number)
                if not is_valid:
                    messages.error(request, f"Invalid phone number: {error_msg}")
                    return redirect('admin_page')

        try:
            room = Room.objects.get(id=room_id)

            if Guest.objects.filter(reservation_number=reservation_number).exists():
                messages.error(request, "Reservation number already exists.")
                return redirect('admin_page')

            previous_stays = Guest.objects.filter(
                Q(full_name__iexact=full_name)
            ).exists()

            # Generate PIN via TTLock API
            front_door_lock = TTLock.objects.filter(is_front_door=True).first()
            room_lock = room.ttlock
            if not front_door_lock:
                logger.error("Front door lock not configured in the database.")
                messages.error(request, "Front door lock not configured. Please contact support.")
                return redirect('admin_page')
            if not room_lock:
                logger.error(f"No TTLock assigned to room {room.name}")
                messages.error(request, f"No lock assigned to room {room.name}. Please contact support.")
                return redirect('admin_page')

            pin = generate_memorable_4digit_pin()  # 4-digit memorable PIN
            uk_timezone = pytz.timezone("Europe/London")
            now_uk_time = timezone.now().astimezone(uk_timezone)

            # Set start_time to NOW so PIN is immediately active in TTLock
            # (PIN visibility to guest is controlled separately in room_detail view with early_checkin_time)
            start_time = int(now_uk_time.timestamp() * 1000)

            # Set end time based on late_checkout_time (default to 11:00 AM if not set)
            if late_checkout_time:
                try:
                    late_checkout_time = datetime.datetime.strptime(late_checkout_time, '%H:%M').time()
                except ValueError:
                    messages.error(request, "Invalid late check-out time format. Use HH:MM (e.g., 12:00).")
                    return redirect('admin_page')
            else:
                late_checkout_time = time(11, 0)
            end_date = uk_timezone.localize(
                datetime.datetime.combine(check_out_date, late_checkout_time)
            ) + datetime.timedelta(days=1)
            end_time = int(end_date.timestamp() * 1000)

            ttlock_client = TTLockClient()
            try:
                # Generate PIN for front door
                front_door_response = ttlock_client.generate_temporary_pin(
                    lock_id=front_door_lock.lock_id,
                    pin=pin,
                    start_time=start_time,
                    end_time=end_time,
                    name=f"Front Door - {room.name} - {full_name} - {pin}",
                )
                if "keyboardPwdId" not in front_door_response:
                    logger.error(f"Failed to generate front door PIN for guest {reservation_number}: {front_door_response.get('errmsg', 'Unknown error')}")
                    messages.error(request, f"Failed to generate front door PIN: {front_door_response.get('errmsg', 'Unknown error')}")
                    return redirect('admin_page')
                keyboard_pwd_id_front = front_door_response["keyboardPwdId"]

                # Generate the same PIN for the room lock
                room_response = ttlock_client.generate_temporary_pin(
                    lock_id=room_lock.lock_id,
                    pin=pin,
                    start_time=start_time,
                    end_time=end_time,
                    name=f"Room - {room.name} - {full_name} - {pin}",
                )
                if "keyboardPwdId" not in room_response:
                    logger.error(f"Failed to generate room PIN for guest {reservation_number}: {room_response.get('errmsg', 'Unknown error')}")
                    # Roll back the front door PIN
                    try:
                        ttlock_client.delete_pin(
                            lock_id=front_door_lock.lock_id,
                            keyboard_pwd_id=keyboard_pwd_id_front,
                        )
                    except Exception as e:
                        logger.error(f"Failed to roll back front door PIN for guest {reservation_number}: {str(e)}")
                    messages.error(request, f"Failed to generate room PIN: {room_response.get('errmsg', 'Unknown error')}")
                    return redirect('admin_page')
                keyboard_pwd_id_room = room_response["keyboardPwdId"]

                # Create the guest with the generated PIN
                guest = Guest.objects.create(
                    full_name=full_name,
                    phone_number=phone_number,
                    email=email,
                    reservation_number=reservation_number,
                    check_in_date=check_in_date,
                    check_out_date=check_out_date,
                    assigned_room=room,
                    is_returning=previous_stays,
                    front_door_pin=pin,
                    front_door_pin_id=keyboard_pwd_id_front,
                    room_pin_id=keyboard_pwd_id_room,
                    early_checkin_time=early_checkin_time if early_checkin_time else None,
                    late_checkout_time=late_checkout_time if late_checkout_time != time(11, 0) else None,
                )
                # Log the guest creation action
                AuditLog.objects.create(
                    user=request.user,
                    action="create_guest",
                    object_type="Guest",
                    object_id=guest.id,
                    details=f"Created guest {guest.full_name} (Reservation: {reservation_number}) with PIN {pin}"
                )
                messages.success(request, f"Guest {guest.full_name} added successfully! PIN (for both front door and room): {pin}. They can also unlock the doors remotely during check-in or from the room detail page.")
            except Exception as e:
                logger.error(f"Failed to generate PIN for guest {reservation_number}: {str(e)}")
                messages.error(request, f"Failed to generate PIN: {str(e)}")
                return redirect('admin_page')

            return redirect('admin_page')

        except Room.DoesNotExist:
            logger.error(f"Invalid room ID {room_id} selected for guest {reservation_number}")
            messages.error(request, "Invalid room selected.")
        except IntegrityError:
            logger.error(f"Reservation number {reservation_number} already exists.")
            messages.error(request, "Reservation number already exists.")
            return redirect('admin_page')

    # Get iCal configurations for all rooms
    ical_configs = {}
    for room in available_rooms:
        try:
            config = RoomICalConfig.objects.get(room=room)
            ical_configs[room.id] = config
        except RoomICalConfig.DoesNotExist:
            ical_configs[room.id] = None

    # Detect overlapping reservations (different platforms, same room, overlapping dates)
    overlapping_warnings = []

    for room in available_rooms:
        # Get all confirmed reservations for this room
        reservations = Reservation.objects.filter(
            room=room,
            status='confirmed'
        ).order_by('check_in_date')

        # Check for overlaps between different platforms
        for i, res1 in enumerate(reservations):
            for res2 in reservations[i+1:]:
                # Only check if different platforms
                if res1.platform != res2.platform:
                    # Check if date ranges overlap
                    if (res1.check_in_date < res2.check_out_date and
                        res2.check_in_date < res1.check_out_date):
                        warning = {
                            'room': room.name,
                            'platform1': dict(Reservation.PLATFORM_CHOICES).get(res1.platform),
                            'platform2': dict(Reservation.PLATFORM_CHOICES).get(res2.platform),
                            'dates': f"{max(res1.check_in_date, res2.check_in_date)} to {min(res1.check_out_date, res2.check_out_date)}",
                            'res1_guest': res1.guest_name,
                            'res2_guest': res2.guest_name,
                        }
                        overlapping_warnings.append(warning)

        return render(request, 'main/admin_page.html', {
        'rooms': available_rooms,
        'guests': guests,
        'todays_entries': todays_entries,
        'current_entries': current_entries,
        'dashboard_stats': current_guests_data['dashboard_stats'],
        'check_in_date': check_in_date,
        'check_out_date': check_out_date,
        'ical_configs': ical_configs,
        'overlapping_warnings': overlapping_warnings,
    })

def get_available_rooms(check_in_date, check_out_date):
    check_in_date = date.fromisoformat(str(check_in_date)) if isinstance(check_in_date, str) else check_in_date
    check_out_date = date.fromisoformat(str(check_out_date)) if isinstance(check_out_date, str) else check_out_date

    conflicting_guests = Guest.objects.filter(
        Q(check_in_date__lt=check_out_date) & Q(check_out_date__gt=check_in_date)
    )

    conflicting_rooms = conflicting_guests.values_list('assigned_room', flat=True)
    return Room.objects.exclude(id__in=conflicting_rooms)

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def available_rooms(request):
    check_in_date = request.GET.get('check_in_date')
    check_out_date = request.GET.get('check_out_date')

    if check_in_date and check_out_date:
        check_in_date = date.fromisoformat(check_in_date)
        check_out_date = date.fromisoformat(check_out_date)
        rooms = get_available_rooms(check_in_date, check_out_date)
        room_list = [{'id': room.id, 'name': room.name} for room in rooms]
        return JsonResponse({'rooms': room_list})
    return JsonResponse({'rooms': []})

def unauthorized(request):
    return render(request, 'main/unauthorized.html')

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.has_perm('main.change_guest'), login_url='/unauthorized/')
def edit_guest(request, guest_id):
    guest = get_object_or_404(Guest, id=guest_id)
    # Store original values for comparison
    original_room_id = guest.assigned_room.id
    original_phone_number = guest.phone_number
    original_email = guest.email
    original_full_name = guest.full_name
    original_reservation_number = guest.reservation_number
    original_check_in_date = guest.check_in_date
    original_check_out_date = guest.check_out_date
    original_early_checkin_time = guest.early_checkin_time
    original_late_checkout_time = guest.late_checkout_time

    if request.method == 'POST':
        if 'regenerate_pin' in request.POST:
            front_door_lock = TTLock.objects.filter(is_front_door=True).first()
            room_lock = guest.assigned_room.ttlock
            if not front_door_lock:
                logger.error("Front door lock not configured in the database.")
                messages.error(request, "Front door lock not configured.")
                return redirect('edit_guest', guest_id=guest.id)
            if not room_lock:
                logger.error(f"No TTLock assigned to room {guest.assigned_room.name}")
                messages.error(request, f"No lock assigned to room {guest.assigned_room.name}.")
                return redirect('edit_guest', guest_id=guest.id)

            ttlock_client = TTLockClient()
            # Delete existing front door PIN
            if guest.front_door_pin_id:
                try:
                    ttlock_client.delete_pin(
                        lock_id=front_door_lock.lock_id,
                        keyboard_pwd_id=guest.front_door_pin_id,
                    )
                except Exception as e:
                    messages.warning(request, f"Failed to delete old front door PIN: {str(e)}")

            # Delete existing room PIN
            if guest.room_pin_id:
                try:
                    ttlock_client.delete_pin(
                        lock_id=room_lock.lock_id,
                        keyboard_pwd_id=guest.room_pin_id,
                    )
                except Exception as e:
                    messages.warning(request, f"Failed to delete old room PIN: {str(e)}")

            new_pin = generate_memorable_4digit_pin()  # 4-digit memorable PIN
            uk_timezone = pytz.timezone("Europe/London")
            now_uk_time = timezone.now().astimezone(uk_timezone)

            # Set start_time to NOW so PIN is immediately active in TTLock
            # (PIN visibility to guest is controlled separately in room_detail view with early_checkin_time)
            start_time = int(now_uk_time.timestamp() * 1000)

            # Set endDate to one day after check-out
            check_out_time = guest.late_checkout_time if guest.late_checkout_time else datetime.time(11, 0)
            end_date = uk_timezone.localize(
                datetime.datetime.combine(guest.check_out_date, check_out_time)
            ) + datetime.timedelta(days=1)
            end_time = int(end_date.timestamp() * 1000)

            try:
                # Generate new PIN for front door
                front_door_response = ttlock_client.generate_temporary_pin(
                    lock_id=front_door_lock.lock_id,
                    pin=new_pin,
                    start_time=start_time,
                    end_time=end_time,
                    name=f"Front Door - {guest.assigned_room.name} - {guest.full_name} - {new_pin}",
                )
                if "keyboardPwdId" not in front_door_response:
                    logger.error(f"Failed to generate new front door PIN for guest {guest.reservation_number}: {front_door_response.get('errmsg', 'Unknown error')}")
                    messages.error(request, f"Failed to generate new front door PIN: {front_door_response.get('errmsg', 'Unknown error')}")
                    return redirect('edit_guest', guest_id=guest.id)
                guest.front_door_pin = new_pin
                guest.front_door_pin_id = front_door_response["keyboardPwdId"]

                # Generate the same PIN for the room lock
                room_response = ttlock_client.generate_temporary_pin(
                    lock_id=room_lock.lock_id,
                    pin=new_pin,
                    start_time=start_time,
                    end_time=end_time,
                    name=f"Room - {guest.assigned_room.name} - {guest.full_name} - {new_pin}",
                )
                if "keyboardPwdId" not in room_response:
                    logger.error(f"Failed to generate new room PIN for guest {guest.reservation_number}: {room_response.get('errmsg', 'Unknown error')}")
                    # Roll back the front door PIN
                    try:
                        ttlock_client.delete_pin(
                            lock_id=front_door_lock.lock_id,
                            keyboard_pwd_id=guest.front_door_pin_id,
                        )
                    except Exception as e:
                        logger.error(f"Failed to roll back new front door PIN for guest {guest.reservation_number}: {str(e)}")
                    guest.front_door_pin = None
                    guest.front_door_pin_id = None
                    guest.room_pin_id = None
                    guest.save()
                    messages.error(request, f"Failed to generate new room PIN: {room_response.get('errmsg', 'Unknown error')}")
                    return redirect('edit_guest', guest_id=guest.id)
                guest.room_pin_id = room_response["keyboardPwdId"]
                guest.save()
                AuditLog.objects.create(
                    user=request.user,
                    action="Guest PIN Regenerated",
                    object_type="Guest",
                    object_id=guest.id,
                    details=f"Regenerated PIN {new_pin} for reservation {guest.reservation_number}"
                )
                # Send update message after PIN regeneration
                if guest.phone_number or guest.email:
                    guest.send_update_message()
                messages.success(request, f"New PIN (for both front door and room) generated: {new_pin}. The guest can also unlock the doors remotely during check-in or from the room detail page.")
            except Exception as e:
                logger.error(f"Failed to generate new PIN for guest {guest.reservation_number}: {str(e)}")
                messages.error(request, f"Failed to generate new PIN: {str(e)}")
                return redirect('edit_guest', guest_id=guest.id)

        else:
            # Update guest details
            new_reservation_number = request.POST.get('reservation_number', '').strip()
            # Validate reservation_number length
            if len(new_reservation_number) > 15:
                messages.error(request, "Reservation number must not exceed 15 characters.")
                return redirect('edit_guest', guest_id=guest.id)

            # Store new values for comparison
            new_full_name = request.POST.get('full_name')
            new_reservation_number = new_reservation_number
            new_phone_number = request.POST.get('phone_number') or None
            new_email = request.POST.get('email') or None

            # Normalize and validate phone number if provided
            if new_phone_number:
                new_phone_number = normalize_phone_to_e164(new_phone_number.strip(), '+44')
                if new_phone_number:
                    is_valid, error_msg = validate_phone_number(new_phone_number)
                    if not is_valid:
                        messages.error(request, f"Invalid phone number: {error_msg}")
                        return redirect('edit_guest', guest_id=guest.id)

            check_in_date = date.fromisoformat(request.POST.get('check_in_date'))
            check_out_date = date.fromisoformat(request.POST.get('check_out_date'))
            new_room_id = request.POST.get('room')
            early_checkin_time = request.POST.get('early_checkin_time')
            late_checkout_time = request.POST.get('late_checkout_time')

            # Update early_checkin_time if provided
            new_early_checkin_time = None
            if early_checkin_time:
                try:
                    new_early_checkin_time = datetime.datetime.strptime(early_checkin_time, '%H:%M').time()
                    guest.early_checkin_time = new_early_checkin_time
                except ValueError:
                    messages.error(request, "Invalid early check-in time format. Use HH:MM (e.g., 12:00).")
                    return redirect('edit_guest', guest_id=guest.id)
            else:
                guest.early_checkin_time = None  # Revert to default if empty

            # Update late_checkout_time if provided
            new_late_checkout_time = None
            if late_checkout_time:
                try:
                    new_late_checkout_time = datetime.datetime.strptime(late_checkout_time, '%H:%M').time()
                    guest.late_checkout_time = new_late_checkout_time
                except ValueError:
                    messages.error(request, "Invalid late check-out time format. Use HH:MM (e.g., 12:00).")
                    return redirect('edit_guest', guest_id=guest.id)
            else:
                guest.late_checkout_time = None  # Revert to default if empty

            # Update all guest fields before saving
            guest.full_name = new_full_name
            guest.reservation_number = new_reservation_number
            guest.phone_number = new_phone_number
            guest.email = new_email
            guest.check_in_date = check_in_date
            guest.check_out_date = check_out_date
            guest.assigned_room_id = new_room_id

            # Check for room change
            if str(new_room_id) != str(original_room_id):
                AuditLog.objects.create(
                    user=request.user,
                    action="Guest Room Changed",
                    object_type="Guest",
                    object_id=guest.id,
                    details=f"Changed room from {original_room_id} to {new_room_id} for reservation {guest.reservation_number}"
                )
                front_door_lock = TTLock.objects.filter(is_front_door=True).first()
                old_room_lock = Room.objects.get(id=original_room_id).ttlock
                new_room_lock = Room.objects.get(id=new_room_id).ttlock
                ttlock_client = TTLockClient()

                # Delete old room PIN
                if guest.room_pin_id and old_room_lock:
                    try:
                        ttlock_client.delete_pin(
                            lock_id=old_room_lock.lock_id,
                            keyboard_pwd_id=guest.room_pin_id,
                        )
                    except Exception as e:
                        messages.warning(request, f"Failed to delete old room PIN: {str(e)}")

                # Regenerate PIN for new room and front door
                if front_door_lock and new_room_lock:
                    try:
                        # Delete existing front door PIN if present
                        if guest.front_door_pin_id:
                            ttlock_client.delete_pin(
                                lock_id=front_door_lock.lock_id,
                                keyboard_pwd_id=guest.front_door_pin_id,
                            )

                        new_pin = generate_memorable_4digit_pin()  # 4-digit memorable PIN
                        uk_timezone = pytz.timezone("Europe/London")
                        now_uk_time = timezone.now().astimezone(uk_timezone)

                        # Set start_time to NOW so PIN is immediately active in TTLock
                        # (PIN visibility to guest is controlled separately in room_detail view with early_checkin_time)
                        start_time = int(now_uk_time.timestamp() * 1000)

                        check_out_time = guest.late_checkout_time if guest.late_checkout_time else datetime.time(11, 0)
                        end_date = uk_timezone.localize(
                            datetime.datetime.combine(check_out_date, check_out_time)
                        ) + datetime.timedelta(days=1)
                        end_time = int(end_date.timestamp() * 1000)

                        # Generate new PIN for front door
                        front_door_response = ttlock_client.generate_temporary_pin(
                            lock_id=front_door_lock.lock_id,
                            pin=new_pin,
                            start_time=start_time,
                            end_time=end_time,
                            name=f"Front Door - {Room.objects.get(id=new_room_id).name} - {guest.full_name} - {new_pin}",
                        )
                        if "keyboardPwdId" not in front_door_response:
                            logger.error(f"Failed to generate new front door PIN for guest {guest.reservation_number} after room change: {front_door_response.get('errmsg', 'Unknown error')}")
                            messages.error(request, f"Failed to generate new front door PIN: {front_door_response.get('errmsg', 'Unknown error')}")
                            return redirect('edit_guest', guest_id=guest.id)
                        guest.front_door_pin = new_pin
                        guest.front_door_pin_id = front_door_response["keyboardPwdId"]

                        # Generate the same PIN for the room lock
                        room_response = ttlock_client.generate_temporary_pin(
                            lock_id=new_room_lock.lock_id,
                            pin=new_pin,
                            start_time=start_time,
                            end_time=end_time,
                            name=f"Room - {Room.objects.get(id=new_room_id).name} - {guest.full_name} - {new_pin}",
                        )
                        if "keyboardPwdId" not in room_response:
                            logger.error(f"Failed to generate new room PIN for guest {guest.reservation_number} after room change: {room_response.get('errmsg', 'Unknown error')}")
                            # Roll back the front door PIN
                            try:
                                ttlock_client.delete_pin(
                                    lock_id=front_door_lock.lock_id,
                                    keyboard_pwd_id=guest.front_door_pin_id,
                                )
                            except Exception as e:
                                logger.error(f"Failed to roll back new front door PIN for guest {guest.reservation_number}: {str(e)}")
                            guest.front_door_pin = None
                            guest.front_door_pin_id = None
                            guest.room_pin_id = None
                            guest.save()
                            messages.error(request, f"Failed to generate new room PIN: {room_response.get('errmsg', 'Unknown error')}")
                            return redirect('edit_guest', guest_id=guest.id)
                        guest.room_pin_id = room_response["keyboardPwdId"]
                        AuditLog.objects.create(
                            user=request.user,
                            action="Guest PIN Regenerated (Room Change)",
                            object_type="Guest",
                            object_id=guest.id,
                            details=f"Regenerated PIN {new_pin} due to room change for reservation {guest.reservation_number}"
                        )
                    except Exception as e:
                        logger.error(f"Failed to generate new PIN for guest {guest.reservation_number} after room change: {str(e)}")
                        messages.error(request, f"Failed to generate new PIN after room change: {str(e)}")
                        return redirect('edit_guest', guest_id=guest.id)

            # Check for changes and build the changed_fields list
            changed_fields = []
            if original_full_name != new_full_name:
                changed_fields.append(f"Full Name (from '{original_full_name}' to '{new_full_name}')")
            if original_reservation_number != new_reservation_number:
                changed_fields.append(f"Reservation Number (from '{original_reservation_number}' to '{new_reservation_number}')")
            if original_phone_number != new_phone_number:
                changed_fields.append(f"Phone Number (from '{original_phone_number or 'None'}' to '{new_phone_number or 'None'}')")
            if original_email != new_email:
                changed_fields.append(f"Email (from '{original_email or 'None'}' to '{new_email or 'None'}')")
            if original_check_in_date != check_in_date:
                changed_fields.append(f"Check-In Date (from '{original_check_in_date}' to '{check_in_date}')")
            if original_check_out_date != check_out_date:
                changed_fields.append(f"Check-Out Date (from '{original_check_out_date}' to '{check_out_date}')")
            if str(original_room_id) != str(new_room_id):
                original_room = Room.objects.get(id=original_room_id)
                new_room = Room.objects.get(id=new_room_id)
                changed_fields.append(f"Room (from '{original_room.name}' to '{new_room.name}')")
            if original_early_checkin_time != new_early_checkin_time:
                changed_fields.append(f"Early Check-In Time (from '{original_early_checkin_time or 'Default (2:00 PM)'}' to '{new_early_checkin_time or 'Default (2:00 PM)'}')")
            if original_late_checkout_time != new_late_checkout_time:
                changed_fields.append(f"Late Check-Out Time (from '{original_late_checkout_time or 'Default (11:00 AM)'}' to '{new_late_checkout_time or 'Default (11:00 AM)'}')")

            # Save the guest with all updated fields
            guest.save()

            # Log the updated times for debugging
            logger.info(f"After save: early_checkin_time={guest.early_checkin_time}, late_checkout_time={guest.late_checkout_time}")

            # Send update message if there are changes and the guest has contact info
            if changed_fields and (guest.phone_number or guest.email):
                guest.send_update_message()

            # Construct the success message with changed fields
            if changed_fields:
                changes_message = "Changes made: " + ", ".join(changed_fields) + "."
            else:
                changes_message = "No changes were made to the guest's details."
            messages.success(request, f"Guest {guest.full_name} updated successfully. {changes_message} The guest can unlock the doors using their PIN or remotely during check-in or from the room detail page.")

            AuditLog.objects.create(
                user=request.user,
                action="Guest Updated",
                object_type="Guest",
                object_id=guest.id,
                details=f"Updated details for reservation {guest.reservation_number} (Room: {new_room_id}, Check-in: {check_in_date}, Check-out: {check_out_date})"
            )

        return redirect('admin_page')

    available_rooms = get_available_rooms(guest.check_in_date, guest.check_out_date) | Room.objects.filter(id=guest.assigned_room.id)

    return render(request, 'main/edit_guest.html', {
        'guest': guest,
        'rooms': available_rooms,
    })

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.has_perm('main.view_admin_dashboard'), login_url='/unauthorized/')
def edit_reservation(request, reservation_id):
    """Edit unenriched iCal reservation (before guest checks in)"""
    reservation = get_object_or_404(Reservation, id=reservation_id)

    # Store original values for comparison
    original_check_in_date = reservation.check_in_date
    original_check_out_date = reservation.check_out_date
    original_early_checkin_time = reservation.early_checkin_time
    original_late_checkout_time = reservation.late_checkout_time
    original_room_id = reservation.room.id

    if request.method == 'POST':
        # Get form data
        check_in_date = date.fromisoformat(request.POST.get('check_in_date'))
        check_out_date = date.fromisoformat(request.POST.get('check_out_date'))
        room_id = request.POST.get('room')
        early_checkin_time = request.POST.get('early_checkin_time')
        late_checkout_time = request.POST.get('late_checkout_time')

        # Update early_checkin_time if provided
        if early_checkin_time:
            try:
                reservation.early_checkin_time = datetime.datetime.strptime(early_checkin_time, '%H:%M').time()
            except ValueError:
                messages.error(request, "Invalid early check-in time format. Use HH:MM (e.g., 12:00).")
                return redirect('edit_reservation', reservation_id=reservation.id)
        else:
            reservation.early_checkin_time = None  # Revert to default if empty

        # Update late_checkout_time if provided
        if late_checkout_time:
            try:
                reservation.late_checkout_time = datetime.datetime.strptime(late_checkout_time, '%H:%M').time()
            except ValueError:
                messages.error(request, "Invalid late check-out time format. Use HH:MM (e.g., 14:00).")
                return redirect('edit_reservation', reservation_id=reservation.id)
        else:
            reservation.late_checkout_time = None  # Revert to default if empty

        # Update basic fields
        reservation.check_in_date = check_in_date
        reservation.check_out_date = check_out_date
        reservation.room_id = room_id

        # Save changes
        reservation.save()

        # Build changes message
        changes = []
        if str(room_id) != str(original_room_id):
            changes.append(f"Room changed")
        if check_in_date != original_check_in_date:
            changes.append(f"Check-in date changed to {check_in_date}")
        if check_out_date != original_check_out_date:
            changes.append(f"Check-out date changed to {check_out_date}")
        if reservation.early_checkin_time != original_early_checkin_time:
            if reservation.early_checkin_time:
                changes.append(f"Early check-in set to {reservation.early_checkin_time.strftime('%I:%M %p')}")
            else:
                changes.append("Early check-in removed (will default to 2:00 PM)")
        if reservation.late_checkout_time != original_late_checkout_time:
            if reservation.late_checkout_time:
                changes.append(f"Late check-out set to {reservation.late_checkout_time.strftime('%I:%M %p')}")
            else:
                changes.append("Late check-out removed (will default to 11:00 AM)")

        if changes:
            changes_message = ". ".join(changes) + "."
        else:
            changes_message = "No changes were made."

        messages.success(request, f"Reservation {reservation.booking_reference} updated successfully. {changes_message}")

        # Log the action
        AuditLog.objects.create(
            user=request.user,
            action="Reservation Updated",
            object_type="Reservation",
            object_id=reservation.id,
            details=f"Updated reservation {reservation.booking_reference} - {changes_message}"
        )

        return redirect('admin_page')

    # Get available rooms for the date range (include current room)
    available_rooms = get_available_rooms(reservation.check_in_date, reservation.check_out_date) | Room.objects.filter(id=reservation.room.id)

    return render(request, 'main/edit_reservation.html', {
        'reservation': reservation,
        'rooms': available_rooms,
    })

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.has_perm('main.view_admin_dashboard'), login_url='/unauthorized/')
def manual_checkin_reservation(request, reservation_id):
    """
    Manually check in an unenriched iCal reservation
    - Admin provides guest name, phone, email
    - System generates PIN (respecting check-in date validation)
    - Links Guest to Reservation
    - Copies early/late times from Reservation to Guest
    """
    reservation = get_object_or_404(Reservation, id=reservation_id)

    # Ensure reservation is not already enriched
    if reservation.guest:
        messages.warning(request, f"This reservation is already checked in by {reservation.guest.full_name}.")
        return redirect('admin_page')

    if request.method == 'POST':
        # Get form data
        full_name = request.POST.get('full_name', '').strip()
        phone_number = request.POST.get('phone_number', '').strip() or None
        email = request.POST.get('email', '').strip() or None

        # Validation
        if not full_name:
            messages.error(request, "Full name is required.")
            return redirect('manual_checkin_reservation', reservation_id=reservation.id)

        # Normalize and validate phone number
        if phone_number:
            phone_number = normalize_phone_to_e164(phone_number, '+44')
            if phone_number:
                is_valid, error_msg = validate_phone_number(phone_number)
                if not is_valid:
                    messages.error(request, f"Invalid phone number: {error_msg}")
                    return redirect('manual_checkin_reservation', reservation_id=reservation.id)

        # MULTI-ROOM: Check if guest with this booking reference already exists
        existing_guest = Guest.objects.filter(reservation_number=reservation.booking_reference).first()
        
        if existing_guest:
            # Guest already exists - link this reservation to existing guest
            reservation.guest = existing_guest
            reservation.save()
            logger.info(f"Linked reservation {reservation.id} to existing guest {existing_guest.id} (multi-room booking)")
            
            # MULTI-ROOM FIX: Generate PIN for this additional room using existing guest's PIN
            if existing_guest.front_door_pin and reservation.room.ttlock:
                try:
                    ttlock_client = TTLockClient()
                    uk_timezone = pytz.timezone("Europe/London")
                    now_uk_time = timezone.now().astimezone(uk_timezone)
                    
                    # Use existing guest's PIN
                    pin = existing_guest.front_door_pin
                    start_time = int(now_uk_time.timestamp() * 1000)
                    check_out_time_val = reservation.late_checkout_time if reservation.late_checkout_time else time(11, 0)
                    end_date = uk_timezone.localize(
                        datetime.datetime.combine(reservation.check_out_date, check_out_time_val)
                    ) + datetime.timedelta(days=1)
                    end_time = int(end_date.timestamp() * 1000)
                    
                    # Generate PIN for this room's lock
                    room_response = ttlock_client.generate_temporary_pin(
                        lock_id=reservation.room.ttlock.lock_id,
                        pin=pin,
                        start_time=start_time,
                        end_time=end_time,
                        name=f"Room - {reservation.room.name} - {existing_guest.full_name} - {pin}",
                    )
                    
                    if "keyboardPwdId" in room_response:
                        logger.info(f"Generated PIN for additional room {reservation.room.name} (multi-room booking)")
                        messages.success(request, f"Linked to existing guest {existing_guest.full_name}. Room {reservation.room.name} added with PIN {pin}.")
                    else:
                        logger.error(f"Failed to generate PIN for room {reservation.room.name}: {room_response.get('errmsg', 'Unknown error')}")
                        messages.warning(request, f"Linked reservation but failed to generate PIN for {reservation.room.name}. Guest can use existing PIN for other rooms.")
                except Exception as e:
                    logger.error(f"Failed to generate PIN for additional room: {str(e)}")
                    messages.warning(request, f"Linked reservation but PIN generation failed: {str(e)}")
            else:
                messages.success(request, f"Linked to existing guest {existing_guest.full_name}. Room {reservation.room.name} added to their booking.")
            
            # Log the action
            AuditLog.objects.create(
                user=request.user,
                action="Manual Check-In (Multi-Room)",
                object_type="Reservation",
                object_id=reservation.id,
                details=f"Linked reservation {reservation.booking_reference} to existing guest {existing_guest.full_name}, generated PIN for {reservation.room.name}"
            )
            return redirect('admin_page')

        # Check for returning guest
        previous_stays = Guest.objects.filter(
            Q(full_name__iexact=full_name)
        ).exists()

        # Check if it's the check-in day (or later) before generating PIN
        uk_timezone = pytz.timezone("Europe/London")
        now_uk_time = timezone.now().astimezone(uk_timezone)

        # Only generate PIN on or after check-in date
        if now_uk_time.date() < reservation.check_in_date:
            # Too early - create guest without PIN
            guest = Guest.objects.create(
                full_name=full_name,
                email=email,
                phone_number=phone_number,
                reservation_number=reservation.booking_reference,
                check_in_date=reservation.check_in_date,
                check_out_date=reservation.check_out_date,
                assigned_room=reservation.room,
                early_checkin_time=reservation.early_checkin_time,
                late_checkout_time=reservation.late_checkout_time,
                is_returning=previous_stays,
            )
            reservation.guest = guest
            reservation.save()

            logger.info(f"Guest {guest.id} created via manual check-in but PIN generation deferred until check-in date")
            messages.info(request, f"Guest {full_name} checked in successfully. PIN will be generated on {reservation.check_in_date.strftime('%d %b %Y')}.")

            # Log the action
            AuditLog.objects.create(
                user=request.user,
                action="Manual Check-In (Early)",
                object_type="Guest",
                object_id=guest.id,
                details=f"Manually checked in {full_name} for reservation {reservation.booking_reference} (PIN deferred until check-in date)"
            )
            return redirect('admin_page')

        # Generate PIN (same logic as enrich_reservation)
        try:
            front_door_lock = TTLock.objects.get(is_front_door=True)
            room_lock = reservation.room.ttlock

            if not front_door_lock:
                messages.error(request, "Front door lock not configured.")
                return redirect('manual_checkin_reservation', reservation_id=reservation.id)
            if not room_lock:
                messages.error(request, f"No lock assigned to room {reservation.room.name}.")
                return redirect('manual_checkin_reservation', reservation_id=reservation.id)

            pin = generate_memorable_4digit_pin()

            # Set start_time to NOW so PIN is immediately active
            start_time = int(now_uk_time.timestamp() * 1000)

            # Set end time based on late_checkout_time (from reservation or default)
            check_out_time_val = reservation.late_checkout_time if reservation.late_checkout_time else time(11, 0)
            end_date = uk_timezone.localize(
                datetime.datetime.combine(reservation.check_out_date, check_out_time_val)
            ) + datetime.timedelta(days=1)
            end_time = int(end_date.timestamp() * 1000)

            ttlock_client = TTLockClient()

            # Generate front door PIN
            front_door_response = ttlock_client.generate_temporary_pin(
                lock_id=front_door_lock.lock_id,
                pin=pin,
                start_time=start_time,
                end_time=end_time,
                name=f"Front Door - {reservation.room.name} - {full_name} - {pin}",
            )
            if "keyboardPwdId" not in front_door_response:
                logger.error(f"Failed to generate front door PIN: {front_door_response.get('errmsg', 'Unknown error')}")
                messages.error(request, f"Failed to generate front door PIN: {front_door_response.get('errmsg', 'Unknown error')}")
                return redirect('manual_checkin_reservation', reservation_id=reservation.id)
            keyboard_pwd_id_front = front_door_response["keyboardPwdId"]

            # Generate room PIN
            room_response = ttlock_client.generate_temporary_pin(
                lock_id=room_lock.lock_id,
                pin=pin,
                start_time=start_time,
                end_time=end_time,
                name=f"Room - {reservation.room.name} - {full_name} - {pin}",
            )
            if "keyboardPwdId" not in room_response:
                logger.error(f"Failed to generate room PIN: {room_response.get('errmsg', 'Unknown error')}")
                # Roll back front door PIN
                try:
                    ttlock_client.delete_pin(lock_id=front_door_lock.lock_id, keyboard_pwd_id=keyboard_pwd_id_front)
                except Exception as e:
                    logger.error(f"Failed to roll back front door PIN: {str(e)}")
                messages.error(request, f"Failed to generate room PIN: {room_response.get('errmsg', 'Unknown error')}")
                return redirect('manual_checkin_reservation', reservation_id=reservation.id)
            keyboard_pwd_id_room = room_response["keyboardPwdId"]

            # Create guest with PIN
            guest = Guest.objects.create(
                full_name=full_name,
                email=email,
                phone_number=phone_number,
                reservation_number=reservation.booking_reference,
                check_in_date=reservation.check_in_date,
                check_out_date=reservation.check_out_date,
                assigned_room=reservation.room,
                early_checkin_time=reservation.early_checkin_time,
                late_checkout_time=reservation.late_checkout_time,
                is_returning=previous_stays,
                front_door_pin=pin,
                front_door_pin_id=keyboard_pwd_id_front,
                room_pin_id=keyboard_pwd_id_room,
            )

            # Link guest to reservation
            reservation.guest = guest
            reservation.save()

            logger.info(f"Guest {guest.id} created via manual check-in with PIN {pin}")
            messages.success(request, f"Guest {full_name} checked in successfully! PIN (for both front door and room): {pin}")

            # Log the action
            AuditLog.objects.create(
                user=request.user,
                action="Manual Check-In",
                object_type="Guest",
                object_id=guest.id,
                details=f"Manually checked in {full_name} for reservation {reservation.booking_reference} with PIN {pin}"
            )

            # Send welcome message if contact info provided
            if guest.phone_number or guest.email:
                try:
                    guest.send_checkin_message()
                except Exception as e:
                    logger.error(f"Failed to send check-in message to {full_name}: {str(e)}")

            return redirect('admin_page')

        except Exception as e:
            logger.error(f"Failed to manually check in reservation {reservation.id}: {str(e)}")
            messages.error(request, f"Failed to check in guest: {str(e)}")
            return redirect('manual_checkin_reservation', reservation_id=reservation.id)

    # GET request - show form
    return render(request, 'main/manual_checkin_reservation.html', {
        'reservation': reservation,
    })

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.has_perm('main.delete_guest'), login_url='/unauthorized/')
def delete_guest(request, guest_id):
    guest = get_object_or_404(Guest, id=guest_id)
    guest_name = guest.full_name
    reservation_number = guest.reservation_number
    front_door_lock = TTLock.objects.filter(is_front_door=True).first()
    room_lock = guest.assigned_room.ttlock
    ttlock_client = TTLockClient()

    # Delete front door PIN
    if guest.front_door_pin_id and front_door_lock:
        try:
            ttlock_client.delete_pin(
                lock_id=front_door_lock.lock_id,
                keyboard_pwd_id=guest.front_door_pin_id,
            )
            logger.info(f"Deleted front door PIN for guest {guest.reservation_number} (Keyboard Password ID: {guest.front_door_pin_id})")
        except Exception as e:
            logger.error(f"Failed to delete front door PIN for guest {guest.reservation_number}: {str(e)}")
            messages.warning(request, f"Failed to delete front door PIN for {guest_name}: {str(e)}")

    # Delete room PIN
    if guest.room_pin_id and room_lock:
        try:
            ttlock_client.delete_pin(
                lock_id=room_lock.lock_id,
                keyboard_pwd_id=guest.room_pin_id,
            )
            logger.info(f"Deleted room PIN for guest {guest.reservation_number} (Keyboard Password ID: {guest.room_pin_id})")
        except Exception as e:
            logger.error(f"Failed to delete room PIN for guest {guest.reservation_number}: {str(e)}")
            messages.warning(request, f"Failed to delete room PIN for {guest_name}: {str(e)}")

    guest.delete()
    AuditLog.objects.create(
        user=request.user,
        action="Guest Deleted",
        object_type="Guest",
        object_id=guest_id,
        details=f"Deleted guest {guest_name} with reservation {reservation_number}"
    )
    logger.info(f"Deleted guest {reservation_number}")
    messages.success(request, f"Guest {guest_name} deleted successfully.")
    return redirect('admin_page')

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.has_perm('main.view_guest'), login_url='/unauthorized/')
def past_guests(request):
    search_query = request.GET.get('search', '')

    # Optimize: Use select_related and prefetch_related to reduce queries
    # Note: is_returning is already a field on Guest model, no need to annotate
    past_guests = Guest.objects.filter(
        is_archived=True
    ).select_related('assigned_room').prefetch_related('reservation')

    if search_query:
        past_guests = past_guests.filter(
            Q(full_name__icontains=search_query) |
            Q(phone_number__icontains=search_query) |
            Q(reservation_number__icontains=search_query) |
            Q(assigned_room__name__icontains=search_query)
        )

    past_guests = past_guests.order_by('-check_out_date')
    paginator = Paginator(past_guests, 50)
    page_number = request.GET.get('page')
    paginated_past_guests = paginator.get_page(page_number)

    return render(request, 'main/past_guests.html', {
        'past_guests': paginated_past_guests,
        'search_query': search_query,
    })

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.has_perm('main.view_admin_dashboard'), login_url='/unauthorized/')
def all_reservations(request):
    """
    Display all reservations (past, present, future) with filtering
    - Platform filter (Booking.com, Airbnb, Manual)
    - Status filter (Confirmed, Cancelled)
    - Enrichment filter (Enriched/Unenriched)
    - Date range filter
    - Search by booking reference or guest name
    - JavaScript pagination (10 per page)
    """
    from datetime import datetime as dt

    # Get filter parameters
    platform_filter = request.GET.get('platform', 'all')
    status_filter = request.GET.get('status', 'all')
    enrichment_filter = request.GET.get('enrichment', 'all')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    search_query = request.GET.get('search', '')
    quick_filter = request.GET.get('quick', '')
    show_all = request.GET.get('show_all', '')  # New: show all reservations (including old)

    today = date.today()
    yesterday = today - timedelta(days=1)

    # DEFAULT: Show relevant reservations (current, upcoming, recently checked out)
    # UNLESS search query is provided (then show all matching results)
    # UNLESS show_all=true (then show everything)
    if search_query:
        # Search mode: Show ALL reservations matching search (no date filter)
        reservations = Reservation.objects.all().select_related('room', 'guest')
    elif show_all:
        # Show all mode: Show everything
        reservations = Reservation.objects.all().select_related('room', 'guest')
    elif quick_filter == 'today':
        # Show reservations active today (check_in <= today <= check_out)
        reservations = Reservation.objects.filter(
            check_in_date__lte=today,
            check_out_date__gte=today
        ).select_related('room', 'guest')
    elif quick_filter == 'tomorrow':
        # Show reservations active tomorrow
        tomorrow = today + timedelta(days=1)
        reservations = Reservation.objects.filter(
            check_in_date__lte=tomorrow,
            check_out_date__gte=tomorrow
        ).select_related('room', 'guest')
    else:
        # DEFAULT VIEW: Show current guests + upcoming + recently checked out (last 1 day)
        reservations = Reservation.objects.filter(
            Q(check_out_date__gte=yesterday) |  # Currently staying OR checked out in last 1 day
            Q(check_in_date__gte=today)  # OR checking in today or future
        ).select_related('room', 'guest')

    # Order by check-in date (nearest first)
    reservations = reservations.order_by('check_in_date')

    # Apply platform filter
    if platform_filter != 'all':
        reservations = reservations.filter(platform=platform_filter)

    # Apply status filter
    if status_filter != 'all':
        reservations = reservations.filter(status=status_filter)

    # Apply enrichment filter
    if enrichment_filter == 'enriched':
        reservations = reservations.filter(guest__isnull=False)
    elif enrichment_filter == 'unenriched':
        reservations = reservations.filter(guest__isnull=True)

    # Apply date range filter (only when not using quick filters or default view)
    if date_from or date_to:
        if date_from:
            try:
                date_from_obj = dt.strptime(date_from, '%Y-%m-%d').date()
                reservations = reservations.filter(check_in_date__gte=date_from_obj)
            except ValueError:
                pass

        if date_to:
            try:
                date_to_obj = dt.strptime(date_to, '%Y-%m-%d').date()
                reservations = reservations.filter(check_in_date__lte=date_to_obj)
            except ValueError:
                pass

    # Apply search filter (searches all reservations regardless of date)
    if search_query:
        reservations = reservations.filter(
            Q(booking_reference__icontains=search_query) |
            Q(guest_name__icontains=search_query) |
            Q(guest__full_name__icontains=search_query)
        )

    # Get today's date for visual indicators
    today = date.today()

    # Prepare reservation list with enriched data
    reservations_data = []
    for reservation in reservations:
        # Determine status badge
        if reservation.check_in_date > today:
            time_status = 'upcoming'
            time_badge = 'Upcoming'
        elif reservation.check_in_date <= today <= reservation.check_out_date:
            time_status = 'current'
            time_badge = 'Current'
        else:
            time_status = 'past'
            time_badge = 'Past'

        # Platform badge
        if reservation.platform == 'booking':
            platform_badge = '📘 Booking.com'
        elif reservation.platform == 'airbnb':
            platform_badge = '🏠 Airbnb'
        else:
            platform_badge = '👤 Manual'

        # Enrichment status
        is_enriched = reservation.guest is not None
        enrichment_status = 'Checked In' if is_enriched else 'Pending'
        guest_name = reservation.guest.full_name if is_enriched else reservation.guest_name or 'N/A'

        reservations_data.append({
            'id': reservation.id,
            'booking_reference': reservation.booking_reference,
            'guest_name': guest_name,
            'room': reservation.room.name,
            'check_in_date': reservation.check_in_date,
            'check_out_date': reservation.check_out_date,
            'platform': reservation.platform,
            'platform_badge': platform_badge,
            'status': reservation.status,
            'time_status': time_status,
            'time_badge': time_badge,
            'is_enriched': is_enriched,
            'enrichment_status': enrichment_status,
            'guest_id': reservation.guest.id if is_enriched else None,
            'early_checkin_time': reservation.early_checkin_time,
            'late_checkout_time': reservation.late_checkout_time,
        })

    return render(request, 'main/all_reservations.html', {
        'reservations': reservations,  # Pass queryset directly (room data via select_related)
        'platform_filter': platform_filter,
        'status_filter': status_filter,
        'enrichment_filter': enrichment_filter,
        'date_from': date_from,
        'date_to': date_to,
        'search_query': search_query,
        'today': today,
    })

@login_required(login_url='/admin-page/login/')

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.has_perm('main.delete_guest'), login_url='/unauthorized/')
def delete_reservation(request, reservation_id):
    """Delete individual reservation"""
    if request.method == 'POST':
        try:
            reservation = get_object_or_404(Reservation, id=reservation_id)
            booking_ref = reservation.booking_reference
            room_name = reservation.room.name
            
            # Check if reservation is enriched (has linked guest)
            if reservation.guest:
                messages.warning(request, f"Cannot delete reservation {booking_ref} - it is linked to guest {reservation.guest.full_name}. Delete the guest first.")
                return redirect('all_reservations')
            
            # Delete the reservation
            reservation.delete()
            
            # Log the deletion
            AuditLog.objects.create(
                user=request.user,
                action="Reservation Deleted",
                object_type="Reservation",
                object_id=reservation_id,
                details=f"Deleted unenriched reservation {booking_ref} for room {room_name}"
            )
            
            logger.info(f"Reservation {booking_ref} deleted by {request.user.username}")
            messages.success(request, f"Reservation {booking_ref} deleted successfully.")
            
        except Exception as e:
            logger.error(f"Error deleting reservation {reservation_id}: {str(e)}")
            messages.error(request, f"Failed to delete reservation: {str(e)}")
    
    return redirect('all_reservations')


@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.has_perm('main.delete_guest'), login_url='/unauthorized/')
def bulk_delete_reservations(request):
    """Delete multiple reservations at once"""
    if request.method == 'POST':
        reservation_ids = request.POST.getlist('reservation_ids')
        
        if not reservation_ids:
            messages.warning(request, "No reservations selected for deletion.")
            return redirect('all_reservations')
        
        deleted_count = 0
        skipped_count = 0
        skipped_bookings = []
        
        for res_id in reservation_ids:
            try:
                reservation = Reservation.objects.get(id=res_id)
                
                # Skip enriched reservations (linked to guests)
                if reservation.guest:
                    skipped_count += 1
                    skipped_bookings.append(reservation.booking_reference)
                    continue
                
                booking_ref = reservation.booking_reference
                room_name = reservation.room.name
                
                # Delete the reservation
                reservation.delete()
                
                # Log the deletion
                AuditLog.objects.create(
                    user=request.user,
                    action="Reservation Deleted (Bulk)",
                    object_type="Reservation",
                    object_id=res_id,
                    details=f"Bulk deleted unenriched reservation {booking_ref} for room {room_name}"
                )
                
                deleted_count += 1
                
            except Reservation.DoesNotExist:
                logger.warning(f"Reservation {res_id} not found during bulk delete")
                continue
            except Exception as e:
                logger.error(f"Error deleting reservation {res_id}: {str(e)}")
                continue
        
        # Prepare success/warning messages
        if deleted_count > 0:
            messages.success(request, f"Successfully deleted {deleted_count} reservation(s).")
        
        if skipped_count > 0:
            skipped_list = ", ".join(skipped_bookings[:5])  # Show first 5
            if len(skipped_bookings) > 5:
                skipped_list += f" (+{len(skipped_bookings) - 5} more)"
            messages.warning(request, f"Skipped {skipped_count} enriched reservation(s) (linked to guests): {skipped_list}")
        
        if deleted_count == 0 and skipped_count == 0:
            messages.info(request, "No reservations were deleted.")
        
        logger.info(f"Bulk delete completed by {request.user.username}: {deleted_count} deleted, {skipped_count} skipped")
    
    return redirect('all_reservations')


@user_passes_test(lambda user: user.has_perm('main.change_guest'), login_url='/unauthorized/')
def manage_checkin_checkout(request, guest_id):
    guest = get_object_or_404(Guest, id=guest_id)
    # Store original values for comparison
    original_early_checkin_time = guest.early_checkin_time
    original_late_checkout_time = guest.late_checkout_time

    if request.method == 'POST':
        if 'regenerate_pin' in request.POST:
            front_door_lock = TTLock.objects.filter(is_front_door=True).first()
            room_lock = guest.assigned_room.ttlock
            if not front_door_lock:
                logger.error("Front door lock not configured in the database.")
                messages.error(request, "Front door lock not configured.")
                return redirect('manage_checkin_checkout', guest_id=guest.id)
            if not room_lock:
                logger.error(f"No TTLock assigned to room {guest.assigned_room.name}")
                messages.error(request, f"No lock assigned to room {guest.assigned_room.name}.")
                return redirect('manage_checkin_checkout', guest_id=guest.id)

            ttlock_client = TTLockClient()
            # Delete existing front door PIN
            if guest.front_door_pin_id:
                try:
                    ttlock_client.delete_pin(
                        lock_id=front_door_lock.lock_id,
                        keyboard_pwd_id=guest.front_door_pin_id,
                    )
                except Exception as e:
                    messages.warning(request, f"Failed to delete old front door PIN: {str(e)}")

            # Delete existing room PIN
            if guest.room_pin_id:
                try:
                    ttlock_client.delete_pin(
                        lock_id=room_lock.lock_id,
                        keyboard_pwd_id=guest.room_pin_id,
                    )
                except Exception as e:
                    messages.warning(request, f"Failed to delete old room PIN: {str(e)}")

            new_pin = generate_memorable_4digit_pin()  # 4-digit memorable PIN
            uk_timezone = pytz.timezone("Europe/London")
            now_uk_time = timezone.now().astimezone(uk_timezone)

            # Set start_time to NOW so PIN is immediately active in TTLock
            # (PIN visibility to guest is controlled separately in room_detail view with early_checkin_time)
            start_time = int(now_uk_time.timestamp() * 1000)

            # Set endDate to one day after check-out
            check_out_time = guest.late_checkout_time if guest.late_checkout_time else datetime.time(11, 0)
            end_date = uk_timezone.localize(
                datetime.datetime.combine(guest.check_out_date, check_out_time)
            ) + datetime.timedelta(days=1)
            end_time = int(end_date.timestamp() * 1000)

            try:
                # Generate new PIN for front door
                front_door_response = ttlock_client.generate_temporary_pin(
                    lock_id=front_door_lock.lock_id,
                    pin=new_pin,
                    start_time=start_time,
                    end_time=end_time,
                    name=f"Front Door - {guest.assigned_room.name} - {guest.full_name} - {new_pin}",
                )
                if "keyboardPwdId" not in front_door_response:
                    logger.error(f"Failed to generate new front door PIN for guest {guest.reservation_number}: {front_door_response.get('errmsg', 'Unknown error')}")
                    messages.error(request, f"Failed to generate new front door PIN: {front_door_response.get('errmsg', 'Unknown error')}")
                    return redirect('manage_checkin_checkout', guest_id=guest.id)
                guest.front_door_pin = new_pin
                guest.front_door_pin_id = front_door_response["keyboardPwdId"]

                # Generate the same PIN for the room lock
                room_response = ttlock_client.generate_temporary_pin(
                    lock_id=room_lock.lock_id,
                    pin=new_pin,
                    start_time=start_time,
                    end_time=end_time,
                    name=f"Room - {guest.assigned_room.name} - {guest.full_name} - {new_pin}",
                )
                if "keyboardPwdId" not in room_response:
                    logger.error(f"Failed to generate new room PIN for guest {guest.reservation_number}: {room_response.get('errmsg', 'Unknown error')}")
                    # Roll back the front door PIN
                    try:
                        ttlock_client.delete_pin(
                            lock_id=front_door_lock.lock_id,
                            keyboard_pwd_id=guest.front_door_pin_id,
                        )
                    except Exception as e:
                        logger.error(f"Failed to roll back new front door PIN for guest {guest.reservation_number}: {str(e)}")
                    guest.front_door_pin = None
                    guest.front_door_pin_id = None
                    guest.room_pin_id = None
                    guest.save()
                    messages.error(request, f"Failed to generate new room PIN: {room_response.get('errmsg', 'Unknown error')}")
                    return redirect('manage_checkin_checkout', guest_id=guest.id)
                guest.room_pin_id = room_response["keyboardPwdId"]
                guest.save()
                AuditLog.objects.create(
                    user=request.user,
                    action="Guest PIN Regenerated (Check-In/Check-Out Update)",
                    object_type="Guest",
                    object_id=guest.id,
                    details=f"Regenerated PIN {new_pin} for reservation {guest.reservation_number} due to check-in/check-out time update"
                )
                # Send update message after PIN regeneration
                if guest.phone_number or guest.email:
                    guest.send_update_message()
                messages.success(request, f"New PIN (for both front door and room) generated: {new_pin}. The guest can also unlock the doors remotely during check-in or from the room detail page.")
            except Exception as e:
                logger.error(f"Failed to generate new PIN for guest {guest.reservation_number}: {str(e)}")
                messages.error(request, f"Failed to generate new PIN: {str(e)}")
                return redirect('manage_checkin_checkout', guest_id=guest.id)

        else:
            # Update guest details
            early_checkin_time = request.POST.get('early_checkin_time')
            late_checkout_time = request.POST.get('late_checkout_time')

            # Convert time strings (e.g., "12:00") to time objects
            if early_checkin_time:
                try:
                    early_checkin_time = datetime.datetime.strptime(early_checkin_time, '%H:%M').time()
                    guest.early_checkin_time = early_checkin_time
                except ValueError:
                    messages.error(request, "Invalid early check-in time format. Use HH:MM (e.g., 12:00).")
                    return redirect('manage_checkin_checkout', guest_id=guest.id)
            else:
                guest.early_checkin_time = None  # Revert to default if empty

            if late_checkout_time:
                try:
                    late_checkout_time = datetime.datetime.strptime(late_checkout_time, '%H:%M').time()
                    guest.late_checkout_time = late_checkout_time
                except ValueError:
                    messages.error(request, "Invalid late check-out time format. Use HH:MM (e.g., 12:00).")
                    return redirect('manage_checkin_checkout', guest_id=guest.id)
            else:
                guest.late_checkout_time = None  # Revert to default if empty

            # Check for changes and build the changed_fields list
            changed_fields = []
            if original_early_checkin_time != guest.early_checkin_time:
                changed_fields.append(f"Early Check-In Time (from '{original_early_checkin_time or 'Default (2:00 PM)'}' to '{guest.early_checkin_time or 'Default (2:00 PM)'}')")
            if original_late_checkout_time != guest.late_checkout_time:
                changed_fields.append(f"Late Check-Out Time (from '{original_late_checkout_time or 'Default (11:00 AM)'}' to '{guest.late_checkout_time or 'Default (11:00 AM)'}')")

            # Save the guest with updated fields
            guest.save()

            # Send update message if there are changes and the guest has contact info
            if changed_fields and (guest.phone_number or guest.email):
                guest.send_update_message()

            # Construct the success message with changed fields
            if changed_fields:
                changes_message = "Changes made: " + ", ".join(changed_fields) + "."
            else:
                changes_message = "No changes were made to the check-in/check-out times."
            messages.success(request, f"Check-in/check-out times updated for {guest.full_name}. {changes_message}")

            AuditLog.objects.create(
                user=request.user,
                action="Guest Check-In/Check-Out Updated",
                object_type="Guest",
                object_id=guest.id,
                details=f"Updated check-in/check-out times for reservation {guest.reservation_number}: {', '.join(changed_fields)}"
            )

        return redirect('admin_page')

    return render(request, 'main/manage_checkin_checkout.html', {
        'guest': guest,
    })

def privacy_policy(request):
    return render(request, 'main/privacy_policy.html')

def terms_of_use(request):
    return render(request, 'main/terms_of_use.html')

def terms_conditions(request):
    return render(request, 'main/terms_conditions.html')

def cookie_policy(request):
    return render(request, 'main/cookie_policy.html')

def sitemap(request):
    return render(request, 'main/sitemap.html')

def how_to_use(request):
    return render(request, 'main/how_to_use.html')

@csrf_exempt
def ttlock_callback(request):
    """Handle callback events from TTLock API."""
    if request.method == 'POST':
        try:
            # Log the headers, query parameters, and body
            headers = dict(request.headers)
            query_params = dict(request.GET)
            body = request.body.decode('utf-8')
            # Try to parse the body as JSON for better readability
            try:
                body_json = json.loads(body)
            except json.JSONDecodeError:
                body_json = body
            logger.info(
                f"Received TTLock callback - "
                f"Headers: {headers}, "
                f"Query Params: {query_params}, "
                f"Body: {body_json}"
            )
            return HttpResponse(status=200)
        except Exception as e:
            logger.error(f"Error processing TTLock callback: {str(e)}")
            return HttpResponse(status=500)
    logger.warning(f"Invalid method for TTLock callback: {request.method}")
    return HttpResponse(status=405)

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.has_perm('main.can_give_access'), login_url='/unauthorized/')
def give_access(request):
    """Allow admin to remotely unlock doors for active guests and manually for staff/visitors."""
    guests = Guest.objects.filter(is_archived=False).order_by('check_in_date')
    all_rooms = Room.objects.all()  # Fetch all rooms (e.g., Room 1, Room 2, Room 3, Room 4)
    front_door_lock = TTLock.objects.filter(is_front_door=True).first()  # Get the front door lock

    if request.method == "POST" and "unlock_door" in request.POST:
        # Check rate limit (6 per minute per user)
        if getattr(request, 'limited', False):  # Set by ratelimit if exceeded
            messages.error(request, "Too many attempts, please wait a moment.")
            return redirect('give_access')

        try:
            lock_id = request.POST.get("lock_id")
            door_type = request.POST.get("door_type")

            client = TTLockClient()
            max_retries = 3

            if door_type in ["front", "room"] and "guest_id" in request.POST:
                # Handle guest-specific unlock
                guest_id = request.POST.get("guest_id")
                guest = get_object_or_404(Guest, id=guest_id, is_archived=False)
                if door_type == "front":
                    lock = front_door_lock  # Use the front door lock directly
                else:  # door_type == "room"
                    lock = guest.assigned_room.ttlock
                if not lock:
                    raise TTLock.DoesNotExist("Lock not found for the specified door.")
            elif door_type in ["manual_front", "manual_room"]:
                # Handle manual unlock
                lock = get_object_or_404(TTLock, lock_id=lock_id)
            else:
                messages.warning(request, "Invalid unlock request. Please try again.")
                return redirect('give_access')

            for attempt in range(max_retries):
                try:
                    unlock_response = client.unlock_lock(lock_id=str(lock.lock_id))
                    if "errcode" in unlock_response and unlock_response["errcode"] != 0:
                        error_msg = unlock_response.get('errmsg', 'Unknown error')
                        logger.error(f"Failed to unlock {door_type} (Lock ID: {lock.lock_id}): {error_msg}")
                        if attempt == max_retries - 1:
                            if door_type in ["front", "room"]:
                                messages.error(request, f"Failed to unlock the {door_type} door for {guest.full_name}. Please try again or contact support.")
                            else:
                                messages.error(request, f"Failed to unlock {door_type.replace('manual_', '')} door. Please try again or contact support.")
                        else:
                            continue
                    else:
                        if door_type in ["front", "room"]:
                            messages.success(request, f"The {door_type} door has been unlocked for {guest.full_name}.")
                        else:
                            messages.success(request, f"The {door_type.replace('manual_', '')} door has been unlocked.")
                        break
                except Exception as e:
                    logger.error(f"Failed to unlock {door_type} (Lock ID: {lock.lock_id}): {str(e)}")
                    if attempt == max_retries - 1:
                        if door_type in ["front", "room"]:
                            messages.error(request, f"Failed to unlock the {door_type} door for {guest.full_name}. Please try again or contact support.")
                        else:
                            messages.error(request, f"Failed to unlock {door_type.replace('manual_', '')} door. Please try again or contact support.")
                    else:
                        continue

        except TTLock.DoesNotExist:
            logger.error(f"Lock with ID {lock_id} not configured in the database.")
            messages.error(request, "The requested lock is not configured. Please contact support.")
        except Guest.DoesNotExist:
            logger.error(f"Guest with ID {guest_id} not found or is archived.")
            messages.error(request, "Guest not found or is no longer active.")
        except Exception as e:
            logger.error(f"Unexpected error during unlock: {str(e)}")
            messages.error(request, "An unexpected error occurred. Please try again or contact support.")

        return redirect('give_access')

    return render(request, "main/give_access.html", {
        "guests": guests,
        "all_rooms": all_rooms,
        "front_door_lock": front_door_lock,
    })

# Apply rate limit to the entire view, but we'll check 'limited' only for POST
give_access = ratelimit(key='user', rate='6/m', method='POST', block=True)(give_access)

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def user_management(request):
    """Allow superusers to manage admin users (add, edit, reset password, delete)."""
    User = get_user_model()
    users = User.objects.filter(is_superuser=False, is_staff=True).order_by('username')  # Only show admin users (staff, not superusers)

    # Define available groups (roles) for permissions
    groups = Group.objects.all()

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "add_user":
            username = request.POST.get("username").strip()
            email = request.POST.get("email").strip()
            password = request.POST.get("password").strip()
            group_name = request.POST.get("group")

            if not username or not password or not group_name:
                messages.error(request, "Username, password, and role are required.")
                return redirect('user_management')

            if User.objects.filter(username=username).exists():
                messages.error(request, "Username already exists.")
                return redirect('user_management')

            try:
                user = User.objects.create(
                    username=username,
                    email=email,
                    password=make_password(password),
                    is_staff=True,  # Mark as admin user (can log in to admin_page)
                    is_superuser=False,
                )
                group = Group.objects.get(name=group_name)
                user.groups.add(group)
                user.save()
                logger.info(f"Superuser {request.user.username} created new admin user: {username} with role {group_name}")
                messages.success(request, f"User {username} created successfully and assigned to {group_name} role.")
            except Exception as e:
                logger.error(f"Failed to create user {username}: {str(e)}")
                messages.error(request, f"Failed to create user: {str(e)}")

        elif action == "edit_user":
            user_id = request.POST.get("user_id")
            user = get_object_or_404(User, id=user_id, is_superuser=False, is_staff=True)
            group_name = request.POST.get("group")

            try:
                group = Group.objects.get(name=group_name)
                user.groups.clear()  # Remove existing groups
                user.groups.add(group)
                user.save()
                logger.info(f"Superuser {request.user.username} updated role for user {user.username} to {group_name}")
                messages.success(request, f"User {user.username}'s role updated to {group_name}.")
            except Exception as e:
                logger.error(f"Failed to update user {user.username}: {str(e)}")
                messages.error(request, f"Failed to update user: {str(e)}")

        elif action == "reset_password":
            user_id = request.POST.get("user_id")
            user = get_object_or_404(User, id=user_id, is_superuser=False, is_staff=True)
            new_password = request.POST.get("new_password").strip()

            if not new_password:
                messages.error(request, "New password is required.")
                return redirect('user_management')

            try:
                user.password = make_password(new_password)
                user.save()
                logger.info(f"Superuser {request.user.username} reset password for user {user.username}")
                messages.success(request, f"Password for {user.username} reset successfully. New password: {new_password}")
            except Exception as e:
                logger.error(f"Failed to reset password for user {user.username}: {str(e)}")
                messages.error(request, f"Failed to reset password: {str(e)}")

        elif action == "delete_user":
            user_id = request.POST.get("user_id")
            user = get_object_or_404(User, id=user_id, is_superuser=False, is_staff=True)
            username = user.username
            try:
                user.delete()
                logger.info(f"Superuser {request.user.username} deleted user {username}")
                messages.success(request, f"User {username} deleted successfully.")
            except Exception as e:
                logger.error(f"Failed to delete user {username}: {str(e)}")
                messages.error(request, f"Failed to delete user: {str(e)}")

        return redirect('user_management')

    return render(request, "main/user_management.html", {
        "users": users,
        "groups": groups,
    })

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.has_perm('main.manage_rooms'), login_url='/unauthorized/')
def room_management(request):
    """View to manage rooms (add, edit, delete)."""
    rooms = Room.objects.all()
    ttlocks = TTLock.objects.all()  # For assigning locks to rooms

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "populate_locks":
            locks_json = request.POST.get("locks_json", "").strip()
            if not locks_json:
                messages.error(request, "Please enter JSON data in the textarea.")
                return redirect('room_management')

            try:
                # Parse the JSON data
                ttlock_data = json.loads(locks_json)

                # Validate the JSON structure
                if not isinstance(ttlock_data, list):
                    messages.error(request, "JSON data must be an array of lock objects.")
                    return redirect('room_management')

                for data in ttlock_data:
                    if not isinstance(data, dict) or 'name' not in data or 'lock_id' not in data:
                        messages.error(request, "Each lock entry must have 'name' and 'lock_id' fields.")
                        return redirect('room_management')

                    # Create TTLock entries
                    lock_id = data["lock_id"]
                    if not isinstance(lock_id, (int, str)) or not str(lock_id).isdigit():
                        messages.error(request, "Lock ID must be a valid number.")
                        return redirect('room_management')
                    lock_id = int(lock_id)
                    if TTLock.objects.filter(lock_id=lock_id).exists():
                        messages.error(request, f"Lock ID {lock_id} is already in use.")
                        return redirect('room_management')

                    TTLock.objects.get_or_create(lock_id=lock_id, defaults={"name": data["name"]})

                # Associate TTLock with Rooms (only for room-specific locks)
                room_locks = {item["name"]: item["lock_id"] for item in ttlock_data if item["name"].startswith("Room")}
                for room_name, lock_id in room_locks.items():
                    room = Room.objects.get_or_create(name=room_name)[0]  # Create room if it doesn't exist
                    ttlock = TTLock.objects.get(lock_id=lock_id)
                    room.ttlock = ttlock
                    room.save()

                messages.success(request, "Successfully populated TTLock entries and associations from JSON data.")
            except json.JSONDecodeError:
                messages.error(request, "Invalid JSON format. Please check your syntax.")
            except Room.DoesNotExist:
                messages.error(request, "One or more rooms in the JSON data do not exist.")
            except Exception as e:
                logger.error(f"Failed to populate locks: {str(e)}")
                messages.error(request, f"Failed to populate locks: {str(e)}")

        elif action == "add_from_inputs":
            new_room_name = request.POST.get("new_room_name").strip()
            new_lock_id = request.POST.get("new_lock_id")

            if not new_room_name or not new_lock_id:
                messages.error(request, "Room name and lock ID are required.")
                return redirect('room_management')

            try:
                # Validate and create new TTLock
                if not new_lock_id.isdigit():
                    messages.error(request, "Lock ID must be a valid number.")
                    return redirect('room_management')
                new_lock_id = int(new_lock_id)
                if TTLock.objects.filter(lock_id=new_lock_id).exists():
                    messages.error(request, f"Lock ID {new_lock_id} is already in use.")
                    return redirect('room_management')

                new_lock_name = new_room_name + " Lock"  # Auto-generate lock name based on room name
                new_ttlock = TTLock.objects.create(
                    name=new_lock_name,
                    lock_id=new_lock_id,
                    is_front_door=False
                )
                room = Room.objects.create(
                    name=new_room_name,
                    video_url="",  # Default empty, can be added later via "Add New Room" form
                    description="",  # Default empty
                    image="",  # Default empty
                    ttlock=new_ttlock,
                )
                AuditLog.objects.create(
                    user=request.user,
                    action="Room Created",
                    object_type="Room",
                    object_id=room.id,
                    details=f"Created room '{new_room_name}' with lock '{new_lock_name}' (Lock ID: {new_lock_id})"
                )
                messages.success(request, f"Room '{new_room_name}' and lock '{new_lock_name}' added successfully.")
            except ValueError:
                messages.error(request, "Invalid lock ID format.")
            except Exception as e:
                logger.error(f"Failed to add room and lock: {str(e)}")
                messages.error(request, f"Failed to add room and lock: {str(e)}")

        elif action == "add_room":
            name = request.POST.get("name").strip()
            video_url = request.POST.get("video_url").strip()
            description = request.POST.get("description").strip() or None
            image_url = request.POST.get("image").strip() or None
            ttlock_id = request.POST.get("ttlock")
            new_lock_name = request.POST.get("new_lock_name").strip()
            new_lock_id = request.POST.get("new_lock_id")

            if not name or not video_url:
                messages.error(request, "Room name and video URL are required.")
                return redirect('room_management')

            try:
                if ttlock_id:
                    # Use existing TTLock if selected
                    ttlock = TTLock.objects.get(id=ttlock_id) if ttlock_id else None
                elif new_lock_name and new_lock_id:
                    # Create new TTLock if no existing lock is selected
                    if not new_lock_id.isdigit():
                        messages.error(request, "Lock ID must be a valid number.")
                        return redirect('room_management')
                    new_lock_id = int(new_lock_id)
                    if TTLock.objects.filter(lock_id=new_lock_id).exists():
                        messages.error(request, "This lock ID is already in use.")
                        return redirect('room_management')

                    ttlock = TTLock.objects.create(
                        name=new_lock_name,
                        lock_id=new_lock_id,
                        is_front_door=False
                    )
                else:
                    messages.error(request, "Please either select an existing lock or provide a new lock name and ID.")
                    return redirect('room_management')

                room = Room.objects.create(
                    name=name,
                    video_url=video_url,
                    description=description,
                    image=image_url,
                    ttlock=ttlock,
                )
                AuditLog.objects.create(
                    user=request.user,
                    action="Room Created",
                    object_type="Room",
                    object_id=room.id,
                    details=f"Created room '{room.name}' with lock '{ttlock.name}' (Lock ID: {ttlock.lock_id})"
                )
                messages.success(request, f"Room '{room.name}' added successfully with lock '{ttlock.name}'.")
            except TTLock.DoesNotExist:
                messages.error(request, "Invalid TTLock selected.")
                return redirect('room_management')
            except ValueError:
                messages.error(request, "Invalid lock ID format.")
                return redirect('room_management')
            except Exception as e:
                logger.error(f"Failed to add room and lock: {str(e)}")
                messages.error(request, f"Failed to add room and lock: {str(e)}")

        elif action == "delete_room":
            room_id = request.POST.get("room_id")
            room = get_object_or_404(Room, id=room_id)
            room_name = room.name
            try:
                # Check if the TTLock is only associated with this room before deleting
                delete_lock = False
                ttlock_name = None
                if room.ttlock:
                    ttlock = room.ttlock
                    ttlock_name = ttlock.name
                    if Room.objects.filter(ttlock=ttlock).count() == 1:
                        delete_lock = True
                        ttlock.delete()
                room.delete()
                AuditLog.objects.create(
                    user=request.user,
                    action="Room Deleted",
                    object_type="Room",
                    object_id=room_id,
                    details=f"Deleted room '{room_name}'" + (f" and lock '{ttlock_name}'" if delete_lock else "")
                )
                messages.success(request, f"Room '{room_name}' deleted successfully." + (f" Associated lock '{ttlock_name}' was also deleted." if delete_lock else ""))
            except Exception as e:
                logger.error(f"Failed to delete room {room_id}: {str(e)}")
                messages.error(request, f"Failed to delete room: {str(e)}")

        return redirect('room_management')

    return render(request, "main/room_management.html", {
        "rooms": rooms,
        "ttlocks": ttlocks,
    })

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.has_perm('main.manage_rooms'), login_url='/unauthorized/')
def edit_room(request, room_id):
    """View to edit an existing room."""
    room = get_object_or_404(Room, id=room_id)
    ttlocks = TTLock.objects.all()  # For assigning existing locks
    old_ttlock = room.ttlock  # Store the old TTLock for potential deletion

    if request.method == "POST":
        name = request.POST.get("name").strip()
        video_url = request.POST.get("video_url").strip()
        description = request.POST.get("description").strip() or None
        image_url = request.POST.get("image").strip() or None
        ttlock_id = request.POST.get("ttlock")
        new_lock_name = request.POST.get("new_lock_name").strip()
        new_lock_id = request.POST.get("new_lock_id")

        if not name or not video_url:
            messages.error(request, "Room name and video URL are required.")
            return render(request, "main/edit_room.html", {
                "room": room,
                "ttlocks": ttlocks,
            })

        try:
            if new_lock_name and new_lock_id:
                if not new_lock_id.isdigit():
                    messages.error(request, "Lock ID must be a valid number.")
                    return render(request, "main/edit_room.html", {
                        "room": room,
                        "ttlocks": ttlocks,
                    })
                new_lock_id = int(new_lock_id)
                if TTLock.objects.filter(lock_id=new_lock_id).exclude(id=room.ttlock.id if room.ttlock else None).exists():
                    messages.error(request, "This lock ID is already in use.")
                    return render(request, "main/edit_room.html", {
                        "room": room,
                        "ttlocks": ttlocks,
                    })

                # Create or update new TTLock
                if room.ttlock and room.ttlock.lock_id == new_lock_id:
                    room.ttlock.name = new_lock_name
                    room.ttlock.save()
                else:
                    new_ttlock = TTLock.objects.create(
                        name=new_lock_name,
                        lock_id=new_lock_id,
                        is_front_door=False
                    )
                    # Update room.ttlock and save to ensure the database reflects the new association
                    room.ttlock = new_ttlock
                    room.save()
                    # Now check if the old TTLock is unused and delete it
                    if old_ttlock and old_ttlock != new_ttlock and Room.objects.filter(ttlock=old_ttlock).count() == 0:
                        old_ttlock.delete()
                        logger.info(f"Deleted old TTLock '{old_ttlock.name}' (Lock ID: {old_ttlock.lock_id}) after replacing with new lock")
            elif ttlock_id:
                ttlock = TTLock.objects.get(id=ttlock_id) if ttlock_id else None
                # Update room.ttlock and save to ensure the database reflects the new association
                room.ttlock = ttlock
                room.save()
                # Delete the old TTLock if it exists, is different, and is no longer used by other rooms
                if old_ttlock and old_ttlock != ttlock and Room.objects.filter(ttlock=old_ttlock).count() == 0:
                    old_ttlock.delete()
                    logger.info(f"Deleted old TTLock '{old_ttlock.name}' (Lock ID: {old_ttlock.lock_id}) after reassigning to new lock")

            else:
                messages.error(request, "Please either select an existing lock or provide a new lock name and ID.")
                return render(request, "main/edit_room.html", {
                    "room": room,
                    "ttlocks": ttlocks,
                })

            # Update other room fields
            room.name = name
            room.video_url = video_url
            room.description = description
            room.image = image_url
            room.save()
            AuditLog.objects.create(
                user=request.user,
                action="Room Updated",
                object_type="Room",
                object_id=room.id,
                details=f"Updated room '{room.name}' (Video URL: {video_url}, Description: {description}, Image: {image_url}, Lock: {room.ttlock.name if room.ttlock else 'None'})"
            )
            messages.success(request, f"Room '{room.name}' updated successfully.")
            logger.info(f"Admin {request.user.username} updated room '{room.name}'")
            # Redirect with fragment manually appended
            return redirect(reverse('room_management') + '#existing-rooms')
        except TTLock.DoesNotExist:
            messages.error(request, "Invalid TTLock selected.")
        except Exception as e:
            logger.error(f"Failed to update room {room_id}: {str(e)}")
            messages.error(request, f"Failed to update room: {str(e)}")

        return render(request, "main/edit_room.html", {
            "room": room,
            "ttlocks": ttlocks,
        })

    return render(request, "main/edit_room.html", {
        "room": room,
        "ttlocks": ttlocks,
    })

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def audit_logs(request):
    """View to display audit logs for administrative actions with filtering, sorting, and pagination."""
    # Default query set
    logs = AuditLog.objects.all()

    # Handle search
    search_query = request.GET.get('search', '').strip()
    if search_query:
        logs = logs.filter(
            Q(user__username__icontains=search_query) |
            Q(action__icontains=search_query) |
            Q(object_type__icontains=search_query) |
            Q(details__icontains=search_query) |
            Q(timestamp__icontains=search_query)
        )

    # Handle date range filter
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if start_date:
        logs = logs.filter(timestamp__gte=start_date)
    if end_date:
        logs = logs.filter(timestamp__lte=end_date + ' 23:59:59')

    # Handle sorting
    sort_by = request.GET.get('sort', '-timestamp')  # Default to descending timestamp
    if sort_by not in ['timestamp', '-timestamp', 'user', '-user', 'action', '-action', 'object_type', '-object_type', 'object_id', '-object_id']:
        sort_by = '-timestamp'  # Fallback to default if invalid
    logs = logs.order_by(sort_by)

    # Handle pagination
    per_page = request.GET.get('per_page', '50')  # Default to 50
    try:
        per_page = int(per_page)
        if per_page not in [25, 50, 100]:
            per_page = 50  # Fallback to default if invalid
    except ValueError:
        per_page = 50
    paginator = Paginator(logs, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Prepare context
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'start_date': start_date or '',
        'end_date': end_date or '',
        'sort_by': sort_by,
        'per_page': per_page,
        'sort_options': [
            ('timestamp', 'Timestamp (Newest First)'),
            ('-timestamp', 'Timestamp (Oldest First)'),
            ('user', 'User (A-Z)'),
            ('-user', 'User (Z-A)'),
            ('action', 'Action (A-Z)'),
            ('-action', 'Action (Z-A)'),
            ('object_type', 'Object Type (A-Z)'),
            ('-object_type', 'Object Type (Z-A)'),
            ('object_id', 'Object ID (Ascending)'),
            ('-object_id', 'Object ID (Descending)'),
        ],
        'per_page_options': [25, 50, 100],
    }

    return render(request, 'main/audit_logs.html', context)

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def guest_details(request, guest_id):
    """Display detailed information for a guest, including uploaded IDs, restricted to superusers."""
    guest = get_object_or_404(Guest, id=guest_id)
    id_uploads = guest.id_uploads.all()  # Fetch all uploaded IDs for this guest

    # Fetch all reservations (past and present) for this guest
    all_reservations = Guest.objects.filter(full_name__iexact=guest.full_name).order_by('-check_in_date')

    # Handle POST request to block review message
    if request.method == 'POST' and 'block_review' in request.POST:
        guest.dont_send_review_message = True
        guest.save()
        # Create audit log entry for blocking review message
        AuditLog.objects.create(
            user=request.user,
            action="block_review_message",
            object_type="Guest",
            object_id=guest.id,
            details=f"Blocked review message for guest {guest.full_name} (Reservation: {guest.reservation_number})"
        )
        messages.success(request, f"Review message blocked for guest {guest.full_name}.")
        return redirect('guest_details', guest_id=guest.id)

    # Generate signed URLs for each ID image
    id_uploads_with_filenames = []
    for upload in id_uploads:
        if upload.id_image:
            # Extract the public ID from the URL (e.g., "guest_ids/2025/3/15/ibvkul4hkv3ew4lvruzd")
            public_id_parts = upload.id_image.split('/image/upload/')[1].split('.')[0]  # Adjust based on URL structure
            public_id = public_id_parts  # The part after /image/upload/ up to the extension
            # Generate a signed URL with an expiration time (e.g., 1 hour = 3600 seconds)
            signed_url, _ = cloudinary_url(
                public_id,
                sign_url=True,
                resource_type="image",
                expires_at=int(time_module.time() + 3600),  # Use time_module.time()
                secure=True
            )
            id_uploads_with_filenames.append({
                'id_image': signed_url,  # Use the signed URL
                'filename': os.path.basename(upload.id_image) if upload.id_image else 'downloaded-image.png'
            })
        else:
            id_uploads_with_filenames.append({
                'id_image': '',
                'filename': 'downloaded-image.png'
            })

    context = {
        'guest': guest,
        'id_uploads': id_uploads_with_filenames,  # Pass dictionary with signed URLs and filename
        'all_reservations': all_reservations,
    }
    return render(request, 'main/guest_details.html', context)

def event_finder(request):
    """Display a page for guests to find events using the Ticketmaster API."""
    # Define today at the top to avoid UnboundLocalError
    today = date.today().strftime('%Y-%m-%d')

    # Get parameters
    city = request.GET.get('city', 'Manchester')  # Default to Manchester
    keyword = request.GET.get('keyword', '')  # Search by event place, band, or musician
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    page = request.GET.get('page', 1)

    # Set default date range if no dates are provided (from today to end of year)
    if not start_date and not end_date:
        start_date = today
        end_date = '2025-12-31'  # Search up to end of 2025 to ensure events are found

    # Build the API query
    params = {
        'apikey': settings.TICKETMASTER_CONSUMER_KEY,
        'city': city,
        'countryCode': 'GB',  # Restrict to UK
        'size': 10,  # 10 events per page
        'page': int(page) - 1,  # Ticketmaster API uses 0-based paging
        'sort': 'date,asc',  # Sort by date ascending
    }

    # Add date filters
    if start_date:
        params['startDateTime'] = f"{start_date}T00:00:00Z"  # Start of day
    if end_date:
        params['endDateTime'] = f"{end_date}T23:59:59Z"  # End of day

    # Add keyword search for event place, band, or musician
    if keyword:
        params['keyword'] = keyword

    # On initial load (no search parameters), prioritize popular events
    major_venues = ['Co-op Live', 'AO Arena', 'Etihad Stadium', 'Old Trafford']
    if not keyword and not start_date == today and not end_date == '2025-12-31':
        params['keyword'] = ','.join(major_venues)  # Search for major venues by default

    # Log the API request for debugging, redacting the API key
    request_url = 'https://app.ticketmaster.com/discovery/v2/events.json' + '?' + '&'.join(
        f"{k}={'[REDACTED]' if k == 'apikey' else v}" for k, v in params.items()
    )
    logger.info(f"Ticketmaster API request URL: {request_url}")

    # Call the Ticketmaster API
    try:
        response = requests.get('https://app.ticketmaster.com/discovery/v2/events.json', params=params)
        response.raise_for_status()  # Raise an error for bad status codes
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Ticketmaster API error: {str(e)}")
        data = {'_embedded': {'events': []}, 'page': {'totalElements': 0, 'totalPages': 1}}

    # Extract events and preprocess to filter popular events
    events = []
    for event in data.get('_embedded', {}).get('events', []):
        # Check ticket price (if available)
        price_info = event.get('priceRanges', [{}])[0]
        min_price = price_info.get('min', 0)
        max_price = price_info.get('max', 0)
        ticket_price = max(min_price, max_price) if min_price or max_price else 0

        # Check if sold out (status code or availability)
        is_sold_out = event.get('dates', {}).get('status', {}).get('code') == 'soldout'

        # Check if at a major venue
        venue_name = event.get('_embedded', {}).get('venues', [{}])[0].get('name', '') if event.get('_embedded', {}).get('venues') else 'Unknown Venue'
        is_major_venue = any(major_venue in venue_name for major_venue in major_venues)

        # Consider an event popular if sold out, price > £40, or at a major venue
        is_popular = is_sold_out or ticket_price > 40 or is_major_venue

        # On initial load, only include popular events
        if not keyword and start_date == today and end_date == '2025-12-31' and not is_popular:
            continue

        event_data = {
            'name': event.get('name'),
            'date': event.get('dates', {}).get('start', {}).get('localDate'),
            'time': event.get('dates', {}).get('start', {}).get('localTime'),
            'venue': venue_name,
            'url': event.get('url'),
            'image': event.get('images', [{}])[0].get('url') if event.get('images') else None,  # Extract event image
            'is_sold_out': is_sold_out,
            'ticket_price': f"£{ticket_price}" if ticket_price else "N/A",
        }
        events.append(event_data)

    total_pages = data.get('page', {}).get('totalPages', 1)
    total_elements = data.get('page', {}).get('totalElements', 0)

    # Limit page range to 5 pages around the current page
    page_range = []
    start_page = max(1, int(page) - 2)
    end_page = min(total_pages, int(page) + 2)
    for i in range(start_page, end_page + 1):
        page_range.append(i)

    context = {
        'events': events,
        'city': city,
        'keyword': keyword,
        'start_date': start_date,
        'end_date': end_date,
        'current_page': int(page),
        'total_pages': total_pages,
        'total_elements': total_elements,
        'page_range': page_range,
    }
    return render(request, 'main/event_finder.html', context)

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def price_suggester(request):
    """Suggest room prices based on popular events near M11 3NP (display only)."""
    # Base room price
    base_price = 50  # £50 as per your requirement

    # Manually collected average hotel price near M11 3NP (e.g., from ibis Budget, Dakota Manchester)
    average_hotel_price = 80  # Example value; adjust as needed

    # Default date range (from today to 365 days from now)
    today = date.today()
    start_date = request.GET.get('start_date', today.strftime('%Y-%m-%d'))
    end_date = request.GET.get('end_date', (today + timedelta(days=365)).strftime('%Y-%m-%d'))
    keyword = request.GET.get('keyword', '')  # Search by event location (e.g., Co-op Live, AO Arena)
    show_sold_out = request.GET.get('show_sold_out', '')  # Filter for sold-out events
    page = request.GET.get('page', 1)

    # Fetch events for display with pagination
    display_params = {
        'apikey': settings.TICKETMASTER_CONSUMER_KEY,
        'city': 'Manchester',
        'countryCode': 'GB',
        'size': 10,
        'page': int(page) - 1,
        'sort': 'date,asc',
        'startDateTime': f"{start_date}T00:00:00Z",
        'endDateTime': f"{end_date}T23:59:59Z",
    }
    if keyword:
        display_params['keyword'] = keyword

    try:
        display_response = requests.get('https://app.ticketmaster.com/discovery/v2/events.json', params=display_params)
        display_response.raise_for_status()
        display_data = display_response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Ticketmaster API display error: {str(e)}")
        display_data = {'_embedded': {'events': []}}

    # Extract events for display
    display_events = display_data.get('_embedded', {}).get('events', [])
    major_venues = settings.MAJOR_VENUES
    suggestions = []
    for event in display_events:
        price_info = event.get('priceRanges', [{}])[0]
        min_price = price_info.get('min', 0)
        max_price = price_info.get('max', 0)
        ticket_price = max(min_price, max_price) if min_price or max_price else 0
        is_sold_out = event.get('dates', {}).get('status', {}).get('code') == 'soldout'
        venue_name = event.get('_embedded', {}).get('venues', [{}])[0].get('name', '') if event.get('_embedded', {}).get('venues') else 'Unknown Venue'
        is_major_venue = any(major_venue in venue_name for major_venue in major_venues)
        is_popular = is_sold_out or ticket_price > 40 or is_major_venue

        if show_sold_out and not is_sold_out:
            continue
        if not show_sold_out and not is_popular:
            continue

        suggested_price = 150 if is_sold_out or is_major_venue else 100
        event_details = {
            'event_id': event.get('id'),
            'name': event.get('name'),
            'date': event.get('dates', {}).get('start', {}).get('localDate'),
            'venue': venue_name,
            'ticket_price': f"£{ticket_price}" if ticket_price else "N/A",
            'suggested_price': f"£{suggested_price}",
            'image': event.get('images', [{}])[0].get('url') if event.get('images') else None,
        }
        suggestions.append(event_details)

    total_pages = display_data.get('page', {}).get('totalPages', 1)
    total_elements = display_data.get('page', {}).get('totalElements', 0)

    # Limit page range to 5 pages around the current page
    page_range = []
    start_page = max(1, int(page) - 2)
    end_page = min(total_pages, int(page) + 2)
    for i in range(start_page, end_page + 1):
        page_range.append(i)

    context = {
        'suggestions': suggestions,
        'base_price': f"£{base_price}",
        'average_hotel_price': f"£{average_hotel_price}",
        'start_date': start_date,
        'end_date': end_date,
        'keyword': keyword,
        'show_sold_out': show_sold_out,
        'current_page': int(page),
        'total_pages': total_pages,
        'total_elements': total_elements,
        'page_range': page_range,
    }
    return render(request, 'main/price_suggester.html', context)

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def block_review_messages(request):
    """Allow superusers to block review messages for current guests."""
    search_query = request.GET.get('search', '')
    guests = Guest.objects.filter(is_archived=False)

    if search_query:
        guests = guests.filter(
            Q(full_name__icontains=search_query) |
            Q(reservation_number__icontains=search_query) |
            Q(check_in_date__icontains=search_query)
        )

    if request.method == 'POST':
        guest_ids = request.POST.getlist('guest_ids')  # List of selected guest IDs
        if guest_ids:
            # Update the selected guests to block review messages
            Guest.objects.filter(id__in=guest_ids).update(dont_send_review_message=True)
            messages.success(request, f"Blocked review messages for {len(guest_ids)} guest(s).")
            logger.info(f"Superuser {request.user.username} blocked review messages for guests with IDs: {guest_ids}")
        return redirect('block_review_messages')

    context = {
        'guests': guests,
        'search_query': search_query,
    }
    return render(request, 'main/block_review_message.html', context)

@csrf_exempt
def sms_reply_handler(request):
    if request.method == 'POST':
        from_number = request.POST.get('From', 'Unknown')
        message_body = request.POST.get('Body', 'No message')
        logger.info(f"Received SMS reply from {from_number}: {message_body}")

        admin_phone_number = settings.ADMIN_PHONE_NUMBER
        guest = Guest.objects.filter(phone_number=from_number).first()
        guest_info = f" ({guest.full_name}, #{guest.reservation_number})" if guest else ""

        forwarded_message = (
            f"Guest Reply from {from_number}{guest_info}: {message_body}\n"
            f"[Forwarded to you on {admin_phone_number}]"
        )

        try:
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            message = client.messages.create(
                body=forwarded_message,
                from_=settings.TWILIO_PHONE_NUMBER,
                to=admin_phone_number
            )
            logger.info(f"Forwarded SMS reply to {admin_phone_number}, SID: {message.sid}")
        except Exception as e:
            logger.error(f"Failed to forward SMS reply to {admin_phone_number}: {str(e)}")

        return HttpResponse('<Response></Response>', content_type='text/xml')
    return HttpResponse(status=405)


@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.has_perm('main.view_admin_dashboard'), login_url='/unauthorized/')
def message_templates(request):
    """
    Message Templates page - Admin can view and edit all message templates for iCal guests
    """
    from main.models import MessageTemplate

    # Handle template edit
    if request.method == 'POST':
        template_id = request.POST.get('template_id')
        action = request.POST.get('action')

        if action == 'edit':
            template = get_object_or_404(MessageTemplate, id=template_id)
            subject = request.POST.get('subject', '').strip()
            content = request.POST.get('content', '').strip()
            is_active = request.POST.get('is_active') == 'on'

            # Validation
            if not content:
                messages.error(request, "Message content cannot be empty.")
                return redirect('message_templates')

            # Update template
            template.subject = subject
            template.content = content
            template.is_active = is_active
            template.last_edited_by = request.user
            template.save()

            messages.success(request, f"'{template.get_message_type_display()}' updated successfully!")
            logger.info(f"Message template {template.message_type} updated by {request.user.username}")
            return redirect('message_templates')

    # Get all message templates
    templates = MessageTemplate.objects.all().order_by('message_type')

    # Group templates by category for better display
    email_templates = templates.filter(message_type__contains='email')
    sms_templates = templates.filter(message_type__contains='sms')

    # Generate sample preview data
    sample_data = {
        'guest_name': 'John Smith',
        'room_name': 'Room 101',
        'check_in_date': '2025-01-20',
        'check_out_date': '2025-01-22',
        'reservation_number': 'BK1234567890',
        'pin': '1234',
        'room_detail_url': 'https://www.pickarooms.com',
        'platform_name': 'Booking.com',
    }

    return render(request, 'main/message_templates.html', {
        'email_templates': email_templates,
        'sms_templates': sms_templates,
        'sample_data': sample_data,
    })


# =========================================
# Email Enrichment System Views
# =========================================

@csrf_exempt
def handle_twilio_sms_webhook(request):
    """
    Twilio SMS webhook handler for manual room assignment
    Processes SMS replies in format: "2-3" (Room 2, 3 nights) or "A1-3" (Booking A, Room 1, 3 nights)
    """
    from main.services.sms_reply_handler import handle_sms_room_assignment
    from main.enrichment_config import WHITELISTED_SMS_NUMBERS
    import sys

    if request.method != 'POST':
        print(f"[SMS WEBHOOK] Invalid method: {request.method}", file=sys.stderr)
        return HttpResponse('Method not allowed', status=405)

    from_number = request.POST.get('From', '')
    body = request.POST.get('Body', '')

    # Force logging to both logger and stdout/stderr
    print(f"[SMS WEBHOOK] Received SMS from {from_number}: '{body}'", file=sys.stderr)
    logger.info(f"Received SMS from {from_number}: {body}")

    # Security check
    if from_number not in WHITELISTED_SMS_NUMBERS:
        print(f"[SMS WEBHOOK] Unauthorized sender: {from_number}", file=sys.stderr)
        logger.warning(f"Unauthorized SMS from {from_number}")
        return HttpResponse('Unauthorized', status=403)

    try:
        print(f"[SMS WEBHOOK] Calling handler for {from_number}", file=sys.stderr)
        result = handle_sms_room_assignment(from_number, body)
        print(f"[SMS WEBHOOK] Handler result: {result}", file=sys.stderr)
        logger.info(f"SMS handler result: {result}")
        return HttpResponse(result, status=200)
    except Exception as e:
        print(f"[SMS WEBHOOK] ERROR: {str(e)}", file=sys.stderr)
        logger.error(f"Error processing SMS: {str(e)}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        return HttpResponse(f"Error: {str(e)}", status=500)


@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.has_perm('main.view_reservation'), login_url='/unauthorized/')
def pending_enrichments_page(request):
    """
    Phase 5 Dashboard: Show unenriched reservations (iCal-driven flow)
    Displays reservations awaiting enrichment with real-time status tracking
    """
    from main.models import Reservation, EnrichmentLog, PendingEnrichment
    from django.db.models import Q

    # Get unenriched reservations (booking_reference is empty string for unenriched)
    unenriched = Reservation.objects.filter(
        platform='booking',
        status='confirmed',
        guest__isnull=True,
        booking_reference=''
    ).select_related('room').order_by('check_in_date')

    # Build unenriched data with enrichment status
    unenriched_data = []
    for reservation in unenriched:
        # Get latest enrichment log for this reservation
        latest_log = EnrichmentLog.objects.filter(
            reservation=reservation
        ).order_by('-timestamp').first()

        # Determine status badge
        if latest_log:
            if latest_log.action == 'email_search_started':
                attempt = latest_log.details.get('attempt', 1) if isinstance(latest_log.details, dict) else 1
                status = f"Searching Email (Attempt {attempt}/4)"
                badge_class = 'warning' if attempt <= 2 else 'orange'
            elif latest_log.action == 'email_not_found_alerted':
                status = "Email Not Found - SMS Sent"
                badge_class = 'danger'
            elif latest_log.action == 'collision_detected':
                status = "Collision Detected - SMS Sent"
                badge_class = 'info'
            elif latest_log.action == 'email_found_multi_room':
                status = "Multi-Room Booking - Confirmation Sent"
                badge_class = 'purple'
            else:
                status = "Awaiting Manual Enrichment"
                badge_class = 'danger'
        else:
            status = "Pending"
            badge_class = 'secondary'

        nights = (reservation.check_out_date - reservation.check_in_date).days

        unenriched_data.append({
            'id': reservation.id,
            'room': reservation.room,
            'check_in_date': reservation.check_in_date,
            'check_out_date': reservation.check_out_date,
            'nights': nights,
            'platform': 'Booking.com',
            'status': status,
            'badge_class': badge_class,
            'latest_log': latest_log,
        })

    # Get recently enriched reservations (last 20)
    enriched = Reservation.objects.filter(
        platform='booking',
        status='confirmed',
        guest__isnull=True
    ).exclude(
        booking_reference=''
    ).select_related('room').order_by('-updated_at')[:20]

    # Build enriched data
    enriched_data = []
    for reservation in enriched:
        # Get enrichment method from logs
        enrichment_log = EnrichmentLog.objects.filter(
            Q(booking_reference=reservation.booking_reference) |
            Q(reservation=reservation)
        ).order_by('-timestamp').first()

        if enrichment_log:
            if enrichment_log.action == 'email_found_matched':
                method = "Auto (Email)"
            elif enrichment_log.action == 'manual_enrichment_sms':
                method = "Manual (SMS)"
            elif enrichment_log.action == 'multi_enrichment_sms':
                method = "Multi (SMS)"
            elif enrichment_log.action == 'xls_enriched_single':
                method = "XLS Upload"
            else:
                method = "Manual"
        else:
            method = "Unknown"

        nights = (reservation.check_out_date - reservation.check_in_date).days

        enriched_data.append({
            'id': reservation.id,
            'booking_reference': reservation.booking_reference,
            'room': reservation.room,
            'check_in_date': reservation.check_in_date,
            'check_out_date': reservation.check_out_date,
            'nights': nights,
            'platform': 'Booking.com',
            'method': method,
        })

    # Get recent enrichment logs (last 50)
    logs = EnrichmentLog.objects.select_related(
        'reservation', 'room'
    ).order_by('-timestamp')[:50]

    logs_data = []
    for log in logs:
        logs_data.append({
            'timestamp': log.timestamp,
            'action': log.get_action_display(),
            'booking_reference': log.booking_reference,
            'room': log.room.name if log.room else '---',
            'method': log.method or '---',
            'details': str(log.details) if log.details else '---',
        })

    # OLD MODEL DATA (for backward compatibility - keep for now)
    old_pending = PendingEnrichment.objects.filter(
        status__in=['failed_awaiting_manual', 'pending']
    ).count()

    return render(request, 'main/pending_enrichments.html', {
        'unenriched_reservations': unenriched_data,
        'enriched_reservations': enriched_data,
        'enrichment_logs': logs_data,
        'total_unenriched': len(unenriched_data),
        'total_enriched': len(enriched_data),
        'total_logs': len(logs_data),
        'old_pending_count': old_pending,
    })


@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.has_perm('main.add_reservation'), login_url='/unauthorized/')
def xls_upload_page(request):
    """
    Admin page for uploading Booking.com XLS exports
    Supports multi-room bookings
    """
    from main.services.xls_parser import process_xls_file
    from main.models import CSVEnrichmentLog

    if request.method == 'POST' and request.FILES.get('xls_file'):
        xls_file = request.FILES['xls_file']

        try:
            # Process XLS file
            results = process_xls_file(xls_file, uploaded_by=request.user)

            if results['success']:
                # Show success message
                messages.success(
                    request,
                    f"XLS processed successfully! "
                    f"Created: {results['created_count']}, "
                    f"Updated: {results['updated_count']}, "
                    f"Multi-room bookings: {results['multi_room_count']}"
                )

                # Show room change warnings if any
                if results.get('warnings'):
                    for warning in results['warnings']:
                        if warning['type'] == 'room_change':
                            warning_msg = (
                                f"ROOM CHANGE: Booking {warning['booking_ref']} "
                                f"({warning['guest_name']}, {warning['check_in']}) - "
                            )
                            if warning['removed_rooms']:
                                warning_msg += f"Removed from {', '.join(warning['removed_rooms'])}. "
                            if warning['added_rooms']:
                                warning_msg += f"Added to {', '.join(warning['added_rooms'])}. "
                            warning_msg += "Please check Django admin to delete old reservations."
                            messages.warning(request, warning_msg)
            else:
                messages.error(request, f"Error processing XLS: {results.get('error', 'Unknown error')}")

        except Exception as e:
            logger.error(f"XLS upload error: {str(e)}")
            messages.error(request, f"Error uploading XLS: {str(e)}")

        return redirect('xls_upload_page')

    # Get recent upload logs
    recent_logs = CSVEnrichmentLog.objects.all().order_by('-uploaded_at')[:20]

    logs_data = []
    for log in recent_logs:
        logs_data.append({
            'id': log.id,
            'file_name': log.file_name,
            'uploaded_at': log.uploaded_at,
            'uploaded_by': log.uploaded_by.username if log.uploaded_by else 'System',
            'total_rows': log.total_rows,
            'single_room_count': log.single_room_count,
            'multi_room_count': log.multi_room_count,
            'created_count': log.created_count,
            'updated_count': log.updated_count,
        })

    return render(request, 'main/xls_upload.html', {
        'recent_logs': logs_data,
    })


@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.has_perm('main.view_reservation'), login_url='/unauthorized/')
def enrichment_logs_page(request):
    """
    Admin page showing enrichment audit trail with timeline view option
    """
    from main.models import EnrichmentLog, PendingEnrichment
    from collections import defaultdict
    from django.db.models import Q

    view_mode = request.GET.get('view', 'list')  # 'list' or 'timeline'
    search_ref = request.GET.get('search', '').strip()

    # Base query
    logs_query = EnrichmentLog.objects.all().select_related(
        'pending_enrichment', 'reservation', 'room'
    )

    # Apply search filter
    if search_ref:
        logs_query = logs_query.filter(booking_reference__icontains=search_ref)

    # Limit to recent logs
    logs = logs_query.order_by('-timestamp')[:200]

    if view_mode == 'timeline':
        # Group logs by booking reference to show process flow
        timelines = defaultdict(list)
        for log in logs:
            timelines[log.booking_reference].append({
                'id': log.id,
                'action': log.get_action_display(),
                'action_code': log.action,
                'booking_reference': log.booking_reference,
                'room': log.room.name if log.room else 'N/A',
                'method': log.method if hasattr(log, 'method') else 'N/A',
                'timestamp': log.timestamp,
                'details': log.details,
                'pending_enrichment_id': log.pending_enrichment_id,
                'reservation_id': log.reservation_id,
            })

        # Sort each timeline by timestamp
        for ref in timelines:
            timelines[ref] = sorted(timelines[ref], key=lambda x: x['timestamp'])

        # Get corresponding PendingEnrichment status
        timeline_data = []
        for ref, events in timelines.items():
            # Get latest PendingEnrichment for this booking reference
            pending = PendingEnrichment.objects.filter(
                booking_reference=ref
            ).order_by('-created_at').first()

            timeline_data.append({
                'booking_reference': ref,
                'events': events,
                'pending_status': pending.status if pending else None,
                'pending_attempts': pending.attempts if pending else 0,
                'email_type': pending.get_email_type_display() if pending else 'N/A',
                'check_in_date': pending.check_in_date if pending else None,
            })

        # Sort timelines by most recent event
        timeline_data = sorted(
            timeline_data,
            key=lambda x: x['events'][0]['timestamp'] if x['events'] else timezone.now(),
            reverse=True
        )

        return render(request, 'main/enrichment_logs.html', {
            'view_mode': 'timeline',
            'timelines': timeline_data,
            'total_count': len(timeline_data),
            'search_ref': search_ref,
        })

    else:
        # List view (original)
        logs_data = []
        for log in logs:
            logs_data.append({
                'id': log.id,
                'action': log.get_action_display(),
                'action_code': log.action,
                'booking_reference': log.booking_reference,
                'room': log.room.name if log.room else 'N/A',
                'method': log.method if hasattr(log, 'method') else 'N/A',
                'timestamp': log.timestamp,
                'details': log.details,
            })

        return render(request, 'main/enrichment_logs.html', {
            'view_mode': 'list',
            'logs': logs_data,
            'total_count': len(logs_data),
            'search_ref': search_ref,
        })