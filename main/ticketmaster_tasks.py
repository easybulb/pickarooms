"""
Celery tasks for Ticketmaster event polling and price suggestions
"""
from celery import shared_task
from django.utils import timezone
from django.conf import settings
from datetime import datetime, timedelta, date
import logging
import requests

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def poll_ticketmaster_events(self):
    """
    Poll Ticketmaster API for popular events in Manchester.
    Runs every 6 hours to keep event data fresh.

    Creates/updates PopularEvent records with:
    - Event details from Ticketmaster
    - Calculated popularity scores
    - Suggested room prices
    """
    from main.models import PopularEvent

    logger.info("Starting Ticketmaster event polling...")

    # Fetch events for next 365 days
    today = date.today()
    end_date = today + timedelta(days=365)

    # Priority venues for detailed scanning
    priority_venues = [
        'Manchester Warehouse Project',
        'Warehouse Project',
        'The Co-op Live',
        'Co-op Live',
        'Etihad Stadium',
        'AO Arena',
    ]

    # Ticketmaster API parameters
    params = {
        'apikey': settings.TICKETMASTER_CONSUMER_KEY,
        'city': 'Manchester',
        'countryCode': 'GB',
        'size': 200,  # Max events per request
        'page': 0,
        'sort': 'date,asc',
        'startDateTime': f"{today.isoformat()}T00:00:00Z",
        'endDateTime': f"{end_date.isoformat()}T23:59:59Z",
    }

    try:
        response = requests.get(
            'https://app.ticketmaster.com/discovery/v2/events.json',
            params=params,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Ticketmaster API error: {str(e)}")
        raise self.retry(exc=e)

    events_data = data.get('_embedded', {}).get('events', [])

    if not events_data:
        logger.info("No events found from Ticketmaster")
        return "No events found"

    created_count = 0
    updated_count = 0
    new_priority_events = []

    for event in events_data:
        try:
            # Extract event details
            event_id = event.get('id')
            name = event.get('name', 'Unknown Event')
            event_date_str = event.get('dates', {}).get('start', {}).get('localDate')

            if not event_date_str:
                continue

            event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()

            # Venue information
            venues = event.get('_embedded', {}).get('venues', [])
            venue_name = venues[0].get('name', 'Unknown Venue') if venues else 'Unknown Venue'

            # Price information
            price_ranges = event.get('priceRanges', [{}])
            ticket_min = price_ranges[0].get('min', 0) if price_ranges else 0
            ticket_max = price_ranges[0].get('max', 0) if price_ranges else 0

            # Status
            is_sold_out = event.get('dates', {}).get('status', {}).get('code') == 'soldout'

            # Image
            images = event.get('images', [])
            image_url = images[0].get('url') if images else None

            # Calculate popularity score
            popularity_score = calculate_popularity_score(
                ticket_min, ticket_max, is_sold_out, venue_name
            )

            # Calculate suggested room price
            suggested_room_price = calculate_suggested_price(
                popularity_score, is_sold_out, venue_name
            )

            # Legacy format for compatibility
            ticket_price_str = f"£{ticket_max}" if ticket_max else "N/A"
            suggested_price_str = f"£{suggested_room_price}"

            # Create or update event
            event_obj, created = PopularEvent.objects.update_or_create(
                event_id=event_id,
                defaults={
                    'name': name,
                    'date': event_date,
                    'venue': venue_name,
                    'ticket_min_price': ticket_min,
                    'ticket_max_price': ticket_max,
                    'ticket_price': ticket_price_str,
                    'suggested_price': suggested_price_str,
                    'suggested_room_price': suggested_room_price,
                    'is_sold_out': is_sold_out,
                    'popularity_score': popularity_score,
                    'image_url': image_url,
                    'description': event.get('description', ''),
                }
            )

            if created:
                created_count += 1
                # Track newly created priority events
                if event_obj.is_priority_venue and event_obj.should_send_sms:
                    new_priority_events.append(event_obj.id)
            else:
                updated_count += 1

        except Exception as e:
            logger.error(f"Error processing event {event.get('id')}: {str(e)}")
            continue

    logger.info(
        f"Ticketmaster polling complete: {created_count} created, "
        f"{updated_count} updated. Priority events: {len(new_priority_events)}"
    )

    # Trigger SMS check for new priority events
    if new_priority_events:
        check_new_important_events.delay(new_event_ids=new_priority_events)

    return f"Created: {created_count}, Updated: {updated_count}"


def calculate_popularity_score(ticket_min, ticket_max, is_sold_out, venue_name):
    """
    Calculate popularity score (0-100) based on event attributes.

    Scoring factors:
    - Sold out: +50
    - High ticket price: +30
    - Priority venue: +25-30
    """
    score = 0

    # Sold out = instant high score
    if is_sold_out:
        score += 50

    # Ticket price indicator
    max_price = ticket_max or ticket_min or 0
    if max_price > 100:
        score += 30
    elif max_price > 50:
        score += 20
    elif max_price > 30:
        score += 10

    # Venue importance
    if 'Manchester Warehouse Project' in venue_name or 'Warehouse Project' in venue_name:
        score += 30
    elif any(v in venue_name for v in ['Co-op Live', 'Etihad Stadium', 'AO Arena']):
        score += 25
    elif any(v in venue_name for v in settings.MAJOR_VENUES):
        score += 15

    return min(score, 100)  # Cap at 100


def calculate_suggested_price(popularity_score, is_sold_out, venue_name):
    """
    Calculate suggested room price based on event popularity.

    Price tiers:
    - £200: Warehouse Project or Critical events (80+)
    - £150: High popularity (60-79) or sold-out major venues
    - £100: Medium popularity (40-59)
    - £80: Low popularity (0-39)
    """
    # Manchester Warehouse Project = premium pricing
    if 'Manchester Warehouse Project' in venue_name or 'Warehouse Project' in venue_name:
        return 200

    # Critical popularity or sold-out major venues
    if popularity_score >= 80 or (is_sold_out and popularity_score >= 60):
        return 200

    # High popularity
    if popularity_score >= 60:
        return 150

    # Medium popularity
    if popularity_score >= 40:
        return 100

    # Low popularity
    return 80


@shared_task(bind=True, max_retries=1)
def check_new_important_events(self, new_event_ids=None):
    """
    Check for new important events and send SMS alerts.

    Runs every 12 hours OR triggered after poll_ticketmaster_events
    finds new priority events.

    SMS alert criteria:
    1. NEW event at Manchester Warehouse Project (always)
    2. NEW event with popularity_score >= 80
    3. NEW sold-out event at Co-op Live, Etihad, AO Arena
    4. Limit: Max 2 SMS per day (don't spam)

    Args:
        new_event_ids: List of newly created event IDs to check
    """
    from main.models import PopularEvent
    from twilio.rest import Client
    from django.urls import reverse

    logger.info("Checking for important events requiring SMS alerts...")

    # Check SMS limit (max 2 per day)
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    sms_sent_today = PopularEvent.objects.filter(
        sms_sent=True,
        sms_sent_at__gte=today_start
    ).count()

    if sms_sent_today >= 2:
        logger.info(f"SMS limit reached for today ({sms_sent_today}/2). Skipping alerts.")
        return "SMS limit reached"

    # Query for events that need SMS
    query = PopularEvent.objects.filter(
        sms_sent=False,
        date__gte=date.today()
    )

    # If specific events provided, filter to those
    if new_event_ids:
        query = query.filter(id__in=new_event_ids)

    # Get events that should send SMS
    events_to_alert = []
    for event in query:
        if event.should_send_sms:
            events_to_alert.append(event)

    if not events_to_alert:
        logger.info("No events require SMS alerts")
        return "No alerts needed"

    # Sort by priority: Warehouse Project first, then by popularity
    events_to_alert.sort(
        key=lambda e: (
            'Warehouse Project' not in e.venue,  # False (Warehouse) sorts first
            -e.popularity_score
        )
    )

    # Send SMS (max 2 per day)
    sms_count = 0
    max_sms = 2 - sms_sent_today

    try:
        twilio_client = Client(
            settings.TWILIO_ACCOUNT_SID,
            settings.TWILIO_AUTH_TOKEN
        )
    except Exception as e:
        logger.error(f"Twilio client initialization failed: {str(e)}")
        return "Twilio error"

    for event in events_to_alert[:max_sms]:
        try:
            # Build event detail URL
            event_url = f"https://pickarooms-495ab160017c.herokuapp.com/admin-page/event/{event.id}/"

            # Build SMS message
            venue_emoji = get_venue_emoji(event.venue)
            popularity_emoji = get_popularity_emoji(event.popularity_level)

            message = (
                f"{venue_emoji} NEW EVENT ALERT {popularity_emoji}\n\n"
                f"{event.name}\n"
                f"Date: {event.date.strftime('%a, %b %d, %Y')}\n"
                f"Venue: {event.venue}\n"
                f"Popularity: {event.popularity_level} ({event.popularity_score}/100)\n"
                f"Suggested Price: £{event.suggested_room_price}\n\n"
                f"View details: {event_url}"
            )

            # Send SMS
            twilio_client.messages.create(
                body=message,
                from_=settings.TWILIO_PHONE_NUMBER,
                to=settings.ADMIN_PHONE_NUMBER  # Your phone number
            )

            # Mark as sent
            event.sms_sent = True
            event.sms_sent_at = timezone.now()
            event.save()

            sms_count += 1
            logger.info(f"SMS sent for event: {event.name} at {event.venue}")

        except Exception as e:
            logger.error(f"Failed to send SMS for event {event.id}: {str(e)}")
            continue

    logger.info(f"Sent {sms_count} SMS alerts for important events")
    return f"Sent {sms_count} SMS alerts"


def get_venue_emoji(venue_name):
    """Get emoji for venue"""
    if 'Warehouse Project' in venue_name:
        return '🎧'  # Electronic music venue
    elif 'Etihad' in venue_name:
        return '⚽'  # Football stadium
    elif 'Arena' in venue_name or 'Co-op Live' in venue_name:
        return '🎤'  # Concert venue
    else:
        return '🎭'  # General event


def get_popularity_emoji(popularity_level):
    """Get emoji for popularity level"""
    return {
        'CRITICAL': '🔴',
        'HIGH': '🟠',
        'MEDIUM': '🟡',
        'LOW': '🟢',
    }.get(popularity_level, '⚪')
