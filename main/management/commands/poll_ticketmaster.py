"""
Management command to manually trigger Ticketmaster polling.
Usage: python manage.py poll_ticketmaster
"""
from django.core.management.base import BaseCommand
from main.ticketmaster_tasks import poll_ticketmaster_events


class Command(BaseCommand):
    help = 'Manually trigger Ticketmaster event polling'

    def handle(self, *args, **options):
        self.stdout.write('Triggering Ticketmaster event polling...')

        # Trigger the task asynchronously
        result = poll_ticketmaster_events.delay()

        self.stdout.write(
            self.style.SUCCESS(f'Task triggered successfully! Task ID: {result.id}')
        )
        self.stdout.write(
            'Check worker logs to see progress: heroku logs --tail --dyno=worker -a pickarooms'
        )
