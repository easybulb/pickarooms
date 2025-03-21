# main/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required, user_passes_test
import requests
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
from .models import Guest, Room, ReviewCSVUpload, TTLock, AuditLog, GuestIDUpload, PopularEvent
from .ttlock_utils import TTLockClient
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

@ratelimit(key='ip', rate='7/m', method='POST', block=True)
def checkin(request):
    if request.method == "POST":
        reservation_number = request.POST.get('reservation_number', '').strip()

        # Step 1: Check for non-archived (active) guest
        guest = Guest.objects.filter(reservation_number=reservation_number, is_archived=False).order_by('-check_in_date').first()

        if guest:
            # Check if the guest has checked out (even if not archived)
            uk_timezone = pytz.timezone("Europe/London")
            now_uk_time = timezone.now().astimezone(uk_timezone)
            check_out_time = guest.late_checkout_time if guest.late_checkout_time else datetime.time(11, 0)
            check_out_datetime = timezone.make_aware(
                datetime.datetime.combine(guest.check_out_date, check_out_time),
                datetime.timezone.utc,
            ).astimezone(uk_timezone)

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

            # Generate a PIN if the guest doesn't have one
            if not guest.front_door_pin:
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
                    start_time = int(now_uk_time.timestamp() * 1000)
                    check_out_time = guest.late_checkout_time if guest.late_checkout_time else datetime.time(11, 0)
                    end_date = timezone.make_aware(
                        datetime.datetime.combine(guest.check_out_date, check_out_time),
                        datetime.timezone.utc,
                    ).astimezone(uk_timezone) + datetime.timedelta(days=1)
                    end_time = int(end_date.timestamp() * 1000)
                    pin = str(random.randint(10000, 99999))  # 5-digit PIN

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
            check_out_datetime = timezone.make_aware(
                datetime.datetime.combine(guest.check_out_date, check_out_time),
                datetime.timezone.utc,
            ).astimezone(uk_timezone)

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

        # Step 4: If no guest is found or none of the conditions match, show error
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

def room_detail(request, room_token):
    reservation_number = request.session.get("reservation_number", None)
    guest = Guest.objects.filter(secure_token=room_token).first()

    if not guest or not reservation_number or guest.reservation_number != reservation_number:
        return redirect("unauthorized")

    room = guest.assigned_room
    uk_timezone = pytz.timezone("Europe/London")
    now_uk_time = timezone.now().astimezone(uk_timezone)

    check_in_time = guest.early_checkin_time if guest.early_checkin_time else datetime.time(14, 0)
    check_in_datetime = timezone.make_aware(
        datetime.datetime.combine(guest.check_in_date, check_in_time),
        timezone.get_current_timezone(),
    ).astimezone(uk_timezone)

    check_out_time = guest.late_checkout_time if guest.late_checkout_time else datetime.time(11, 0)
    check_out_datetime = timezone.make_aware(
        datetime.datetime.combine(guest.check_out_date, check_out_time),
        timezone.get_current_timezone(),
    ).astimezone(uk_timezone)

    if now_uk_time > check_out_datetime:
        request.session.pop("reservation_number", None)
        return redirect("rebook_guest")

    enforce_2pm_rule = now_uk_time < check_in_datetime

    if request.method == "GET" and request.GET.get('modal'):
        return render(request, "main/room_detail.html", {
            "room": room,
            "guest": guest,
            "image_url": room.image or None,
            "expiration_message": f"Your access will expire on {guest.check_out_date.strftime('%d %b %Y')} at {check_out_time.strftime('%I:%M %p')}.",
            "show_pin": not enforce_2pm_rule,
            "front_door_pin": guest.front_door_pin,
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
                # Initialize Cloudinary with environment variables
                cloudinary.config(
                    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
                    api_key=os.environ.get('CLOUDINARY_API_KEY'),
                    api_secret=os.environ.get('CLOUDINARY_API_SECRET')
                )
                logger.debug(f"Cloudinary config initialized: {cloudinary.config().cloud_name}")
                logger.debug(f"Default storage backend: {default_storage.__class__.__name__}")

                # Debug file content before upload
                logger.debug(f"File content sample before upload: {id_image.read(100)}")
                id_image.seek(0)  # Reset the file pointer after reading

                # Manual upload to Cloudinary
                upload_response = cloudinary_upload(
                    id_image,
                    folder=f"guest_ids/{now_uk_time.year}/{now_uk_time.month}/{now_uk_time.day}/",
                    resource_type="image"
                )
                logger.info(f"Manual upload response: {upload_response}")

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
            "front_door_pin": guest.front_door_pin,
            "id_uploads": guest.id_uploads.all(),
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
    now_time = localtime(now())  # Current time in server's local timezone (assumed Europe/London)
    uk_timezone = pytz.timezone("Europe/London")

    # Archive guests and delete their PINs when their check-out time has passed
    guests_to_archive = Guest.objects.filter(is_archived=False)
    front_door_lock = TTLock.objects.filter(is_front_door=True).first()
    ttlock_client = TTLockClient()

    for guest in guests_to_archive:
        # Determine the check-out datetime based on late_checkout_time or default to 11:00 AM
        check_out_time = guest.late_checkout_time if guest.late_checkout_time else time(11, 0)
        check_out_datetime = timezone.make_aware(
            datetime.datetime.combine(guest.check_out_date, check_out_time),
            datetime.timezone.utc
        ).astimezone(uk_timezone)

        if now_time > check_out_datetime:
            # Delete front door PIN
            if guest.front_door_pin_id and front_door_lock:
                try:
                    ttlock_client.delete_pin(
                        lock_id=front_door_lock.lock_id,
                        keyboard_pwd_id=guest.front_door_pin_id,
                    )
                except Exception as e:
                    logger.error(f"Failed to delete front door PIN for guest {guest.reservation_number}: {str(e)}")
                    messages.warning(request, f"Failed to delete front door PIN for {guest.full_name}: {str(e)}")

            # Delete room PIN
            room_lock = guest.assigned_room.ttlock
            if guest.room_pin_id and room_lock:
                try:
                    ttlock_client.delete_pin(
                        lock_id=room_lock.lock_id,
                        keyboard_pwd_id=guest.room_pin_id,
                    )
                except Exception as e:
                    logger.error(f"Failed to delete room PIN for guest {guest.reservation_number}: {str(e)}")
                    messages.warning(request, f"Failed to delete room PIN for {guest.full_name}: {str(e)}")

            # Update guest status and send post-stay message
            guest.front_door_pin = None
            guest.front_door_pin_id = None
            guest.room_pin_id = None
            guest.is_archived = True
            try:
                guest.save()
                # Log the archiving action
                AuditLog.objects.create(
                    user=request.user,
                    action="archive_guest",
                    object_type="Guest",
                    object_id=guest.id,
                    details=f"Archived guest {guest.full_name} (Reservation: {guest.reservation_number})"
                )
                # Send post-stay message if the guest has contact info
                if guest.phone_number or guest.email:
                    guest.send_post_stay_message()
                messages.success(request, f"Guest {guest.full_name} has been archived.")
            except Exception as e:
                logger.error(f"Failed to save archived guest {guest.reservation_number}: {str(e)}")
                messages.error(request, f"Failed to archive {guest.full_name}: {str(e)}")

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
        reservation_number = request.POST.get('reservation_number', '').strip()
        phone_number = request.POST.get('phone_number', '').strip() or None
        email = request.POST.get('email', '').strip() or None  # New email field from form
        full_name = request.POST.get('full_name', 'Guest').strip()
        room_id = request.POST.get('room')

        # Validate reservation_number length
        if len(reservation_number) > 15:
            messages.error(request, "Reservation number must not exceed 15 characters.")
            return redirect('admin_page')

        if not reservation_number:
            messages.error(request, "Reservation number is required.")
            return redirect('admin_page')

        # Normalize and validate phone number
        if phone_number:
            if not re.match(r'^\+?\d{9,15}$', phone_number):  # Allow 9-15 digits with optional +
                messages.error(request, "Phone number must be in international format (e.g., +12025550123) or a valid local number (e.g., 07123456789 for UK).")
                return redirect('admin_page')
            # Only normalize UK numbers starting with 0 to +44, leave other international numbers intact
            if phone_number.startswith('0') and len(phone_number) == 11 and phone_number[1] in '7':  # UK mobile numbers
                phone_number = '+44' + phone_number[1:]
            # Do not modify numbers with existing country codes

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

            pin = str(random.randint(10000, 99999))  # 5-digit PIN
            uk_timezone = pytz.timezone("Europe/London")
            now_uk_time = timezone.now().astimezone(uk_timezone)
            start_time = int(now_uk_time.timestamp() * 1000)
            # Set endDate to one day after check-out, considering late_checkout_time if provided
            check_out_time = time(11, 0)  # Default if not set
            if request.POST.get('late_checkout_time'):
                try:
                    check_out_time = datetime.datetime.strptime(request.POST.get('late_checkout_time'), '%H:%M').time()
                except ValueError:
                    messages.error(request, "Invalid late check-out time format. Use HH:MM (e.g., 12:00).")
                    return redirect('admin_page')
            end_date = timezone.make_aware(
                datetime.datetime.combine(check_out_date, check_out_time),
                datetime.timezone.utc
            ).astimezone(uk_timezone) + datetime.timedelta(days=1)
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
                    late_checkout_time=check_out_time if check_out_time != time(11, 0) else None,
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

    return render(request, 'main/admin_page.html', {
        'rooms': available_rooms,
        'guests': guests,
        'check_in_date': check_in_date,
        'check_out_date': check_out_date,
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

            new_pin = str(random.randint(10000, 99999))  # 5-digit PIN
            uk_timezone = pytz.timezone("Europe/London")
            now_uk_time = timezone.now().astimezone(uk_timezone)
            start_time = int(now_uk_time.timestamp() * 1000)
            # Set endDate to one day after check-out
            check_out_time = guest.late_checkout_time if guest.late_checkout_time else datetime.time(11, 0)
            end_date = timezone.make_aware(
                datetime.datetime.combine(guest.check_out_date, check_out_time),
                datetime.timezone.utc
            ).astimezone(uk_timezone) + datetime.timedelta(days=1)
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

                        new_pin = str(random.randint(10000, 99999))  # 5-digit PIN
                        uk_timezone = pytz.timezone("Europe/London")
                        now_uk_time = timezone.now().astimezone(uk_timezone)
                        start_time = int(now_uk_time.timestamp() * 1000)
                        check_out_time = guest.late_checkout_time if guest.late_checkout_time else datetime.time(11, 0)
                        end_date = timezone.make_aware(
                            datetime.datetime.combine(check_out_date, check_out_time),
                            datetime.timezone.utc,
                        ).astimezone(uk_timezone) + datetime.timedelta(days=1)
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
    past_guests = Guest.objects.filter(is_archived=True)

    if search_query:
        past_guests = past_guests.filter(
            Q(full_name__icontains=search_query) |
            Q(phone_number__icontains=search_query) |
            Q(reservation_number__icontains=search_query) |
            Q(assigned_room__name__icontains=search_query)
        )

    for guest in past_guests:
        guest.is_returning = Guest.objects.filter(
            Q(full_name__iexact=guest.full_name) & Q(is_archived=False)
        ).exists()

    past_guests = past_guests.order_by('-check_out_date')
    paginator = Paginator(past_guests, 50)
    page_number = request.GET.get('page')
    paginated_past_guests = paginator.get_page(page_number)

    return render(request, 'main/past_guests.html', {
        'past_guests': paginated_past_guests,
        'search_query': search_query,
    })

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.has_perm('main.change_guest'), login_url='/unauthorized/')
def manage_checkin_checkout(request, guest_id):
    guest = get_object_or_404(Guest, id=guest_id)

    if request.method == 'POST':
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

        if late_checkout_time:
            try:
                late_checkout_time = datetime.datetime.strptime(late_checkout_time, '%H:%M').time()
                guest.late_checkout_time = late_checkout_time
            except ValueError:
                messages.error(request, "Invalid late check-out time format. Use HH:MM (e.g., 12:00).")
                return redirect('manage_checkin_checkout', guest_id=guest.id)

        # Clear the times if the fields are empty (to revert to default)
        if not early_checkin_time:
            guest.early_checkin_time = None
        if not late_checkout_time:
            guest.late_checkout_time = None

        # Update PIN validity period if check-out time changes
        if late_checkout_time and (guest.front_door_pin_id or guest.room_pin_id):
            front_door_lock = TTLock.objects.filter(is_front_door=True).first()
            room_lock = guest.assigned_room.ttlock
            if front_door_lock and room_lock:
                ttlock_client = TTLockClient()
                try:
                    # Delete the old front door PIN
                    if guest.front_door_pin_id:
                        ttlock_client.delete_pin(
                            lock_id=front_door_lock.lock_id,
                            keyboard_pwd_id=guest.front_door_pin_id,
                        )
                        logger.info(f"Deleted old front door PIN for guest {guest.reservation_number} due to check-out time change (Keyboard Password ID: {guest.front_door_pin_id})")
                    
                    # Delete the old room PIN
                    if guest.room_pin_id:
                        ttlock_client.delete_pin(
                            lock_id=room_lock.lock_id,
                            keyboard_pwd_id=guest.room_pin_id,
                        )
                        logger.info(f"Deleted old room PIN for guest {guest.reservation_number} due to check-out time change (Keyboard Password ID: {guest.room_pin_id})")

                    # Generate a new PIN with updated validity
                    new_pin = guest.front_door_pin  # Reuse the existing PIN
                    uk_timezone = pytz.timezone("Europe/London")
                    now_uk_time = timezone.now().astimezone(uk_timezone)
                    start_time = int(now_uk_time.timestamp() * 1000)
                    # Set endDate to one day after check-out
                    end_date = timezone.make_aware(
                        datetime.datetime.combine(guest.check_out_date, late_checkout_time),
                        datetime.timezone.utc,
                    ).astimezone(uk_timezone) + datetime.timedelta(days=1)
                    end_time = int(end_date.timestamp() * 1000)

                    # Generate new PIN for front door
                    front_door_response = ttlock_client.generate_temporary_pin(
                        lock_id=front_door_lock.lock_id,
                        pin=new_pin,
                        start_time=start_time,
                        end_time=end_time,
                        name=f"Front Door - {guest.assigned_room.name} - {guest.full_name} - {new_pin}",
                    )
                    if "keyboardPwdId" not in front_door_response:
                        logger.error(f"Failed to update front door PIN for guest {guest.reservation_number} after check-out time change: {front_door_response.get('errmsg', 'Unknown error')}")
                        messages.warning(request, f"Failed to update front door PIN after check-out time change: {front_door_response.get('errmsg', 'Unknown error')}")
                        guest.front_door_pin = None
                        guest.front_door_pin_id = None
                        guest.room_pin_id = None
                    else:
                        guest.front_door_pin_id = front_door_response["keyboardPwdId"]
                        logger.info(f"Updated front door PIN {new_pin} for guest {guest.reservation_number} after check-out time change (Keyboard Password ID: {front_door_response['keyboardPwdId']})")

                        # Generate the same PIN for the room lock
                        room_response = ttlock_client.generate_temporary_pin(
                            lock_id=room_lock.lock_id,
                            pin=new_pin,
                            start_time=start_time,
                            end_time=end_time,
                            name=f"Room - {guest.assigned_room.name} - {guest.full_name} - {new_pin}",
                        )
                        if "keyboardPwdId" not in room_response:
                            logger.error(f"Failed to update room PIN for guest {guest.reservation_number} after check-out time change: {room_response.get('errmsg', 'Unknown error')}")
                            # Roll back the front door PIN
                            try:
                                ttlock_client.delete_pin(
                                    lock_id=front_door_lock.lock_id,
                                    keyboard_pwd_id=guest.front_door_pin_id,
                                )
                                logger.info(f"Rolled back updated front door PIN for guest {guest.reservation_number} after check-out time change")
                            except Exception as e:
                                logger.error(f"Failed to roll back updated front door PIN for guest {guest.reservation_number}: {str(e)}")
                            guest.front_door_pin = None
                            guest.front_door_pin_id = None
                            guest.room_pin_id = None
                            messages.warning(request, f"Failed to update room PIN after check-out time change: {room_response.get('errmsg', 'Unknown error')}")
                        else:
                            guest.room_pin_id = room_response["keyboardPwdId"]
                            logger.info(f"Updated room PIN {new_pin} for guest {guest.reservation_number} after check-out time change (Keyboard Password ID: {room_response['keyboardPwdId']})")
                except Exception as e:
                    logger.error(f"Failed to update PIN for guest {guest.reservation_number} after check-out time change: {str(e)}")
                    messages.warning(request, f"Failed to update PIN after check-out time change: {str(e)}")
                    guest.front_door_pin = None
                    guest.front_door_pin_id = None
                    guest.room_pin_id = None

        guest.save()
        messages.success(request, f"Check-in/check-out times updated for {guest.full_name}.")
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
        logger.info(f"Audit logs filtered by search: {search_query}")

    # Handle date range filter
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if start_date:
        logs = logs.filter(timestamp__gte=start_date)
    if end_date:
        logs = logs.filter(timestamp__lte=end_date + ' 23:59:59')
    if start_date or end_date:
        logger.info(f"Audit logs filtered by date range: {start_date} to {end_date}")

    # Handle sorting
    sort_by = request.GET.get('sort', '-timestamp')  # Default to descending timestamp
    if sort_by not in ['timestamp', '-timestamp', 'user', '-user', 'action', '-action', 'object_type', '-object_type', 'object_id', '-object_id']:
        sort_by = '-timestamp'  # Fallback to default if invalid
    logs = logs.order_by(sort_by)
    logger.info(f"Audit logs sorted by: {sort_by}")

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
        logger.info(f"Review message blocked for guest {guest.full_name} (ID: {guest.id}) by user {request.user.username}")
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

    # Log the API request for debugging
    request_url = 'https://app.ticketmaster.com/discovery/v2/events.json' + '?' + '&'.join(f"{k}={v}" for k, v in params.items())
    logger.info(f"Ticketmaster API request URL: {request_url}")

    # Call the Ticketmaster API
    try:
        response = requests.get('https://app.ticketmaster.com/discovery/v2/events.json', params=params)
        response.raise_for_status()  # Raise an error for bad status codes
        data = response.json()
        logger.info(f"Ticketmaster API response: {json.dumps(data, indent=2)}")  # Log the full response
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