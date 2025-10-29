"""
Public-facing views (no login required).
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


# 2. awards_reviews (line ~103)
def awards_reviews(request):
    latest_file = ReviewCSVUpload.objects.last()
    
    if latest_file and latest_file.data:
        reviews = latest_file.data
        filtered_reviews = [r for r in reviews if r["score"] >= 9 and r["text"].strip()]
        all_reviews = sorted(filtered_reviews, key=lambda x: x["score"], reverse=True)[:20]
    else:
        all_reviews = []

    return render(request, "main/awards_reviews.html", {"all_reviews": all_reviews})


# 3. about (line ~115)
def about(request):
    return render(request, 'main/about.html')

# 4. explore_manchester (line ~118)
def explore_manchester(request):
    return render(request, 'main/explore_manchester.html', {
        'GOOGLE_MAPS_API_KEY': settings.GOOGLE_MAPS_API_KEY
    })

# 5. contact (line ~953)
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

# 6. rebook_guest (line ~947)
def rebook_guest(request):
    return render(request, 'main/rebook_guest.html', {
        'booking_link': "https://www.booking.com/hotel/gb/double-bed-room-with-on-suite-near-etihad-manchester-city.en-gb.html?label=gen173nr-1BCAsoUEI5ZG91YmxlLWJlZC1yb29tLXdpdGgtb24tc3VpdGUtbmVhci1ldGloYWQtbWFuY2hlc3Rlci1jaXR5SDNYBGhQiAEBmAEJuAEYyAEM2AEB6AEBiAIBqAIEuAKSxdG9BsACAdICJGM2MGZlZWIxLWFhN2QtNGNjMC05MGVjLWMxNWYwZmM1ZDcyMdgCBeACAQ&sid=7613f9a14781ff8d39041ce2257bfde6&dist=0&keep_landing=1&sb_price_type=total&type=total&",
    })

# 7. privacy_policy (line ~2591)
def privacy_policy(request):
    return render(request, 'main/privacy_policy.html')

# 8. terms_of_use (line ~2594)
def terms_of_use(request):
    return render(request, 'main/terms_of_use.html')

# 9. terms_conditions (line ~2597)
def terms_conditions(request):
    return render(request, 'main/terms_conditions.html')

# 10. cookie_policy (line ~2600)
def cookie_policy(request):
    return render(request, 'main/cookie_policy.html')

# 11. sitemap (line ~2603)
def sitemap(request):
    return render(request, 'main/sitemap.html')

# 12. how_to_use (line ~2606)
def how_to_use(request):
    return render(request, 'main/how_to_use.html')

# 13. event_finder (line ~3252)
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

    # Log the API request for debugging, redacting the API key
    request_url = 'https://app.ticketmaster.com/discovery/v2/events.json' + '?' + '&'.join(
        f"{k}={'[REDACTED]' if k == 'apikey' else v}" for k, v in params.items()
    )
    logger.info(f"Ticketmaster API request URL: {request_url}")

    # Call the Ticketmaster API
    try:
        response = requests.get('https://app.ticketmaster.com/discovery/v2/events.json', params=params)
        response.raise_for_status()  # Raise an error for bad status codes
        data = response.json()
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

# 14. price_suggester (line ~3369) - ADMIN ONLY, might move to admin_dashboard
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