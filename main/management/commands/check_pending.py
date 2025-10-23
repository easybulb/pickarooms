from django.core.management.base import BaseCommand
from main.models import PendingEnrichment
from django.utils import timezone


class Command(BaseCommand):
    help = 'Check PendingEnrichments in database'

    def handle(self, *args, **options):
        total = PendingEnrichment.objects.count()
        self.stdout.write(f'Total PendingEnrichments: {total}')

        if total > 0:
            all_pe = PendingEnrichment.objects.all().order_by('-email_received_at')
            self.stdout.write('\nAll PendingEnrichments:')
            for pe in all_pe:
                days_old = (timezone.now() - pe.email_received_at).days
                self.stdout.write(f'{pe.booking_reference} | {pe.check_in_date} | {pe.status} | {days_old} days old')
