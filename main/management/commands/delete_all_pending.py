from django.core.management.base import BaseCommand
from main.models import PendingEnrichment
from django.utils import timezone


class Command(BaseCommand):
    help = 'Delete ALL PendingEnrichments from database (use with caution!)'

    def handle(self, *args, **options):
        total = PendingEnrichment.objects.count()
        self.stdout.write(f'Total PendingEnrichments before deletion: {total}')

        if total > 0:
            # Show what will be deleted
            self.stdout.write('\nAll pending enrichments (showing first 20):')
            for pe in PendingEnrichment.objects.all()[:20]:
                days_old = (timezone.now() - pe.email_received_at).days
                self.stdout.write(f'  {pe.booking_reference} | Check-in: {pe.check_in_date} | Received: {pe.email_received_at} | {days_old} days ago')

            if total > 20:
                self.stdout.write(f'  ... and {total - 20} more')

            # Delete ALL
            deleted_count, details = PendingEnrichment.objects.all().delete()
            self.stdout.write(f'\nDeleted: {deleted_count} records')
            self.stdout.write(f'Details: {details}')

            after_count = PendingEnrichment.objects.count()
            self.stdout.write(f'Remaining PendingEnrichments: {after_count}')
            self.stdout.write(self.style.SUCCESS('ALL pending enrichments deleted!'))
        else:
            self.stdout.write(self.style.SUCCESS('No pending enrichments to delete'))
