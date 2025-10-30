"""
Booking enrichment workflow views.
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

# 2. pending_enrichments_page (line ~3631)
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
    # Enriched = has booking_reference AND not empty
    enriched = Reservation.objects.filter(
        platform='booking',
        status='confirmed'
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

# 3. enrichment_logs_page (line ~3842)
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

# 4. message_templates (line ~3525)
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
