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

    # STEP 0: Get list of existing event IDs BEFORE polling
    # This allows us to detect truly NEW events
    existing_event_ids = set(PopularEvent.objects.values_list('event_id', flat=True))
    logger.info(f"Existing events in database: {len(existing_event_ids)}")

    # Fetch ALL future events
    today = date.today()
    
    # Priority venue IDs from Ticketmaster API
    priority_venue_ids = [
        'KovZ9177z1f',  # Co-op Live
        'Z7r9jZaAWw',   # AO Arena (main)
        'KovZ9177A4f',  # AO Arena (alternate)
        'KovZpZAnJ6AA', # Etihad Stadium (Manchester)
        'KovZ9177TpV',  # The Warehouse Project
    ]
    
    # Strategy: Query by venue ID for priority venues, then query Manchester for all others
    all_events_data = []
    
    # STEP 1: Fetch ALL events from priority venues (by venue ID)
    logger.info("Fetching events from priority venues by venue ID...")
    for venue_id in priority_venue_ids:
        page = 0
        max_pages = 20
        
        while page < max_pages:
            params = {
                'apikey': settings.TICKETMASTER_CONSUMER_KEY,
                'venueId': venue_id,
                'size': 200,
                'page': page,
                'sort': 'date,asc',
                'startDateTime': f"{today.isoformat()}T00:00:00Z",
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
                logger.error(f"Ticketmaster API error for venue {venue_id}, page {page}: {str(e)}")
                break

            page_data = data.get('_embedded', {}).get('events', [])
            
            if not page_data:
                break
            
            all_events_data.extend(page_data)
            
            page_info = data.get('page', {})
            total_pages = page_info.get('totalPages', 1)
            
            logger.info(f"Venue {venue_id}: Fetched page {page + 1}/{total_pages}: {len(page_data)} events")
            
            if page + 1 >= total_pages:
                break
            
            page += 1
    
    logger.info(f"Fetched {len(all_events_data)} events from priority venues")
    
    # STEP 2: Also fetch general Manchester events (to catch other venues)
    logger.info("Fetching general Manchester events...")
    page = 0
    max_pages = 20
    
    while page < max_pages:
        params = {
            'apikey': settings.TICKETMASTER_CONSUMER_KEY,
            'city': 'Manchester',
            'countryCode': 'GB',
            'size': 200,
            'page': page,
            'sort': 'date,asc',
            'startDateTime': f"{today.isoformat()}T00:00:00Z",
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
            logger.error(f"Ticketmaster API error for Manchester, page {page}: {str(e)}")
            break

        page_data = data.get('_embedded', {}).get('events', [])
        
        if not page_data:
            break
        
        all_events_data.extend(page_data)
        
        page_info = data.get('page', {})
        total_pages = page_info.get('totalPages', 1)
        
        logger.info(f"Manchester: Fetched page {page + 1}/{total_pages}: {len(page_data)} events")
        
        if page + 1 >= total_pages:
            break
        
        page += 1

    events_data = all_events_data
    
    if not events_data:
        logger.info("No events found from Ticketmaster")
        return "No events found"
    
    logger.info(f"Total events fetched from Ticketmaster: {len(events_data)}")

    created_count = 0
    updated_count = 0
    new_priority_events = []  # Track newly created priority events (by comparing event_ids)
    updated_priority_events = []  # Track updated events that became priority
    
    # Track which event_ids we've seen in this poll
    polled_event_ids = set()

    for event in events_data:
        polled_event_ids.add(event.get('id'))
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
                # SMART CHECK: Only alert if event_id is TRULY NEW (wasn't in database before)
                is_truly_new = event_id not in existing_event_ids
                
                if is_truly_new and event_obj.is_priority_venue and event_obj.should_send_sms:
                    new_priority_events.append(event_obj.id)
                    logger.info(f"✨ NEW priority event: {event_obj.name} at {event_obj.venue} (Score: {event_obj.popularity_score})")
            else:
                updated_count += 1
                # Check if an existing event became priority (e.g., sold out)
                # Only alert if it WASN'T already sent
                if event_obj.should_send_sms and not event_obj.sms_sent:
                    # This is an existing event that just became priority
                    is_newly_priority = event_id in existing_event_ids
                    if is_newly_priority:
                        updated_priority_events.append(event_obj.id)
                        logger.info(f"📈 Event became priority: {event_obj.name} at {event_obj.venue} (Score: {event_obj.popularity_score})")

        except Exception as e:
            logger.error(f"Error processing event {event.get('id')}: {str(e)}")
            continue

    # Calculate truly new events (event_ids that didn't exist before)
    truly_new_event_ids = polled_event_ids - existing_event_ids
    
    logger.info(
        f"Ticketmaster polling complete:\n"
        f"  - Total fetched: {len(events_data)} events\n"
        f"  - Created in DB: {created_count}\n"
        f"  - Updated in DB: {updated_count}\n"
        f"  - Truly NEW events (not seen before): {len(truly_new_event_ids)}\n"
        f"  - New priority events: {len(new_priority_events)}\n"
        f"  - Updated priority events: {len(updated_priority_events)}"
    )

    # Trigger alerts ONLY for new and updated priority events
    all_priority_events = new_priority_events + updated_priority_events
    
    if all_priority_events:
        check_new_important_events.delay(new_event_ids=all_priority_events)
        logger.info(f"🔔 Triggering alerts for {len(all_priority_events)} priority events")
    else:
        logger.info("No new priority events - no alerts needed")

    return f"Fetched: {len(events_data)}, New: {len(truly_new_event_ids)}, Priority alerts: {len(all_priority_events)}"


def calculate_popularity_score(ticket_min, ticket_max, is_sold_out, venue_name):
    """
    Calculate popularity score (0-100) based on event attributes.

    Scoring factors:
    - Sold out: +50
    - High ticket price: +35
    - Priority venue: +35-50 (major venues get higher scores)
    - Base score for any event: +15 (increased from +10)
    - Missing price at major venue: +15 bonus (assume premium event)
    """
    score = 15  # Base score for any event (increased from 10)

    # Sold out = instant high score
    if is_sold_out:
        score += 50

    # Check if price is available
    max_price = ticket_max or ticket_min or 0
    has_price = max_price > 0
    
    # Ticket price indicator (increased scoring)
    if max_price > 100:
        score += 35
    elif max_price > 75:
        score += 28
    elif max_price > 50:
        score += 22
    elif max_price > 30:
        score += 12
    elif max_price > 15:
        score += 5

    # Venue importance (increased scoring)
    is_major_venue = False
    if 'Manchester Warehouse Project' in venue_name or 'Warehouse Project' in venue_name:
        score += 50  # Increased from 40 - always premium
        is_major_venue = True
    elif any(v in venue_name for v in ['Co-op Live', 'Etihad Stadium', 'AO Arena']):
        score += 40  # Increased from 35 - tier 1 venues
        is_major_venue = True
    elif any(v in venue_name for v in settings.MAJOR_VENUES):
        score += 25  # Increased from 20 - tier 2 venues
        is_major_venue = True
    
    # Bonus: If no price info but at major venue, assume it's a premium event
    if not has_price and is_major_venue:
        score += 15  # Bonus for missing price at major venues

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
    Check for new important events and send EMAIL + SMS alerts.

    Triggered after poll_ticketmaster_events finds new priority events.

    Alert criteria:
    1. NEW event at Manchester Warehouse Project (always)
    2. NEW event with popularity_score >= 60 (HIGH or CRITICAL)
    3. NEW sold-out event at Co-op Live, Etihad, AO Arena
    
    Email: Full details of all new events
    SMS: Simple list with dates (max 10 events per SMS)

    Args:
        new_event_ids: List of newly created event IDs to check
    """
    from main.models import PopularEvent
    from twilio.rest import Client
    from django.core.mail import send_mail
    from django.urls import reverse

    logger.info("Checking for important events requiring alerts...")

    # Query for NEW events (provided by poll task)
    if not new_event_ids:
        logger.info("No new event IDs provided")
        return "No new events"
    
    # Get the new priority events
    query = PopularEvent.objects.filter(
        id__in=new_event_ids,
        sms_sent=False,
        date__gte=date.today()
    )

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

    # STEP 1: Send EMAIL with full details
    email_sent = send_email_alert(events_to_alert)
    
    # STEP 2: Send SMS with simple list (only if not exceeding daily limit)
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    sms_sent_today = PopularEvent.objects.filter(
        sms_sent=True,
        sms_sent_at__gte=today_start
    ).count()
    
    max_sms_per_day = 10  # Increased limit
    sms_sent = False
    
    if sms_sent_today < max_sms_per_day:
        sms_sent = send_sms_alert(events_to_alert)
    else:
        logger.info(f"SMS daily limit reached ({sms_sent_today}/{max_sms_per_day})")
    
    # Mark all events as notified
    for event in events_to_alert:
        event.sms_sent = True
        event.sms_sent_at = timezone.now()
        event.save()
    
    result_msg = f"Email: {'✓' if email_sent else '✗'}, SMS: {'✓' if sms_sent else '✗'}, Events: {len(events_to_alert)}"
    logger.info(f"Alert summary: {result_msg}")
    return result_msg


def send_email_alert(events):
    """Send detailed email alert with all new priority events"""
    from django.core.mail import send_mail
    
    if not events:
        return False
    
    try:
        # Build email subject
        event_count = len(events)
        subject = f"🎫 {event_count} New Priority Event{'s' if event_count > 1 else ''} - Price Suggester"
        
        # Build email body with full details
        body_lines = [
            "New priority events have been detected in Manchester:\n",
            "=" * 70,
            ""
        ]
        
        for i, event in enumerate(events, 1):
            # Get price display
            if event.ticket_min_price and event.ticket_max_price:
                price_range = f"£{event.ticket_min_price} - £{event.ticket_max_price}"
            elif event.ticket_min_price:
                price_range = f"£{event.ticket_min_price}+"
            else:
                price_range = "N/A"
            
            venue_emoji = get_venue_emoji(event.venue)
            popularity_emoji = get_popularity_emoji(event.popularity_level)
            
            body_lines.extend([
                f"{i}. {venue_emoji} {event.name}",
                f"   Date: {event.date.strftime('%A, %B %d, %Y')}",
                f"   Venue: {event.venue}",
                f"   Ticket Price: {price_range}",
                f"   Popularity: {popularity_emoji} {event.popularity_level} ({event.popularity_score}/100)",
                f"   Suggested Room Price: £{event.suggested_room_price}",
                f"   {'SOLD OUT' if event.is_sold_out else 'Tickets Available'}",
                f"   Details: https://pickarooms-495ab160017c.herokuapp.com/admin-page/event/{event.id}/",
                ""
            ])
        
        body_lines.extend([
            "=" * 70,
            "\nView all events: https://pickarooms-495ab160017c.herokuapp.com/price-suggester/",
            "\n--\nAutomated Price Suggester Alert",
            "Polling every 10 minutes from Ticketmaster"
        ])
        
        body = "\n".join(body_lines)
        
        # Send email
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.DEFAULT_FROM_EMAIL],  # Send to yourself
            fail_silently=False,
        )
        
        logger.info(f"Email alert sent for {event_count} events")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email alert: {str(e)}")
        return False


def send_sms_alert(events):
    """Send SMS with simple event list"""
    from twilio.rest import Client
    
    if not events:
        return False
    
    try:
        twilio_client = Client(
            settings.TWILIO_ACCOUNT_SID,
            settings.TWILIO_AUTH_TOKEN
        )
        
        # Build simple SMS message (max 1600 chars for SMS)
        event_count = len(events)
        message_lines = [
            f"🎫 {event_count} NEW PRIORITY EVENT{'S' if event_count > 1 else ''}\n"
        ]
        
        # List up to 10 events
        for event in events[:10]:
            venue_short = event.venue.replace('Co-op Live', 'Co-op').replace('AO Arena', 'AO').replace('The Warehouse Project', 'WHP')
            message_lines.append(
                f"• {event.date.strftime('%m/%d')}: {event.name[:40]} @ {venue_short}"
            )
        
        if event_count > 10:
            message_lines.append(f"\n+ {event_count - 10} more events")
        
        message_lines.append("\nCheck email for full details")
        
        message = "\n".join(message_lines)
        
        # Send SMS
        twilio_client.messages.create(
            body=message,
            from_=settings.TWILIO_PHONE_NUMBER,
            to=settings.ADMIN_PHONE_NUMBER
        )
        
        logger.info(f"SMS alert sent for {event_count} events")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send SMS alert: {str(e)}")
        return False


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
