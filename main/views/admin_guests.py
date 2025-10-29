"""
Guest CRUD operations for admin.
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
from main.views.base import get_available_rooms
from main.ttlock_utils import TTLockClient
from main.pin_utils import generate_memorable_4digit_pin, add_wakeup_prefix
from main.phone_utils import normalize_phone_to_e164, validate_phone_number
from main.dashboard_helpers import get_current_guests_data, build_entries_list, get_guest_status, get_night_progress
from main.services.sms_reply_handler import handle_sms_room_assignment
from main.enrichment_config import WHITELISTED_SMS_NUMBERS

logger = logging.getLogger('main')


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
                dt.datetime.combine(guest.check_out_date, check_out_time)
            ) + timedelta(days=1)
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
                    new_early_checkin_time = dt.datetime.strptime(early_checkin_time, '%H:%M').time()
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
                    new_late_checkout_time = dt.datetime.strptime(late_checkout_time, '%H:%M').time()
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
                            dt.datetime.combine(check_out_date, check_out_time)
                        ) + timedelta(days=1)
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

# 2. edit_reservation (line ~1742)
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
                reservation.early_checkin_time = dt.datetime.strptime(early_checkin_time, '%H:%M').time()
            except ValueError:
                messages.error(request, "Invalid early check-in time format. Use HH:MM (e.g., 12:00).")
                return redirect('edit_reservation', reservation_id=reservation.id)
        else:
            reservation.early_checkin_time = None  # Revert to default if empty

        # Update late_checkout_time if provided
        if late_checkout_time:
            try:
                reservation.late_checkout_time = dt.datetime.strptime(late_checkout_time, '%H:%M').time()
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

# 3. manual_checkin_reservation (line ~1836)
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
                        dt.datetime.combine(reservation.check_out_date, check_out_time_val)
                    ) + timedelta(days=1)
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
                dt.datetime.combine(reservation.check_out_date, check_out_time_val)
            ) + timedelta(days=1)
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

# 4. delete_guest (line ~2080)
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


# 5. manage_checkin_checkout (line ~2417)
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
                dt.datetime.combine(guest.check_out_date, check_out_time)
            ) + timedelta(days=1)
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
                    early_checkin_time = dt.datetime.strptime(early_checkin_time, '%H:%M').time()
                    guest.early_checkin_time = early_checkin_time
                except ValueError:
                    messages.error(request, "Invalid early check-in time format. Use HH:MM (e.g., 12:00).")
                    return redirect('manage_checkin_checkout', guest_id=guest.id)
            else:
                guest.early_checkin_time = None  # Revert to default if empty

            if late_checkout_time:
                try:
                    late_checkout_time = dt.datetime.strptime(late_checkout_time, '%H:%M').time()
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


# 6. guest_details (line ~3197)
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

# 7. block_review_messages (line ~3465)
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
