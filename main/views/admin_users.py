"""
User management and system audit logs for admin.
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

# 2. audit_logs (line ~3128)
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
