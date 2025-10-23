"""
One-time cleanup command to mark all old Booking.com emails as read
and delete test PendingEnrichments before starting the email polling system.
"""

from django.core.management.base import BaseCommand
from main.services.gmail_client import GmailClient
from main.models import PendingEnrichment


class Command(BaseCommand):
    help = 'Mark all old Booking.com emails as read and delete test PendingEnrichments'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('=' * 60))
        self.stdout.write(self.style.WARNING('CLEANUP: Old Emails & Test PendingEnrichments'))
        self.stdout.write(self.style.WARNING('=' * 60))
        self.stdout.write('')

        # Step 1: Delete test PendingEnrichments
        self.stdout.write('Step 1: Deleting test PendingEnrichments...')
        pending_count = PendingEnrichment.objects.count()

        if pending_count > 0:
            self.stdout.write(f'  Found {pending_count} PendingEnrichment(s)')

            # Show them
            for pe in PendingEnrichment.objects.all()[:10]:
                self.stdout.write(f'    - {pe.booking_reference} | {pe.check_in_date} | {pe.status}')

            if pending_count > 10:
                self.stdout.write(f'    ... and {pending_count - 10} more')

            # Delete
            PendingEnrichment.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f'  ✅ Deleted {pending_count} test PendingEnrichment(s)'))
        else:
            self.stdout.write(self.style.SUCCESS('  ✅ No PendingEnrichments to delete'))

        self.stdout.write('')

        # Step 2: Mark all old Booking.com emails as read
        self.stdout.write('Step 2: Marking all old Booking.com emails as read...')

        try:
            gmail = GmailClient()
            self.stdout.write('  Gmail client initialized')

            # Get all unread Booking.com emails
            emails = gmail.get_unread_booking_emails()

            if not emails:
                self.stdout.write(self.style.SUCCESS('  ✅ No unread Booking.com emails'))
            else:
                self.stdout.write(f'  Found {len(emails)} unread email(s)')

                # Show first 5
                for email in emails[:5]:
                    self.stdout.write(f'    - {email["subject"][:60]}...')

                if len(emails) > 5:
                    self.stdout.write(f'    ... and {len(emails) - 5} more')

                # Mark all as read
                for email in emails:
                    gmail.mark_as_read(email['id'])

                self.stdout.write(self.style.SUCCESS(f'  ✅ Marked {len(emails)} email(s) as read'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  ❌ Error: {str(e)}'))
            return

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('✅ CLEANUP COMPLETE!'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write('')
        self.stdout.write('The email polling system will now only process NEW emails.')
        self.stdout.write('You can safely start the Celery Beat scheduler.')
