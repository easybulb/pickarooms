"""
Guest-facing views for check-in, enrichment, and room access.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User, Group, Permission
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.mail import EmailMessage, BadHeaderError, send_mail
from django.conf import settings
from django.http import HttpResponse, JsonResponse, Http404
from django.utils.timezone import now, localtime
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.safestring import mark_safe
from django.db import IntegrityError
from django.db.models import Q
from django.core.paginator import Paginator
from django.contrib import messages
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django_ratelimit.decorators import ratelimit
from datetime import date, datetime, time, timedelta
import pandas as pd
import random
import logging
import uuid
import pytz
import datetime as dt
import re
import json
import os
import sys
import time as time_module
import requests
from langdetect import detect
import cloudinary
import cloudinary.uploader
import cloudinary.api
from cloudinary.utils import cloudinary_url
from django.core.files.storage import default_storage
from cloudinary.uploader import upload as cloudinary_upload
from twilio.rest import Client

from main.models import (
    Guest, Room, ReviewCSVUpload, TTLock, AuditLog, GuestIDUpload,
    PopularEvent, Reservation, RoomICalConfig, MessageTemplate,
    PendingEnrichment, EnrichmentLog, CheckInAnalytics
)
from main.ttlock_utils import TTLockClient
from main.pin_utils import generate_memorable_4digit_pin, add_wakeup_prefix
from main.phone_utils import normalize_phone_to_e164, validate_phone_number
from main.dashboard_helpers import get_current_guests_data, build_entries_list, get_guest_status, get_night_progress
from main.services.sms_reply_handler import handle_sms_room_assignment
from main.enrichment_config import WHITELISTED_SMS_NUMBERS

logger = logging.getLogger('main')


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
            check_out_time = guest.late_checkout_time if guest.late_checkout_time else time(11, 0)
            check_out_datetime = uk_timezone.localize(
                dt.datetime.combine(guest.check_out_date, check_out_time)
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

                    check_out_time = guest.late_checkout_time if guest.late_checkout_time else time(11, 0)
                    end_date = uk_timezone.localize(
                        dt.datetime.combine(guest.check_out_date, check_out_time)
                    ) + timedelta(days=1)
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
            check_out_time = guest.late_checkout_time if guest.late_checkout_time else time(11, 0)
            check_out_datetime = uk_timezone.localize(
                dt.datetime.combine(guest.check_out_date, check_out_time)
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

# Note: checkin alias is defined in __init__.py (checkin = checkin_step1 from main.checkin_views)

# 2. enrich_reservation (line ~392)
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
        # Use transaction to ensure atomic PIN generation
        from django.db import transaction
        
        try:
            with transaction.atomic():
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
                    # Transaction will commit here (guest + reservation links saved)
                    request.session['reservation_number'] = guest.reservation_number
                    del request.session['reservation_to_enrich']
                    logger.info(f"Guest {guest.id} created but PIN generation deferred until check-in date {guest.check_in_date}")
                    messages.info(request, f"Your reservation starts on {guest.check_in_date.strftime('%d %b %Y')}. You can access your PIN on that day.")
                    return redirect('room_detail', room_token=guest.secure_token)

                # Generate TTLock PINs (reuse logic from checkin view)
                front_door_lock = TTLock.objects.get(is_front_door=True)
                room_lock = guest.assigned_room.ttlock
                if not room_lock:
                    logger.error(f"No TTLock assigned to room {guest.assigned_room.name} for guest {guest.reservation_number}")
                    messages.error(request, f"No lock assigned to room {guest.assigned_room.name}. Please contact support.")
                    # Transaction will rollback automatically
                    if 'reservation_to_enrich' in request.session:
                        del request.session['reservation_to_enrich']
                    return redirect("checkin")

                client = TTLockClient()
                uk_timezone = pytz.timezone("Europe/London")
                now_uk_time = timezone.now().astimezone(uk_timezone)

                # Set start_time to NOW so PIN is immediately active
                start_time = int(now_uk_time.timestamp() * 1000)

                check_out_time = guest.late_checkout_time if guest.late_checkout_time else time(11, 0)
                end_date = uk_timezone.localize(
                    dt.datetime.combine(guest.check_out_date, check_out_time)
                ) + timedelta(days=1)
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
                    # Transaction will rollback automatically
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
                    
                    # Raise exception to trigger transaction rollback
                    raise Exception(f"Failed to generate PINs for rooms: {', '.join(failed_rooms)}")
                
                # Store the first room's PIN ID (for backward compatibility with Guest.room_pin_id field)
                guest.room_pin_id = room_pin_ids[0]['pin_id'] if room_pin_ids else None
                guest.save()
                
        except TTLock.DoesNotExist:
            logger.error("Front door lock not configured in the database.")
            messages.error(request, "Front door lock not configured. Please contact support.")
            if 'reservation_to_enrich' in request.session:
                del request.session['reservation_to_enrich']
            return redirect("checkin")
        except Exception as e:
            logger.error(f"Failed to generate PIN for guest (transaction rolled back): {str(e)}")
            messages.error(request, f"Failed to generate PIN: {str(e)}")
            if 'reservation_to_enrich' in request.session:
                del request.session['reservation_to_enrich']
            return redirect("checkin")
            
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

# 3. room_detail (line ~701)
def room_detail(request, room_token):
    reservation_number = request.session.get("reservation_number", None)
    guest = Guest.objects.filter(secure_token=room_token).first()

    if not guest or not reservation_number or guest.reservation_number != reservation_number:
        return redirect("unauthorized")

    room = guest.assigned_room
    uk_timezone = pytz.timezone("Europe/London")
    now_uk_time = timezone.now().astimezone(uk_timezone)

    check_in_time = guest.early_checkin_time if guest.early_checkin_time else time(14, 0)
    try:
        check_in_datetime = uk_timezone.localize(
            dt.datetime.combine(guest.check_in_date, check_in_time)
        )
    except Exception as e:
        logger.error(f"Error localizing check-in datetime for guest {guest.reservation_number}: {str(e)}")
        # Fallback: Use replace instead of localize for DST safety
        check_in_datetime = dt.datetime.combine(guest.check_in_date, check_in_time).replace(tzinfo=uk_timezone)

    check_out_time = guest.late_checkout_time if guest.late_checkout_time else time(11, 0)
    try:
        check_out_datetime = uk_timezone.localize(
            dt.datetime.combine(guest.check_out_date, check_out_time)
        )
    except Exception as e:
        logger.error(f"Error localizing check-out datetime for guest {guest.reservation_number}: {str(e)}")
        # Fallback: Use replace instead of localize for DST safety
        check_out_datetime = dt.datetime.combine(guest.check_out_date, check_out_time).replace(tzinfo=uk_timezone)

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


# 4. report_pin_issue (line ~906)
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
