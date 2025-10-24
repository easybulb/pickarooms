"""
NUCLEAR OPTION: Delete ALL reservations from database
Usage: heroku run python manage.py nuclear_reset_reservations
"""
from django.core.management.base import BaseCommand
from main.models import Reservation


class Command(BaseCommand):
    help = 'DELETE ALL RESERVATIONS - NUCLEAR RESET'

    def handle(self, *args, **options):
        count = Reservation.objects.count()
        self.stdout.write(f'\n⚠️  WARNING: About to delete {count} reservations\n')
        confirm = input('Type "DELETE ALL" to confirm: ')
        if confirm == 'DELETE ALL':
            Reservation.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f'\n✓ Deleted all {count} reservations\n'))
            self.stdout.write('Next: Re-sync iCal feeds, then upload XLS\n')
        else:
            self.stdout.write('Cancelled\n')
