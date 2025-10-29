"""Management command to manually trigger Ticketmaster polling.
Usage: python manage.py poll_ticketmaster [--sync]
"""
from django.core.management.base import BaseCommand
from main.ticketmaster_tasks import poll_ticketmaster_events


class Command(BaseCommand):
    help = 'Manually trigger Ticketmaster event polling'

    def add_arguments(self, parser):
        parser.add_argument(
            '--sync',
            action='store_true',
            help='Run synchronously instead of queuing as Celery task',
        )

    def handle(self, *args, **options):
        if options['sync']:
            self.stdout.write('Running Ticketmaster polling synchronously...')
            try:
                # Import the actual task logic
                from main.models import PopularEvent
                from django.conf import settings
                from datetime import date, timedelta
                import requests
                import logging
                
                logger = logging.getLogger(__name__)
                
                # Call the function directly without Celery
                from main.ticketmaster_tasks import (
                    calculate_popularity_score,
                    calculate_suggested_price
                )
                
                logger.info("Starting Ticketmaster event polling (sync)...")
                today = date.today()
                end_date = today + timedelta(days=365)
                
                params = {
                    'apikey': settings.TICKETMASTER_CONSUMER_KEY,
                    'city': 'Manchester',
                    'countryCode': 'GB',
                    'size': 200,
                    'page': 0,
                    'sort': 'date,asc',
                    'startDateTime': f"{today.isoformat()}T00:00:00Z",
                    'endDateTime': f"{end_date.isoformat()}T23:59:59Z",
                }
                
                response = requests.get(
                    'https://app.ticketmaster.com/discovery/v2/events.json',
                    params=params,
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()
                
                events_data = data.get('_embedded', {}).get('events', [])
                created_count = 0
                updated_count = 0
                
                for event in events_data:
                    from datetime import datetime
                    event_id = event.get('id')
                    name = event.get('name', 'Unknown Event')
                    event_date_str = event.get('dates', {}).get('start', {}).get('localDate')
                    
                    if not event_date_str:
                        continue
                    
                    event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()
                    venues = event.get('_embedded', {}).get('venues', [])
                    venue_name = venues[0].get('name', 'Unknown Venue') if venues else 'Unknown Venue'
                    
                    price_ranges = event.get('priceRanges', [{}])
                    ticket_min = price_ranges[0].get('min', 0) if price_ranges else 0
                    ticket_max = price_ranges[0].get('max', 0) if price_ranges else 0
                    
                    is_sold_out = event.get('dates', {}).get('status', {}).get('code') == 'soldout'
                    images = event.get('images', [])
                    image_url = images[0].get('url') if images else None
                    
                    popularity_score = calculate_popularity_score(
                        ticket_min, ticket_max, is_sold_out, venue_name
                    )
                    
                    suggested_room_price = calculate_suggested_price(
                        popularity_score, is_sold_out, venue_name
                    )
                    
                    ticket_price_str = f"£{ticket_max}" if ticket_max else "N/A"
                    suggested_price_str = f"£{suggested_room_price}"
                    
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
                    else:
                        updated_count += 1
                
                result = f"Created: {created_count}, Updated: {updated_count}"
                self.stdout.write(self.style.SUCCESS(f'Polling complete: {result}'))
            except Exception as e:
                import traceback
                self.stdout.write(self.style.ERROR(f'Polling failed: {str(e)}'))
                self.stdout.write(traceback.format_exc())
        else:
            self.stdout.write('Triggering Ticketmaster event polling asynchronously...')

            # Trigger the task asynchronously
            result = poll_ticketmaster_events.delay()

            self.stdout.write(
                self.style.SUCCESS(f'Task triggered successfully! Task ID: {result.id}')
            )
            self.stdout.write(
                'Check worker logs to see progress: heroku logs --tail --dyno=worker -a pickarooms'
            )
