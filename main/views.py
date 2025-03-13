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
from datetime import date, datetime, time
from django.core.mail import send_mail
from django.http import Http404, JsonResponse
from django.db import IntegrityError
from django.db.models import Q
from django_ratelimit.decorators import ratelimit
from django.core.paginator import Paginator
from django.conf import settings
from django.contrib import messages
import pandas as pd
import random
from django.utils.translation import gettext as _
from django.utils.safestring import mark_safe
from langdetect import detect
import uuid
import pytz
import datetime
from .models import Guest, Room, ReviewCSVUpload, TTLock
from .ttlock_utils import TTLockClient
import logging
from django.views.decorators.csrf import csrf_exempt
import json
from django.contrib.auth.models import User, Group, Permission
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

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

@ratelimit(key='ip', rate='10/m', method='POST', block=True)
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

    # Redirect to unauthorized if guest doesn't exist or reservation_number doesn't match
    if not guest or not reservation_number or guest.reservation_number != reservation_number:
        return redirect("unauthorized")

    room = guest.assigned_room
    uk_timezone = pytz.timezone("Europe/London")
    now_uk_time = timezone.now().astimezone(uk_timezone)

    # Use early check-in time if set, otherwise default to 2:00 PM
    check_in_time = guest.early_checkin_time if guest.early_checkin_time else time(14, 0)
    check_in_datetime = timezone.make_aware(
        datetime.datetime.combine(guest.check_in_date, check_in_time),
        timezone.get_current_timezone(),
    ).astimezone(uk_timezone)

    # Use late check-out time if set, otherwise default to 11:00 AM
    check_out_time = guest.late_checkout_time if guest.late_checkout_time else time(11, 0)
    check_out_datetime = timezone.make_aware(
        datetime.datetime.combine(guest.check_out_date, check_out_time),
        timezone.get_current_timezone(),
    ).astimezone(uk_timezone)

    if now_uk_time > check_out_datetime:
        request.session.pop("reservation_number", None)
        return redirect("rebook_guest")

    enforce_2pm_rule = now_uk_time < check_in_datetime

    # Handle modal refresh request
    if request.method == "GET" and request.GET.get('modal'):
        return render(request, "main/room_detail.html", {
            "room": room,
            "guest": guest,
            "image_url": room.image or None,
            "expiration_message": f"Your access will expire on {guest.check_out_date.strftime('%d %b %Y')} at {check_out_time.strftime('%I:%M %p')}.",
            "show_pin": not enforce_2pm_rule,
            "front_door_pin": guest.front_door_pin,
        }, content_type="text/html", status=200)

    # Handle unlock request if submitted
    if request.method == "POST" and "unlock_door" in request.POST:
        try:
            front_door_lock = TTLock.objects.get(is_front_door=True)
            room_lock = guest.assigned_room.ttlock
            client = TTLockClient()
            max_retries = 3
            door_type = request.POST.get("door_type")  # New field to determine which door to unlock

            # Unlock the specified door
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
                            return JsonResponse({"error": "Failed to unlock the front door. Please try again or contact report."}, status=400)
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
        },
    )

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

        logger.info(f"Sent contact email from {email}")
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
            datetime.datetime.combine(guest.check_out_date, check_out_time),  # Fixed: Use datetime.datetime.combine
            datetime.timezone.utc
        ).astimezone(uk_timezone)

        logger.info(f"Checking archive for guest {guest.reservation_number}: Current time {now_time}, Check-out time {check_out_datetime}")

        if now_time > check_out_datetime:
            logger.info(f"Archiving guest {guest.reservation_number} as check-out time {check_out_datetime} has passed")
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
                    messages.warning(request, f"Failed to delete front door PIN for {guest.full_name}: {str(e)}")

            # Delete room PIN
            room_lock = guest.assigned_room.ttlock
            if guest.room_pin_id and room_lock:
                try:
                    ttlock_client.delete_pin(
                        lock_id=room_lock.lock_id,
                        keyboard_pwd_id=guest.room_pin_id,
                    )
                    logger.info(f"Deleted room PIN for guest {guest.reservation_number} (Keyboard Password ID: {guest.room_pin_id})")
                except Exception as e:
                    logger.error(f"Failed to delete room PIN for guest {guest.reservation_number}: {str(e)}")
                    messages.warning(request, f"Failed to delete room PIN for {guest.full_name}: {str(e)}")

            # Update guest status
            guest.front_door_pin = None
            guest.front_door_pin_id = None
            guest.room_pin_id = None
            guest.is_archived = True
            try:
                guest.save()
                logger.info(f"Successfully archived guest {guest.reservation_number}")
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
        full_name = request.POST.get('full_name', 'Guest').strip()
        room_id = request.POST.get('room')

        # Validate reservation_number length
        if len(reservation_number) > 15:
            messages.error(request, "Reservation number must not exceed 15 characters.")
            return redirect('admin_page')

        if not reservation_number:
            messages.error(request, "Reservation number is required.")
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
                logger.info(f"Generated front door PIN {pin} for guest {reservation_number} (Keyboard Password ID: {keyboard_pwd_id_front})")

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
                        logger.info(f"Rolled back front door PIN for guest {reservation_number}")
                    except Exception as e:
                        logger.error(f"Failed to roll back front door PIN for guest {reservation_number}: {str(e)}")
                    messages.error(request, f"Failed to generate room PIN: {room_response.get('errmsg', 'Unknown error')}")
                    return redirect('admin_page')
                keyboard_pwd_id_room = room_response["keyboardPwdId"]
                logger.info(f"Generated room PIN {pin} for guest {reservation_number} (Keyboard Password ID: {keyboard_pwd_id_room})")

                # Create the guest with the generated PIN
                guest = Guest.objects.create(
                    full_name=full_name,
                    reservation_number=reservation_number,
                    phone_number=phone_number,
                    check_in_date=check_in_date,
                    check_out_date=check_out_date,
                    assigned_room=room,
                    is_returning=previous_stays,
                    front_door_pin=pin,
                    front_door_pin_id=keyboard_pwd_id_front,
                    room_pin_id=keyboard_pwd_id_room,
                    late_checkout_time=check_out_time if check_out_time != time(11, 0) else None,  # Only save if different from default
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
    original_room_id = guest.assigned_room.id  # Store original room ID for comparison

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
                    logger.info(f"Deleted old front door PIN for guest {guest.reservation_number} (Keyboard Password ID: {guest.front_door_pin_id})")
                except Exception as e:
                    logger.warning(f"Failed to delete old front door PIN for guest {guest.reservation_number}: {str(e)}")
                    messages.warning(request, f"Failed to delete old front door PIN: {str(e)}")

            # Delete existing room PIN
            if guest.room_pin_id:
                try:
                    ttlock_client.delete_pin(
                        lock_id=room_lock.lock_id,
                        keyboard_pwd_id=guest.room_pin_id,
                    )
                    logger.info(f"Deleted old room PIN for guest {guest.reservation_number} (Keyboard Password ID: {guest.room_pin_id})")
                except Exception as e:
                    logger.warning(f"Failed to delete old room PIN for guest {guest.reservation_number}: {str(e)}")
                    messages.warning(request, f"Failed to delete old room PIN: {str(e)}")

            new_pin = str(random.randint(10000, 99999))  # 5-digit PIN
            uk_timezone = pytz.timezone("Europe/London")
            now_uk_time = timezone.now().astimezone(uk_timezone)
            start_time = int(now_uk_time.timestamp() * 1000)
            # Set endDate to one day after check-out
            check_out_time = guest.late_checkout_time if guest.late_checkout_time else datetime.time(11, 0)
            end_date = timezone.make_aware(
                datetime.datetime.combine(guest.check_out_date, check_out_time),
                datetime.timezone.utc,
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
                logger.info(f"Generated new front door PIN {new_pin} for guest {guest.reservation_number} (Keyboard Password ID: {front_door_response['keyboardPwdId']})")

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
                        logger.info(f"Rolled back new front door PIN for guest {guest.reservation_number}")
                    except Exception as e:
                        logger.error(f"Failed to roll back new front door PIN for guest {guest.reservation_number}: {str(e)}")
                    guest.front_door_pin = None
                    guest.front_door_pin_id = None
                    guest.room_pin_id = None
                    guest.save()
                    messages.error(request, f"Failed to generate new room PIN: {room_response.get('errmsg', 'Unknown error')}")
                    return redirect('edit_guest', guest_id=guest.id)
                guest.room_pin_id = room_response["keyboardPwdId"]
                logger.info(f"Generated new room PIN {new_pin} for guest {guest.reservation_number} (Keyboard Password ID: {room_response['keyboardPwdId']})")
                guest.save()
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

            guest.full_name = request.POST.get('full_name')
            guest.reservation_number = new_reservation_number
            guest.phone_number = request.POST.get('phone_number')
            check_in_date = date.fromisoformat(request.POST.get('check_in_date'))
            check_out_date = date.fromisoformat(request.POST.get('check_out_date'))
            new_room_id = request.POST.get('room')
            early_checkin_time = request.POST.get('early_checkin_time')
            late_checkout_time = request.POST.get('late_checkout_time')

            # Update early_checkin_time if provided
            if early_checkin_time:
                try:
                    guest.early_checkin_time = datetime.datetime.strptime(early_checkin_time, '%H:%M').time()
                except ValueError:
                    messages.error(request, "Invalid early check-in time format. Use HH:MM (e.g., 12:00).")
                    return redirect('edit_guest', guest_id=guest.id)
            else:
                guest.early_checkin_time = None  # Revert to default if empty

            # Update late_checkout_time if provided
            if late_checkout_time:
                try:
                    guest.late_checkout_time = datetime.datetime.strptime(late_checkout_time, '%H:M').time()
                except ValueError:
                    messages.error(request, "Invalid late check-out time format. Use HH:MM (e.g., 12:00).")
                    return redirect('edit_guest', guest_id=guest.id)
            else:
                guest.late_checkout_time = None  # Revert to default if empty

            # Check for room change
            if str(new_room_id) != str(original_room_id):
                logger.info(f"Room changed for guest {guest.reservation_number} from {original_room_id} to {new_room_id}")
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
                        logger.info(f"Deleted old room PIN for guest {guest.reservation_number} from room {original_room_id} (Keyboard Password ID: {guest.room_pin_id})")
                    except Exception as e:
                        logger.warning(f"Failed to delete old room PIN for guest {guest.reservation_number}: {str(e)}")
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
                            logger.info(f"Deleted old front door PIN for guest {guest.reservation_number} due to room change (Keyboard Password ID: {guest.front_door_pin_id})")

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
                        logger.info(f"Generated new front door PIN {new_pin} for guest {guest.reservation_number} after room change (Keyboard Password ID: {front_door_response['keyboardPwdId']})")

                        # Generate the same PIN for the new room lock
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
                                logger.info(f"Rolled back new front door PIN for guest {guest.reservation_number} after room change")
                            except Exception as e:
                                logger.error(f"Failed to roll back new front door PIN for guest {guest.reservation_number}: {str(e)}")
                            guest.front_door_pin = None
                            guest.front_door_pin_id = None
                            guest.room_pin_id = None
                            guest.save()
                            messages.error(request, f"Failed to generate new room PIN: {room_response.get('errmsg', 'Unknown error')}")
                            return redirect('edit_guest', guest_id=guest.id)
                        guest.room_pin_id = room_response["keyboardPwdId"]
                        logger.info(f"Generated new room PIN {new_pin} for guest {guest.reservation_number} after room change (Keyboard Password ID: {room_response['keyboardPwdId']})")
                    except Exception as e:
                        logger.error(f"Failed to generate new PIN for guest {guest.reservation_number} after room change: {str(e)}")
                        messages.error(request, f"Failed to generate new PIN after room change: {str(e)}")
                        return redirect('edit_guest', guest_id=guest.id)

            # Update dates and room
            guest.check_in_date = check_in_date
            guest.check_out_date = check_out_date
            guest.assigned_room_id = new_room_id

            # Handle date changes (similar to previous logic)
            if (guest.check_in_date != check_in_date or guest.check_out_date != check_out_date):
                if guest.front_door_pin_id or guest.room_pin_id:
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
                                logger.info(f"Deleted old front door PIN for guest {guest.reservation_number} due to date change (Keyboard Password ID: {guest.front_door_pin_id})")
                            
                            # Delete the old room PIN
                            if guest.room_pin_id:
                                ttlock_client.delete_pin(
                                    lock_id=room_lock.lock_id,
                                    keyboard_pwd_id=guest.room_pin_id,
                                )
                                logger.info(f"Deleted old room PIN for guest {guest.reservation_number} due to date change (Keyboard Password ID: {guest.room_pin_id})")

                            # Generate a new PIN with updated validity
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
                                name=f"Front Door - {guest.assigned_room.name} - {guest.full_name} - {new_pin}",
                            )
                            if "keyboardPwdId" not in front_door_response:
                                logger.error(f"Failed to generate new front door PIN for guest {guest.reservation_number} after date change: {front_door_response.get('errmsg', 'Unknown error')}")
                                messages.warning(request, f"Failed to update front door PIN after date change: {front_door_response.get('errmsg', 'Unknown error')}")
                                guest.front_door_pin = None
                                guest.front_door_pin_id = None
                                guest.room_pin_id = None
                                guest.save()
                            else:
                                guest.front_door_pin = new_pin
                                guest.front_door_pin_id = front_door_response["keyboardPwdId"]
                                logger.info(f"Generated new front door PIN {new_pin} for guest {guest.reservation_number} after date change (Keyboard Password ID: {front_door_response['keyboardPwdId']})")

                                # Generate the same PIN for the room lock
                                room_response = ttlock_client.generate_temporary_pin(
                                    lock_id=room_lock.lock_id,
                                    pin=new_pin,
                                    start_time=start_time,
                                    end_time=end_time,
                                    name=f"Room - {guest.assigned_room.name} - {guest.full_name} - {new_pin}",
                                )
                                if "keyboardPwdId" not in room_response:
                                    logger.error(f"Failed to generate new room PIN for guest {guest.reservation_number} after date change: {room_response.get('errmsg', 'Unknown error')}")
                                    # Roll back the front door PIN
                                    try:
                                        ttlock_client.delete_pin(
                                            lock_id=front_door_lock.lock_id,
                                            keyboard_pwd_id=guest.front_door_pin_id,
                                        )
                                        logger.info(f"Rolled back new front door PIN for guest {guest.reservation_number} after date change")
                                    except Exception as e:
                                        logger.error(f"Failed to roll back new front door PIN for guest {guest.reservation_number}: {str(e)}")
                                    guest.front_door_pin = None
                                    guest.front_door_pin_id = None
                                    guest.room_pin_id = None
                                    guest.save()
                                    messages.warning(request, f"Failed to update room PIN after date change: {room_response.get('errmsg', 'Unknown error')}")
                                else:
                                    guest.room_pin_id = room_response["keyboardPwdId"]
                                    logger.info(f"Generated new room PIN {new_pin} for guest {guest.reservation_number} after date change (Keyboard Password ID: {room_response['keyboardPwdId']})")
                                    messages.info(request, f"PIN updated due to date change: {new_pin}. The guest can also unlock the doors remotely during check-in or from the room detail page.")
                        except Exception as e:
                            logger.error(f"Failed to update PIN for guest {guest.reservation_number} after date change: {str(e)}")
                            messages.warning(request, f"Failed to update PIN after date change: {str(e)}")
                            guest.front_door_pin = None
                            guest.front_door_pin_id = None
                            guest.room_pin_id = None
                            guest.save()

            guest.save()
            logger.info(f"Updated guest {guest.reservation_number} details")
            messages.success(request, f"Guest {guest.full_name} updated successfully. The guest can unlock the doors using their PIN or remotely during check-in or from the room detail page.")

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
    logger.info(f"Deleted guest {guest.reservation_number}")
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
        try:
            lock_id = request.POST.get("lock_id")
            door_type = request.POST.get("door_type")

            client = TTLockClient()
            max_retries = 3

            if door_type in ["front", "room"] and "guest_id" in request.POST:
                # Handle guest-specific unlock
                guest_id = request.POST.get("guest_id")
                guest = get_object_or_404(Guest, id=guest_id, is_archived=False)
                lock = TTLock.objects.get(lock_id=lock_id) if door_type == "front" else guest.assigned_room.ttlock
                if not lock:
                    raise TTLock.DoesNotExist("Lock not found for the specified door.")
            elif door_type in ["manual_front", "manual_room"]:
                # Handle manual unlock
                lock = get_object_or_404(TTLock, lock_id=lock_id)
            else:
                logger.warning(f"Invalid door_type: {door_type}")
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
                            logger.info(f"Retrying unlock {door_type} (Lock ID: {lock.lock_id}) (attempt {attempt + 1}/{max_retries})")
                            continue
                    else:
                        logger.info(f"Successfully unlocked {door_type} (Lock ID: {lock.lock_id})")
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
                        logger.info(f"Retrying unlock {door_type} (Lock ID: {lock.lock_id}) (attempt {attempt + 1}/{max_retries})")
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
                logger.info(f"Admin {request.user.username} populated TTLock entries from JSON textarea")
            except json.JSONDecodeError:
                messages.error(request, "Invalid JSON format. Please check your syntax.")
            except Room.DoesNotExist:
                messages.error(request, "One or more rooms in the JSON data do not exist.")
            except Exception as e:
                logger.error(f"Failed to populate locks: {str(e)}")
                messages.error(request, f"Failed to populate locks: {str(e)}")

        elif action == "add_room":
            name = request.POST.get("name").strip()
            video_url = request.POST.get("video_url").strip()
            description = request.POST.get("description").strip() or None
            image_url = request.POST.get("image").strip() or None
            new_lock_name = request.POST.get("new_lock_name").strip()
            new_lock_id = request.POST.get("new_lock_id")

            if not name or not video_url or not new_lock_name or not new_lock_id:
                messages.error(request, "Room name, video URL, new lock name, and new lock ID are required.")
                return redirect('room_management')

            try:
                # Validate and create new TTLock
                if not new_lock_id.isdigit():
                    messages.error(request, "Lock ID must be a valid number.")
                    return redirect('room_management')
                new_lock_id = int(new_lock_id)
                if TTLock.objects.filter(lock_id=new_lock_id).exists():
                    messages.error(request, "This lock ID is already in use.")
                    return redirect('room_management')

                new_ttlock = TTLock.objects.create(
                    name=new_lock_name,
                    lock_id=new_lock_id,
                    is_front_door=False
                )
                room = Room.objects.create(
                    name=name,
                    video_url=video_url,
                    description=description,
                    image=image_url,
                    ttlock=new_ttlock,
                )
                messages.success(request, f"Room '{room.name}' and new lock '{new_lock_name}' added successfully.")
                logger.info(f"Admin {request.user.username} added room '{room.name}' with new lock '{new_lock_name}' (Lock ID: {new_lock_id})")
            except ValueError:
                messages.error(request, "Invalid lock ID format.")
            except Exception as e:
                logger.error(f"Failed to add room and lock: {str(e)}")
                messages.error(request, f"Failed to add room and lock: {str(e)}")

        elif action == "edit_room":
            room_id = request.POST.get("room_id")
            room = get_object_or_404(Room, id=room_id)
            name = request.POST.get("name").strip()
            video_url = request.POST.get("video_url").strip()
            description = request.POST.get("description").strip() or None
            image_url = request.POST.get("image").strip() or None
            ttlock_id = request.POST.get("ttlock")
            lock_option = request.POST.get("lock_option_" + room_id)
            new_lock_name = request.POST.get("new_lock_name")
            new_lock_id = request.POST.get("new_lock_id")

            if not name or not video_url:
                messages.error(request, "Room name and video URL are required.")
                return redirect('room_management')

            try:
                if lock_option == "new" and new_lock_name and new_lock_id:
                    if not new_lock_id.isdigit():
                        messages.error(request, "Lock ID must be a valid number.")
                        return redirect('room_management')
                    new_lock_id = int(new_lock_id)
                    if TTLock.objects.filter(lock_id=new_lock_id).exists():
                        messages.error(request, "This lock ID is already in use.")
                        return redirect('room_management')

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
                        room.ttlock = new_ttlock
                elif lock_option == "existing" and ttlock_id:
                    ttlock = TTLock.objects.get(id=ttlock_id) if ttlock_id else None
                    room.ttlock = ttlock

                room.name = name
                room.video_url = video_url
                room.description = description
                room.image = image_url
                room.save()
                messages.success(request, f"Room '{room.name}' updated successfully.")
                logger.info(f"Admin {request.user.username} updated room '{room.name}'")
            except TTLock.DoesNotExist:
                messages.error(request, "Invalid TTLock selected.")
            except Exception as e:
                logger.error(f"Failed to update room {room_id}: {str(e)}")
                messages.error(request, f"Failed to update room: {str(e)}")

        elif action == "delete_room":
            room_id = request.POST.get("room_id")
            room = get_object_or_404(Room, id=room_id)
            room_name = room.name
            try:
                room.delete()
                messages.success(request, f"Room '{room_name}' deleted successfully.")
                logger.info(f"Admin {request.user.username} deleted room '{room_name}'")
            except Exception as e:
                logger.error(f"Failed to delete room {room_id}: {str(e)}")
                messages.error(request, f"Failed to delete room: {str(e)}")

        return redirect('room_management')

    return render(request, "main/room_management.html", {
        "rooms": rooms,
        "ttlocks": ttlocks,
    })