"""
Room and access management for admin.
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

# 2. edit_room (line ~3021)
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

# 3. give_access (line ~2638)
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
