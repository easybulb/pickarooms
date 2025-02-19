from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.mail import EmailMessage, BadHeaderError
from django.conf import settings
from django.http import HttpResponse
from django.utils.timezone import now, localtime
from django.utils import timezone
from datetime import date, datetime, time
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
import datetime  # ✅ This is fine, but should be used carefully with Django's `timezone`
from .models import Guest, Room, ReviewCSVUpload


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
        "reservation_number": request.session.get("reservation_number", ""),  # ✅ Prefill from session
    }

    return render(request, "main/home.html", context)




def awards_reviews(request):
    # Fetch the latest uploaded review data
    latest_file = ReviewCSVUpload.objects.last()
    
    if latest_file and latest_file.data:
        reviews = latest_file.data  # Access stored review data

        # Filter reviews with a score of 9 or 10 AND ensure the positive review column is not empty
        filtered_reviews = [r for r in reviews if r["score"] >= 9 and r["text"].strip()]

        # Sort reviews by highest score first and select up to 20
        all_reviews = sorted(filtered_reviews, key=lambda x: x["score"], reverse=True)[:20]
    else:
        all_reviews = []  # Empty list if no review data is available

    return render(request, "main/awards_reviews.html", {"all_reviews": all_reviews})



def about(request):
    return render(request, 'main/about.html')

def explore_manchester(request):
    return render(request, 'main/explore_manchester.html')




@ratelimit(key='ip', rate='10/m', method='POST', block=True)
def checkin(request):
    if request.method == 'POST':
        reservation_number = request.POST.get('reservation_number', '').strip()

        # Find guest using only the unique Booking.com reservation number
        guest = Guest.objects.filter(reservation_number=reservation_number).order_by('-check_in_date').first()

        if guest:
            # 🔒 Securely store reservation number in session
            request.session['reservation_number'] = guest.reservation_number
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
        "reservation_number": request.session.get("reservation_number", ""),  # ✅ Prefill from session
    })



def room_detail(request, room_token):
    reservation_number = request.session.get("reservation_number", None)
    guest = get_object_or_404(Guest, secure_token=room_token)

    # 🔐 Ensure only the correct guest can access their room
    if not reservation_number or guest.reservation_number != reservation_number:
        return redirect("unauthorized")

    room = guest.assigned_room

    # ✅ Get UK time (handling Daylight Saving Time)
    uk_timezone = pytz.timezone("Europe/London")
    now_uk_time = timezone.now().astimezone(uk_timezone)  # ✅ Now includes time

    # ✅ Convert check-in and check-out dates to aware datetimes
    check_in_datetime = timezone.make_aware(
        datetime.datetime.combine(guest.check_in_date, datetime.time(14, 0)),  # ✅ 2 PM check-in time
        datetime.timezone.utc,
    ).astimezone(uk_timezone)

    check_out_datetime = timezone.make_aware(
        datetime.datetime.combine(guest.check_out_date, datetime.time(11, 0)),  # ✅ 11 AM check-out time
        datetime.timezone.utc,
    ).astimezone(uk_timezone)

    # ✅ Convert to date for comparison
    check_in_date = check_in_datetime.date()
    check_out_date = check_out_datetime.date()

    # ✅ If guest has checked out, remove reservation from session and redirect to rebook
    if now_uk_time > check_out_datetime:
        request.session.pop("reservation_number", None)  # 🔥 Remove stored reservation number
        return redirect("rebook_guest")

    # ✅ Only enforce 2 PM rule if today is the check-in day AND before 2 PM
    enforce_2pm_rule = now_uk_time < check_in_datetime  # ✅ Compare full datetime now

    return render(
        request,
        "main/room_detail.html",
        {
            "room": room,
            "guest": guest,
            "image_url": room.image or None,
            "expiration_message": f"Your access will expire on {guest.check_out_date.strftime('%d %b %Y')} at 11:00 AM.",
            "show_pin": not enforce_2pm_rule,  # ✅ PIN shows from 2 PM UK time onwards
        },
    )





def rebook_guest(request):
    return render(request, 'main/rebook_guest.html', {
        'booking_link': "https://www.booking.com/hotel/gb/double-bed-room-with-on-suite-near-etihad-manchester-city.en-gb.html?label=gen173nr-1BCAsoUEI5ZG91YmxlLWJlZC1yb29tLXdpdGgtb24tc3VpdGUtbmVhci1ldGloYWQtbWFuY2hlc3Rlci1jaXR5SDNYBGhQiAEBmAEJuAEYyAEM2AEB6AEBiAIBqAIEuAKSxdG9BsACAdICJGM2MGZlZWIxLWFhN2QtNGNjMC05MGVjLWMxNWYwZmM1ZDcyMdgCBeACAQ&sid=7613f9a14781ff8d39041ce2257bfde6&dist=0&keep_landing=1&sb_price_type=total&type=total&",
    })




def contact(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        message = request.POST.get('message')

        subject = f"Contact Us Message from {name}"
        body = f"Name: {name}\nEmail: {email}\n\nMessage:\n{message}"

        try:
            # Use EmailMessage instead of send_mail for better header control
            email_message = EmailMessage(
                subject=subject,
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,  # Must be your Gmail address
                to=['easybulb@gmail.com'],  # Your email to receive messages
                reply_to=[email]  # Allows proper reply-to behavior
            )
            email_message.send()

        except BadHeaderError:
            return HttpResponse("Invalid header found.", status=400)
        except Exception as e:
            return HttpResponse(f"Error: {str(e)}", status=500)

        return render(request, 'main/contact.html', {
            'success': True,
            "GOOGLE_MAPS_API_KEY": settings.GOOGLE_MAPS_API_KEY,
        })

    return render(request, 'main/contact.html', {
        "GOOGLE_MAPS_API_KEY": settings.GOOGLE_MAPS_API_KEY,
    })






class AdminLoginView(LoginView):
    template_name = 'main/admin_login.html'

    def get_success_url(self):
        # Redirect to the admin page after login
        return '/admin-page/'





@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def admin_page(request):
    """Admin Dashboard to manage guests, rooms, and assignments."""

    now_time = localtime(now())  # Get local timezone time
    today = now_time.date()
    current_time = now_time.time()
    archive_time = time(11, 0)  # Archive guests at 11:00 AM

    # ✅ Archive guests who checked out before today OR today after 11 AM
    if current_time >= archive_time:
        Guest.objects.filter(
            Q(check_out_date__lt=today) | 
            (Q(check_out_date=today) & Q(is_archived=False))
        ).update(is_archived=True)

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
        phone_number = request.POST.get('phone_number', '').strip() or None  # ✅ Optional
        full_name = request.POST.get('full_name', 'Guest').strip()
        room_id = request.POST.get('room')

        if not reservation_number:
            messages.error(request, "Reservation number is required.")
            return redirect('admin_page')

        try:
            room = Room.objects.get(id=room_id)

            # ✅ Check if reservation number already exists
            if Guest.objects.filter(reservation_number=reservation_number).exists():
                messages.error(request, "Reservation number already exists.")
                return redirect('admin_page')

            # ✅ Check if this guest has stayed before based on full name
            previous_stays = Guest.objects.filter(
                Q(full_name__iexact=full_name)  # Case-insensitive match on full name
            ).exists()

            # ✅ Create a new guest entry (DO NOT MODIFY OLD RECORDS)
            Guest.objects.create(
                full_name=full_name,
                reservation_number=reservation_number,  # ✅ Ensure Booking.com reservation number is used
                phone_number=phone_number,
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                assigned_room=room,
                is_returning=previous_stays  # ✅ Mark as returning if they stayed before (based on name)
            )

            messages.success(request, "Guest added successfully!")
            return redirect('admin_page')

        except Room.DoesNotExist:
            messages.error(request, "Invalid room selected.")
        except IntegrityError:  # ✅ Catch duplicate reservation number error (extra safety)
            messages.error(request, "Reservation number already exists.")
            return redirect('admin_page')

    return render(request, 'main/admin_page.html', {
        'rooms': available_rooms,
        'guests': guests,
        'check_in_date': check_in_date,
        'check_out_date': check_out_date,
    })








def get_available_rooms(check_in_date, check_out_date):
    """Returns rooms that are not assigned for the given date range."""
    # Convert dates if necessary
    check_in_date = date.fromisoformat(str(check_in_date)) if isinstance(check_in_date, str) else check_in_date
    check_out_date = date.fromisoformat(str(check_out_date)) if isinstance(check_out_date, str) else check_out_date

    # Find guests whose bookings overlap with the provided date range
    conflicting_guests = Guest.objects.filter(
        Q(check_in_date__lt=check_out_date) & Q(check_out_date__gt=check_in_date)
    )

    # Get IDs of rooms that are booked during the conflicting date range
    conflicting_rooms = conflicting_guests.values_list('assigned_room', flat=True)

    # Return rooms that are NOT in the list of conflicting rooms
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
        guest.full_name = request.POST.get('full_name')
        guest.reservation_number = request.POST.get('reservation_number', '').strip()
        guest.phone_number = request.POST.get('phone_number')
        guest.check_in_date = request.POST.get('check_in_date')
        guest.check_out_date = request.POST.get('check_out_date')
        guest.assigned_room_id = request.POST.get('room')
        guest.save()

        # ✅ Add success message
        messages.success(request, f"Guest {guest.full_name} updated successfully.")

        return redirect('admin_page')

    # Get available rooms for selected check-in and check-out dates
    available_rooms = get_available_rooms(guest.check_in_date, guest.check_out_date) | Room.objects.filter(id=guest.assigned_room.id)

    return render(request, 'main/edit_guest.html', {
        'guest': guest,
        'rooms': available_rooms,
    })




@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def delete_guest(request, guest_id):
    guest = get_object_or_404(Guest, id=guest_id)
    guest_name = guest.full_name  # Store guest name for message before deletion
    guest.delete()

    # ✅ Add success message
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

    # ✅ Update returning guest logic: Check if same full_name appears in past guests
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




