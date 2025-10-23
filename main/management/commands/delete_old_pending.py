from django.core.management.base import BaseCommand
from main.models import PendingEnrichment
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = 'Delete old PendingEnrichments (older than 7 days) from database'

    def handle(self, *args, **options):
        total = PendingEnrichment.objects.count()
        self.stdout.write(f'Total PendingEnrichments: {total}')

        # Get cutoff date (7 days ago)
        cutoff_date = timezone.now() - timedelta(days=7)

        # Find old enrichments
        old_enrichments = PendingEnrichment.objects.filter(email_received_at__lt=cutoff_date)
        old_count = old_enrichments.count()

        self.stdout.write(f'\nEnrichments older than 7 days: {old_count}')

        if old_count > 0:
            # Show what will be deleted
            self.stdout.write('\nOld enrichments to be deleted:')
            for pe in old_enrichments[:20]:  # Show first 20
                days_old = (timezone.now() - pe.email_received_at).days
                self.stdout.write(f'  {pe.booking_reference} | Received: {pe.email_received_at} | {days_old} days old')

            if old_enrichments.count() > 20:
                self.stdout.write(f'  ... and {old_enrichments.count() - 20} more')

            # Delete them
            deleted_count, details = old_enrichments.delete()
            self.stdout.write(f'\nDeleted: {deleted_count} old records')
            self.stdout.write(f'Details: {details}')

            after_count = PendingEnrichment.objects.count()
            self.stdout.write(f'Remaining PendingEnrichments: {after_count}')
            self.stdout.write(self.style.SUCCESS('Old enrichments cleaned successfully!'))
        else:
            self.stdout.write(self.style.SUCCESS('No old enrichments to delete'))
