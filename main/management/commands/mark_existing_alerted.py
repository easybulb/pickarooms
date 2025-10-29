"""
Mark all existing events as already alerted to prevent flood on deployment.
Usage: python manage.py mark_existing_alerted
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from main.models import PopularEvent


class Command(BaseCommand):
    help = 'Mark all existing events as already alerted'

    def handle(self, *args, **options):
        count = PopularEvent.objects.filter(sms_sent=False).update(
            sms_sent=True, 
            sms_sent_at=timezone.now()
        )
        
        self.stdout.write(self.style.SUCCESS(f'✅ Marked {count} events as already alerted'))
