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

# main/views.py
# ... (other imports remain unchanged)

@ratelimit(key='ip', rate='10/m', method='POST', block=True)
def checkin(request):
    if request.method == "POST":
        reservation_number = request.POST.get('reservation_number', '').strip()

        # Find guest using only the unique Booking.com reservation number
        guest = Guest.objects.filter(reservation_number=reservation_number, is_archived=False).order_by('-check_in_date').first()

        if guest:
            # 🔒 Securely store reservation number in session
            request.session['reservation_number'] = guest.reservation_number

            # Generate a PIN if the guest doesn't have one
            if not guest.front_door_pin:
                try:
                    front_door_lock = TTLock.objects.get(is_front_door=True)
                    client = TTLockClient()
                    uk_timezone = pytz.timezone("Europe/London")
                    now_uk_time = timezone.now().astimezone(uk_timezone)
                    start_time = int(now_uk_time.timestamp() * 1000)
                    # Set endDate to one week from now to ensure the passcode is active
                    end_date = now_uk_time + datetime.timedelta(days=7)
                    end_time = int(end_date.timestamp() * 1000)
                    pin = str(random.randint(1000, 9999))  # 4-digit PIN

                    response = client.generate_temporary_pin(
                        lock_id=str(front_door_lock.lock_id),
                        pin=pin,
                        start_time=start_time,
                        end_time=end_time,
                        name=f"{guest.assigned_room.name} - {guest.full_name} - {pin}",  # Include PIN in name
                    )
                    if "keyboardPwdId" not in response:
                        logger.error(f"Failed to generate PIN for guest {guest.reservation_number}: {response.get('errmsg', 'Unknown error')}")
                        messages.error(request, f"Failed to generate PIN: {response.get('errmsg', 'Unknown error')}")
                        return redirect("checkin")
                    guest.front_door_pin = pin
                    guest.front_door_pin_id = response["keyboardPwdId"]
                    logger.info(f"Generated PIN {pin} for guest {guest.reservation_number} (Keyboard Password ID: {response['keyboardPwdId']})")
                    guest.save()

                    # Unlock the door remotely to ensure immediate access
                    try:
                        unlock_response = client.unlock_lock(lock_id=str(front_door_lock.lock_id))
                        if "errcode" in unlock_response and unlock_response["errcode"] != 0:
                            logger.error(f"Failed to unlock door for guest {guest.reservation_number}: {unlock_response.get('errmsg', 'Unknown error')}")
                            messages.warning(request, f"Generated PIN {pin}, but failed to unlock the door remotely: {unlock_response.get('errmsg', 'Unknown error')}")
                        else:
                            logger.info(f"Successfully unlocked door for guest {guest.reservation_number}")
                            messages.info(request, "The door has been unlocked for you. You can also use your PIN or the unlock button on the next page.")
                    except Exception as e:
                        logger.error(f"Failed to unlock door for guest {guest.reservation_number}: {str(e)}")
                        messages.warning(request, f"Generated PIN {pin}, but failed to unlock the door remotely: {str(e)}")

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

            messages.success(request, f"Watch the video instruction")
            return redirect('room_detail', room_token=guest.secure_token)

        # If the reservation number is incorrect, keep it prefilled in the form
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
    guest = Guest.objects.filter(secure_token=room_token).first()  # Use filter().first() instead of get_object_or_404

    # Redirect to unauthorized if guest doesn't exist or reservation_number doesn't match
    if not guest or not reservation_number or guest.reservation_number != reservation_number:
        return redirect("unauthorized")

    room = guest.assigned_room
    uk_timezone = pytz.timezone("Europe/London")
    now_uk_time = timezone.now().astimezone(uk_timezone)

    # Use early check-in time if set, otherwise default to 2:00 PM
    check_in_time = guest.early_checkin_time if guest.early_checkin_time else datetime.time(14, 0)
    check_in_datetime = timezone.make_aware(
        datetime.datetime.combine(guest.check_in_date, check_in_time),
        datetime.timezone.utc,
    ).astimezone(uk_timezone)

    # Use late check-out time if set, otherwise default to 11:00 AM
    check_out_time = guest.late_checkout_time if guest.late_checkout_time else datetime.time(11, 0)
    check_out_datetime = timezone.make_aware(
        datetime.datetime.combine(guest.check_out_date, check_out_time),
        datetime.timezone.utc,
    ).astimezone(uk_timezone)

    if now_uk_time > check_out_datetime:
        request.session.pop("reservation_number", None)
        return redirect("rebook_guest")

    enforce_2pm_rule = now_uk_time < check_in_datetime

    # Handle unlock request if submitted
    if request.method == "POST" and "unlock_door" in request.POST:
        try:
            front_door_lock = TTLock.objects.get(is_front_door=True)
            client = TTLockClient()
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    unlock_response = client.unlock_lock(lock_id=str(front_door_lock.lock_id))
                    if "errcode" in unlock_response and unlock_response["errcode"] != 0:
                        logger.error(f"Failed to unlock door for guest {guest.reservation_number}: {unlock_response.get('errmsg', 'Unknown error')}")
                        if attempt == max_retries - 1:
                            messages.error(request, "Failed to unlock the door. Please try again or contact support.")
                        else:
                            logger.info(f"Retrying unlock for guest {guest.reservation_number} (attempt {attempt + 1}/{max_retries})")
                            continue
                    else:
                        logger.info(f"Successfully unlocked door for guest {guest.reservation_number}")
                        messages.success(request, "The door has been unlocked for you.")
                        break
                except Exception as e:
                    logger.error(f"Failed to unlock door for guest {guest.reservation_number}: {str(e)}")
                    if attempt == max_retries - 1:
                        messages.error(request, "Failed to unlock the door. Please try again or contact support.")
                    else:
                        logger.info(f"Retrying unlock for guest {guest.reservation_number} (attempt {attempt + 1}/{max_retries})")
                        continue
        except TTLock.DoesNotExist:
            logger.error("Front door lock not configured in the database.")
            messages.error(request, "Front door lock not configured. Please contact support.")

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


@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def admin_page(request):
    """Admin Dashboard to manage guests, rooms, and assignments."""
    now_time = localtime(now())
    today = now_time.date()
    current_time = now_time.time()
    archive_time = time(11, 0)

    # Archive guests and delete their PINs after check-out
    if current_time >= archive_time:
        guests_to_archive = Guest.objects.filter(
            Q(check_out_date__lt=today) | 
            (Q(check_out_date=today) & Q(is_archived=False))
        )
        front_door_lock = TTLock.objects.filter(is_front_door=True).first()
        ttlock_client = TTLockClient()

        for guest in guests_to_archive:
            if guest.front_door_pin_id and front_door_lock:
                try:
                    ttlock_client.delete_pin(
                        lock_id=front_door_lock.lock_id,
                        keyboard_pwd_id=guest.front_door_pin_id,
                    )
                    logger.info(f"Deleted PIN for guest {guest.reservation_number} (Keyboard Password ID: {guest.front_door_pin_id})")
                except Exception as e:
                    logger.error(f"Failed to delete PIN for guest {guest.reservation_number}: {str(e)}")
                    messages.warning(request, f"Failed to delete PIN for {guest.full_name}: {str(e)}")
                finally:
                    guest.front_door_pin = None
                    guest.front_door_pin_id = None
                    guest.save()
            guest.is_archived = True
            guest.save()

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
            if not front_door_lock:
                logger.error("Front door lock not configured in the database.")
                messages.error(request, "Front door lock not configured. Please contact support.")
                return redirect('admin_page')

            front_door_pin = str(random.randint(1000, 9999))  # 4-digit PIN
            uk_timezone = pytz.timezone("Europe/London")
            now_uk_time = timezone.now().astimezone(uk_timezone)
            start_time = int(now_uk_time.timestamp() * 1000)
            # Set endDate to one week from now to ensure the passcode is active
            end_date = now_uk_time + datetime.timedelta(days=7)
            end_time = int(end_date.timestamp() * 1000)

            ttlock_client = TTLockClient()
            try:
                response = ttlock_client.generate_temporary_pin(
                    lock_id=front_door_lock.lock_id,
                    pin=front_door_pin,
                    start_time=start_time,
                    end_time=end_time,
                    name=f"{room.name} - {full_name} - {front_door_pin}",  # Include PIN in name
                )
                if "keyboardPwdId" not in response:
                    logger.error(f"Failed to generate PIN for guest {reservation_number}: {response.get('errmsg', 'Unknown error')}")
                    messages.error(request, f"Failed to generate PIN: {response.get('errmsg', 'Unknown error')}")
                    return redirect('admin_page')
                keyboard_pwd_id = response["keyboardPwdId"]
                logger.info(f"Generated PIN {front_door_pin} for guest {reservation_number} (Keyboard Password ID: {keyboard_pwd_id})")
            except Exception as e:
                logger.error(f"Failed to generate PIN for guest {reservation_number}: {str(e)}")
                messages.error(request, f"Failed to generate PIN: {str(e)}")
                return redirect('admin_page')

            # Create the guest with the generated PIN
            guest = Guest.objects.create(
                full_name=full_name,
                reservation_number=reservation_number,
                phone_number=phone_number,
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                assigned_room=room,
                is_returning=previous_stays,
                front_door_pin=front_door_pin,
                front_door_pin_id=keyboard_pwd_id,
            )
            messages.success(request, f"Guest {guest.full_name} added successfully! Front door PIN: {front_door_pin}. They can also unlock the door remotely during check-in or from the room detail page.")

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
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def edit_guest(request, guest_id):
    guest = get_object_or_404(Guest, id=guest_id)

    if request.method == 'POST':
        if 'regenerate_pin' in request.POST:
            front_door_lock = TTLock.objects.filter(is_front_door=True).first()
            if not front_door_lock:
                logger.error("Front door lock not configured in the database.")
                messages.error(request, "Front door lock not configured.")
                return redirect('edit_guest', guest_id=guest.id)

            ttlock_client = TTLockClient()
            if guest.front_door_pin_id:
                try:
                    ttlock_client.delete_pin(
                        lock_id=front_door_lock.lock_id,
                        keyboard_pwd_id=guest.front_door_pin_id,
                    )
                    logger.info(f"Deleted old PIN for guest {guest.reservation_number} (Keyboard Password ID: {guest.front_door_pin_id})")
                except Exception as e:
                    logger.warning(f"Failed to delete old PIN for guest {guest.reservation_number}: {str(e)}")
                    messages.warning(request, f"Failed to delete old PIN: {str(e)}")

            new_pin = str(random.randint(1000, 9999))  # 4-digit PIN
            uk_timezone = pytz.timezone("Europe/London")
            now_uk_time = timezone.now().astimezone(uk_timezone)
            start_time = int(now_uk_time.timestamp() * 1000)
            # Set endDate to one week from now to ensure the passcode is active
            end_date = now_uk_time + datetime.timedelta(days=7)
            end_time = int(end_date.timestamp() * 1000)

            try:
                response = ttlock_client.generate_temporary_pin(
                    lock_id=front_door_lock.lock_id,
                    pin=new_pin,
                    start_time=start_time,
                    end_time=end_time,
                    name=f"{guest.assigned_room.name} - {guest.full_name} - {new_pin}",  # Include PIN in name
                )
                if "keyboardPwdId" not in response:
                    logger.error(f"Failed to generate new PIN for guest {guest.reservation_number}: {response.get('errmsg', 'Unknown error')}")
                    messages.error(request, f"Failed to generate new PIN: {response.get('errmsg', 'Unknown error')}")
                    return redirect('edit_guest', guest_id=guest.id)
                guest.front_door_pin = new_pin
                guest.front_door_pin_id = response["keyboardPwdId"]
                guest.save()
                logger.info(f"Generated new PIN {new_pin} for guest {guest.reservation_number} (Keyboard Password ID: {response['keyboardPwdId']})")
                messages.success(request, f"New front door PIN generated: {new_pin}. The guest can also unlock the door remotely during check-in or from the room detail page.")
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
            guest.assigned_room_id = request.POST.get('room')

            # If dates have changed, update the PIN validity period
            if (guest.check_in_date != check_in_date or guest.check_out_date != check_out_date):
                if guest.front_door_pin_id:
                    front_door_lock = TTLock.objects.filter(is_front_door=True).first()
                    if front_door_lock:
                        ttlock_client = TTLockClient()
                        try:
                            # Delete the old PIN
                            ttlock_client.delete_pin(
                                lock_id=front_door_lock.lock_id,
                                keyboard_pwd_id=guest.front_door_pin_id,
                            )
                            logger.info(f"Deleted old PIN for guest {guest.reservation_number} due to date change (Keyboard Password ID: {guest.front_door_pin_id})")
                            
                            # Generate a new PIN with updated validity
                            new_pin = str(random.randint(1000, 9999))  # 4-digit PIN
                            uk_timezone = pytz.timezone("Europe/London")
                            now_uk_time = timezone.now().astimezone(uk_timezone)
                            start_time = int(now_uk_time.timestamp() * 1000)
                            # Set endDate to one week from now to ensure the passcode is active
                            end_date = now_uk_time + datetime.timedelta(days=7)
                            end_time = int(end_date.timestamp() * 1000)

                            response = ttlock_client.generate_temporary_pin(
                                lock_id=front_door_lock.lock_id,
                                pin=new_pin,
                                start_time=start_time,
                                end_time=end_time,
                                name=f"{guest.assigned_room.name} - {guest.full_name} - {new_pin}",  # Include PIN in name
                            )
                            if "keyboardPwdId" not in response:
                                logger.error(f"Failed to generate new PIN for guest {guest.reservation_number} after date change: {response.get('errmsg', 'Unknown error')}")
                                messages.warning(request, f"Failed to update PIN after date change: {response.get('errmsg', 'Unknown error')}")
                            else:
                                guest.front_door_pin = new_pin
                                guest.front_door_pin_id = response["keyboardPwdId"]
                                logger.info(f"Generated new PIN {new_pin} for guest {guest.reservation_number} after date change (Keyboard Password ID: {response['keyboardPwdId']})")
                                messages.info(request, f"PIN updated due to date change: {new_pin}. The guest can also unlock the door remotely during check-in or from the room detail page.")
                        except Exception as e:
                            logger.error(f"Failed to update PIN for guest {guest.reservation_number} after date change: {str(e)}")
                            messages.warning(request, f"Failed to update PIN after date change: {str(e)}")

            guest.check_in_date = check_in_date
            guest.check_out_date = check_out_date
            guest.save()
            logger.info(f"Updated guest {guest.reservation_number} details")
            messages.success(request, f"Guest {guest.full_name} updated successfully. The guest can unlock the door using their PIN or remotely during check-in or from the room detail page.")

        return redirect('admin_page')

    available_rooms = get_available_rooms(guest.check_in_date, guest.check_out_date) | Room.objects.filter(id=guest.assigned_room.id)

    return render(request, 'main/edit_guest.html', {
        'guest': guest,
        'rooms': available_rooms,
    })



@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def delete_guest(request, guest_id):
    guest = get_object_or_404(Guest, id=guest_id)
    guest_name = guest.full_name
    front_door_lock = TTLock.objects.filter(is_front_door=True).first()
    ttlock_client = TTLockClient()

    if guest.front_door_pin_id and front_door_lock:
        try:
            ttlock_client.delete_pin(
                lock_id=front_door_lock.lock_id,
                keyboard_pwd_id=guest.front_door_pin_id,
            )
            logger.info(f"Deleted PIN for guest {guest.reservation_number} (Keyboard Password ID: {guest.front_door_pin_id})")
        except Exception as e:
            logger.error(f"Failed to delete PIN for guest {guest.reservation_number}: {str(e)}")
            messages.warning(request, f"Failed to delete PIN for {guest_name}: {str(e)}")

    guest.delete()
    logger.info(f"Deleted guest {guest.reservation_number}")
    messages.success(request, f"Guest {guest_name} deleted successfully.")
    return redirect('admin_page')



@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
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
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
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