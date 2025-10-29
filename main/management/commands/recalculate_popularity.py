"""
Management command to recalculate popularity scores for all events.
Usage: python manage.py recalculate_popularity
"""
from django.core.management.base import BaseCommand
from main.models import PopularEvent
from main.ticketmaster_tasks import calculate_popularity_score, calculate_suggested_price


class Command(BaseCommand):
    help = 'Recalculate popularity scores and suggested prices for all existing events'

    def handle(self, *args, **options):
        self.stdout.write('Recalculating popularity scores...')

        events = PopularEvent.objects.all()
        updated_count = 0

        for event in events:
            # Recalculate popularity score
            popularity_score = calculate_popularity_score(
                float(event.ticket_min_price or 0),
                float(event.ticket_max_price or 0),
                event.is_sold_out,
                event.venue
            )

            # Recalculate suggested room price
            suggested_room_price = calculate_suggested_price(
                popularity_score,
                event.is_sold_out,
                event.venue
            )

            # Update if changed
            if event.popularity_score != popularity_score or event.suggested_room_price != suggested_room_price:
                event.popularity_score = popularity_score
                event.suggested_room_price = suggested_room_price
                event.suggested_price = f"£{suggested_room_price}"
                event.save()
                updated_count += 1

                # Avoid Unicode encoding issues in Windows console
                try:
                    self.stdout.write(
                        f"Updated: {event.name} at {event.venue} - Score: {popularity_score}, Price: £{suggested_room_price}"
                    )
                except UnicodeEncodeError:
                    self.stdout.write(
                        f"Updated event ID {event.id} - Score: {popularity_score}, Price: £{suggested_room_price}"
                    )

        self.stdout.write(
            self.style.SUCCESS(f'\nRecalculation complete! Updated {updated_count} events.')
        )
