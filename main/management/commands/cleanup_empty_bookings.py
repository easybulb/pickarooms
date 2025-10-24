"""
Management command to clean up reservations with empty booking references
These are typically created by iCal before the actual booking details are available
Usage: heroku run python manage.py cleanup_empty_bookings
"""

from django.core.management.base import BaseCommand
from main.models import Reservation
from datetime import date


class Command(BaseCommand):
    help = 'Delete confirmed reservations with empty booking references (iCal placeholders)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        self.stdout.write(self.style.SUCCESS('\n=== CLEANUP EMPTY BOOKING REFERENCES ===\n'))

        # Find confirmed reservations with empty/null booking references
        # Only look at future reservations (today onwards)
        today = date.today()
        
        empty_bookings = Reservation.objects.filter(
            booking_reference__in=['', None],
            status='confirmed',
            check_in_date__gte=today,
            guest__isnull=True  # Not enriched (no linked guest)
        ).select_related('room').order_by('check_in_date', 'room__name')

        count = empty_bookings.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS('✓ No empty booking references found'))
            return

        self.stdout.write(self.style.WARNING(f'Found {count} reservation(s) with empty booking references:\n'))

        for res in empty_bookings:
            self.stdout.write(
                f'  ID: {res.id} | Room: {res.room.name} | '
                f'Check-in: {res.check_in_date} | Guest: {res.guest_name} | '
                f'Platform: {res.platform} | ical_uid: {res.ical_uid[:50]}...'
            )

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[DRY RUN] No changes made. Run without --dry-run to delete.'))
        else:
            confirm = input(f'\nDelete these {count} reservation(s)? (yes/no): ')
            if confirm.lower() == 'yes':
                deleted_count = empty_bookings.delete()[0]
                self.stdout.write(self.style.SUCCESS(f'\n✓ Deleted {deleted_count} reservation(s)'))
                self.stdout.write(self.style.SUCCESS('\nNext steps:'))
                self.stdout.write('1. Upload your XLS file again')
                self.stdout.write('2. The reservations will be created with proper booking references')
                self.stdout.write('3. Check Today\'s Guests - they should now show with booking refs')
            else:
                self.stdout.write(self.style.WARNING('\nCancelled. No changes made.'))

        self.stdout.write(self.style.SUCCESS('\n=== END OF CLEANUP ===\n'))
