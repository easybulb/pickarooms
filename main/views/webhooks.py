"""
External webhooks (CSRF exempt).
Handles TTLock callbacks and Twilio SMS webhooks.

SECURITY NOTE: These endpoints bypass CSRF protection.
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
