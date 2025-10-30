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

# 13. event_finder - PUBLIC, uses same database as price_suggester
def event_finder(request):
    """Display events for guests using the same PopularEvent database."""
    today = date.today()
    
    # Get parameters
    city = request.GET.get('city', 'Manchester')
    keyword = request.GET.get('keyword', '')
    start_date_str = request.GET.get('start_date', today.strftime('%Y-%m-%d'))
    end_date_str = request.GET.get('end_date', (today + timedelta(days=180)).strftime('%Y-%m-%d'))
    page = int(request.GET.get('page', 1))

    # Parse dates
    try:
        start_date = dt.datetime.strptime(start_date_str, '%Y-%m-%d').date()
    except ValueError:
        start_date = today

    try:
        end_date = dt.datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        end_date = today + timedelta(days=180)

    # Query PopularEvent database
    events_query = PopularEvent.objects.filter(
        date__gte=start_date,
        date__lte=end_date
    )

    # Apply keyword search
    if keyword:
        events_query = events_query.filter(
            Q(venue__icontains=keyword) | Q(name__icontains=keyword)
        )
    else:
        # Default: show popular events at major venues
        major_venues = ['Co-op Live', 'AO Arena', 'Etihad Stadium', 'Old Trafford', 'Warehouse']
        venue_queries = Q()
        for venue in major_venues:
            venue_queries |= Q(venue__icontains=venue)
        events_query = events_query.filter(venue_queries | Q(popularity_score__gte=60))

    # Order by date
    events_query = events_query.order_by('date', '-popularity_score')

    # Pagination
    paginator = Paginator(events_query, 10)
    try:
        events_page = paginator.page(page)
    except:
        events_page = paginator.page(1)
        page = 1

    # Build events list for template
    events = []
    for event in events_page:
        # Get price display
        if event.ticket_min_price and event.ticket_max_price:
            ticket_price = f"£{event.ticket_min_price} - £{event.ticket_max_price}"
        elif event.ticket_min_price:
            ticket_price = f"£{event.ticket_min_price}+"
        else:
            ticket_price = "N/A"

        event_data = {
            'name': event.name,
            'date': event.date.strftime('%Y-%m-%d'),
            'time': '',  # Time not stored separately
            'venue': event.venue,
            'url': f'https://www.ticketmaster.co.uk/search?q={event.name.replace(" ", "+")}',
            'image': event.image_url,
            'is_sold_out': event.is_sold_out,
            'ticket_price': ticket_price,
        }
        events.append(event_data)

    # Page range
    total_pages = paginator.num_pages
    page_range = []
    start_page_num = max(1, page - 2)
    end_page_num = min(total_pages, page + 2)
    for i in range(start_page_num, end_page_num + 1):
        page_range.append(i)

    context = {
        'events': events,
        'city': city,
        'keyword': keyword,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'current_page': page,
        'total_pages': total_pages,
        'total_elements': paginator.count,
        'page_range': page_range,
    }
    return render(request, 'main/event_finder.html', context)

# 14. price_suggester - ADMIN ONLY, reads from database populated by Celery tasks
@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def price_suggester(request):
    """
    Suggest room prices based on popular events near M11 3NP.
    Events are automatically populated by the poll_ticketmaster_events Celery task.
    """
    # Base room price
    base_price = 50

    # Manually collected average hotel price near M11 3NP
    average_hotel_price = 80

        # Default date range (from today to 365 days from now)
    today = date.today()
    start_date_str = request.GET.get('start_date', today.strftime('%Y-%m-%d'))
    end_date_str = request.GET.get('end_date', (today + timedelta(days=365)).strftime('%Y-%m-%d'))
    keyword = request.GET.get('keyword', '')  # Search by venue name
    show_sold_out = request.GET.get('show_sold_out', '')  # Filter for sold-out events
    page = int(request.GET.get('page', 1))
    venue_filter = request.GET.get('filter', 'priority')  # 'priority' or 'all'
    view_mode = request.GET.get('view', 'calendar')  # 'list' or 'calendar' - default to calendar

    # Parse dates
    try:
        start_date = dt.datetime.strptime(start_date_str, '%Y-%m-%d').date()
    except ValueError:
        start_date = today

    try:
        end_date = dt.datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        end_date = today + timedelta(days=365)

                    # Query PopularEvent model from database
    # FIX: Ensure date filtering works correctly - use gte and lte instead of range
    events_query = PopularEvent.objects.filter(
        date__gte=start_date,
        date__lte=end_date
    )

    # Log query parameters for debugging
    logger.info(f"Price suggester query: start={start_date}, end={end_date}, keyword='{keyword}', sold_out={show_sold_out}, filter={venue_filter}")
    
    # Apply keyword search filter (takes precedence over venue filter)
    if keyword:
        events_query = events_query.filter(
            Q(venue__icontains=keyword) | Q(name__icontains=keyword)
        )
    else:
        # Only apply venue filter if no keyword search is active
        priority_venues = ['Co-op Live', 'Co-Op Live', 'The Co-op Live', 'AO Arena', 'Etihad Stadium', 'Manchester Warehouse Project', 'Warehouse Project']
        
        if venue_filter == 'priority':
            # Filter to priority venues only
            venue_queries = Q()
            for venue in priority_venues:
                venue_queries |= Q(venue__icontains=venue)
            events_query = events_query.filter(venue_queries)

    # Apply sold-out filter
    if show_sold_out:
        events_query = events_query.filter(is_sold_out=True)

    # Order by date, then popularity score
    events_query = events_query.order_by('date', '-popularity_score')
    
    # Log result count
    logger.info(f"Price suggester found {events_query.count()} events matching criteria")

    # For calendar view, get all events (no pagination)
    if view_mode == 'calendar':
        events_to_display = events_query
        total_pages = 1
        total_elements = events_query.count()
        page_range = []
    else:
        # Pagination (15 events per page - increased from 10)
        paginator = Paginator(events_query, 15)
        try:
            events_page = paginator.page(page)
        except:
            events_page = paginator.page(1)
            page = 1
        events_to_display = events_page
        total_pages = paginator.num_pages
        total_elements = paginator.count
        # Limit page range to 5 pages around the current page
        page_range = []
        start_page_num = max(1, page - 2)
        end_page_num = min(total_pages, page + 2)
        for i in range(start_page_num, end_page_num + 1):
            page_range.append(i)

    # Build suggestions list
    suggestions = []
    for event in events_to_display:
        # Get price range display
        if event.ticket_min_price and event.ticket_max_price:
            ticket_price = f"£{event.ticket_min_price} - £{event.ticket_max_price}"
        elif event.ticket_min_price:
            ticket_price = f"£{event.ticket_min_price}+"
        else:
            ticket_price = event.ticket_price  # Legacy format

        # Get color code for display
        if event.popularity_score >= 80:
            color = 'red'
        elif event.popularity_score >= 60:
            color = 'orange'
        elif event.popularity_score >= 40:
            color = 'yellow'
        else:
            color = 'green'

        event_details = {
            'id': event.id,
            'event_id': event.event_id,
            'name': event.name,
            'date': event.date,
            'venue': event.venue,
            'ticket_price': ticket_price,
            'suggested_price': f"£{event.suggested_room_price}",
            'image': event.image_url,
            'is_sold_out': event.is_sold_out,
            'popularity_score': event.popularity_score,
            'color': color,
        }
        suggestions.append(event_details)

    # Prepare calendar events JSON (for calendar view)
    import json
    calendar_events = []
    if view_mode == 'calendar':
        for event_details in suggestions:
            calendar_event = {
                'id': event_details['id'],
                'title': event_details['name'],
                'start': event_details['date'].strftime('%Y-%m-%d'),
                'backgroundColor': {
                    'red': '#e74c3c',
                    'orange': '#e67e22',
                    'yellow': '#f39c12',
                    'green': '#27ae60'
                }.get(event_details['color'], '#3498db'),
                'borderColor': {
                    'red': '#c0392b',
                    'orange': '#d35400',
                    'yellow': '#f39c12',
                    'green': '#27ae60'
                }.get(event_details['color'], '#2980b9'),
                'extendedProps': {
                    'venue': event_details['venue'],
                    'popularity': event_details['popularity_score'],
                    'suggestedPrice': event_details['suggested_price'].replace('£', ''),
                    'soldOut': event_details['is_sold_out']
                }
            }
            calendar_events.append(calendar_event)

    calendar_events_json = json.dumps(calendar_events)

    context = {
        'suggestions': suggestions,
        'base_price': f"£{base_price}",
        'average_hotel_price': f"£{average_hotel_price}",
        'start_date': start_date_str,
        'end_date': end_date_str,
        'keyword': keyword,
        'show_sold_out': show_sold_out,
        'current_page': page,
        'total_pages': total_pages,
        'total_elements': total_elements,
        'page_range': page_range,
        'venue_filter': venue_filter,
        'view_mode': view_mode,
        'calendar_events': calendar_events_json,
    }

    return render(request, 'main/price_suggester.html', context)


@login_required
def event_detail(request, event_id):
    """
    Display detailed information about a specific event.
    Linked from SMS alerts sent for important events.
    """
    event = get_object_or_404(PopularEvent, id=event_id)

    # Calculate additional context
    days_until_event = (event.date - date.today()).days

    # Get price range display
    if event.ticket_min_price and event.ticket_max_price:
        price_range = f"£{event.ticket_min_price} - £{event.ticket_max_price}"
    elif event.ticket_min_price:
        price_range = f"£{event.ticket_min_price}+"
    else:
        price_range = event.ticket_price  # Legacy format

    # Get color code based on popularity
    if event.popularity_score >= 80:
        color = 'red'
        level = 'CRITICAL'
    elif event.popularity_score >= 60:
        color = 'orange'
        level = 'HIGH'
    elif event.popularity_score >= 40:
        color = 'yellow'
        level = 'MEDIUM'
    else:
        color = 'green'
        level = 'LOW'

    context = {
        'event': event,
        'days_until_event': days_until_event,
        'price_range': price_range,
        'color': color,
        'popularity_level': level,
    }

    return render(request, 'main/event_detail.html', context)