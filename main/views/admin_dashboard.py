"""
Admin dashboard and reservation management views.
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

# 2. admin_page (line ~1016)
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

# 3. available_rooms (line ~1384)
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

# 4. all_reservations (line ~2155)
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

# 5. delete_reservation (line ~2314)
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

# 6. bulk_delete_reservations (line ~2351)
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

# 7. past_guests (line ~2126)
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
