# main/middleware.py
import requests
import json
import logging
from django.utils.timezone import now
from datetime import timedelta, date, datetime
from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from .models import PopularEvent

logger = logging.getLogger('main')

class PopularEventMonitorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.last_check_time = None

    def __call__(self, request):
        # Only check for admins under /price-suggester/ and not too frequently
        if request.user.is_authenticated and request.user.is_superuser and request.path == '/price-suggester/':
            current_time = now()
            # Check every 15 minutes
            if self.last_check_time is None or (current_time - self.last_check_time).total_seconds() >= 900:  # 900 seconds = 15 minutes
                self.check_for_new_events()
                self.last_check_time = current_time

        response = self.get_response(request)
        return response

    def check_for_new_events(self):
        today = date.today()
        start_date = today.strftime('%Y-%m-%d')
        end_date = (today + timedelta(days=365)).strftime('%Y-%m-%d')

        major_venues = settings.MAJOR_VENUES

        for page in range(100):  # Pages 0 to 99 (1 to 100), maximizing event coverage
            params = {
                'apikey': settings.TICKETMASTER_CONSUMER_KEY,
                'city': 'Manchester',
                'countryCode': 'GB',
                'size': 10,
                'page': page,
                'sort': 'date,asc',
                'startDateTime': f"{start_date}T00:00:00Z",
                'endDateTime': f"{end_date}T23:59:59Z",
            }

            detection_url = 'https://app.ticketmaster.com/discovery/v2/events.json?' + '&'.join(
                f"{k}={v}" for k, v in params.items()
            )
            logger.info(f"Ticketmaster API detection request URL (page {page}): {detection_url}")

            try:
                detection_response = requests.get('https://app.ticketmaster.com/discovery/v2/events.json', params=params)
                detection_response.raise_for_status()
                detection_data = detection_response.json()
                logger.info(f"Ticketmaster API detection response (page {page}): {json.dumps(detection_data, indent=2)}")
            except requests.exceptions.RequestException as e:
                logger.error(f"Ticketmaster API detection error on page {page}: {str(e)}")
                break

            detection_events = detection_data.get('_embedded', {}).get('events', [])
            if not detection_events:  # Break if no more events
                break

            existing_event_ids = set(PopularEvent.objects.values_list('event_id', flat=True))
            for event in detection_events:
                event_id = event.get('id')
                if event_id not in existing_event_ids:
                    price_info = event.get('priceRanges', [{}])[0]
                    min_price = price_info.get('min', 0)
                    max_price = price_info.get('max', 0)
                    ticket_price = max(min_price, max_price) if min_price or max_price else 0
                    is_sold_out = event.get('dates', {}).get('status', {}).get('code') == 'soldout'
                    venue_name = event.get('_embedded', {}).get('venues', [{}])[0].get('name', '') if event.get('_embedded', {}).get('venues') else 'Unknown Venue'
                    is_major_venue = any(major_venue in venue_name for major_venue in major_venues)
                    is_popular = is_sold_out or ticket_price > 40 or is_major_venue

                    if is_popular:
                        event_date = datetime.strptime(event.get('dates', {}).get('start', {}).get('localDate'), '%Y-%m-%d').date() if event.get('dates', {}).get('start', {}).get('localDate') else None
                        if event_date:
                            # Check if event already exists by event_id
                            existing_event = PopularEvent.objects.filter(event_id=event_id).first()
                            if existing_event:
                                # Update email_sent if not already sent
                                if not existing_event.email_sent:
                                    with transaction.atomic():
                                        existing_event.email_sent = True
                                        existing_event.save()
                                        logger.info(f"Updated existing event {existing_event.name} (ID: {existing_event.event_id}) with email_sent=True")
                            else:
                                # Create new event
                                new_event = PopularEvent(
                                    event_id=event_id,
                                    name=event.get('name'),
                                    date=event_date,
                                    venue=venue_name,
                                    ticket_price=f"£{ticket_price}" if ticket_price else "N/A",
                                    suggested_price=f"£150" if is_sold_out or is_major_venue else f"£100",
                                    email_sent=False,
                                )
                                try:
                                    with transaction.atomic():
                                        new_event.save()
                                        logger.info(f"Saved new popular event: {new_event.name} (ID: {new_event.event_id})")
                                        if not new_event.email_sent:
                                            subject = "New Popular Event Added - Price Suggester"
                                            email_message = (
                                                f"Dear Admin,\n\n"
                                                f"A new popular event has been detected in Manchester:\n\n"
                                                f"Event: {new_event.name}\n"
                                                f"Date: {new_event.date}\n"
                                                f"Venue: {new_event.venue}\n"
                                                f"Ticket Price: {new_event.ticket_price}\n"
                                                f"Suggested Room Price: {new_event.suggested_price}\n\n"
                                                f"Please review the Price Suggester page for more details.\n\n"
                                                f"Best regards,\nThe Pickarooms Team"
                                            )
                                            try:
                                                send_mail(
                                                    subject,
                                                    email_message,
                                                    settings.DEFAULT_FROM_EMAIL,
                                                    [settings.DEFAULT_FROM_EMAIL],
                                                    fail_silently=False,
                                                )
                                                logger.info(f"Sent email notification for new popular event: {new_event.name}")
                                                new_event.email_sent = True
                                                new_event.save()
                                                logger.info(f"Updated email_sent flag for event {new_event.event_id}")
                                            except Exception as e:
                                                logger.error(f"Failed to send email notification for new popular event: {str(e)}")
                                except IntegrityError:
                                    logger.warning(f"Duplicate event found during save: {new_event.name} on {new_event.date} at {new_event.venue}")
                                    continue

            # Delete events older than 30 days to free space
            cutoff_date = now() - timedelta(days=30)
            PopularEvent.objects.filter(date__lt=cutoff_date).delete()
            logger.info(f"Deleted popular events older than {cutoff_date}")