"""
Check recent SMS messages sent via Twilio
"""
from django.core.management.base import BaseCommand
from twilio.rest import Client
from django.conf import settings
from datetime import datetime, timedelta
import pytz


class Command(BaseCommand):
    help = 'Check recent SMS messages sent via Twilio'

    def handle(self, *args, **options):
        uk_tz = pytz.timezone('Europe/London')

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write("Recent SMS Messages from Twilio")
        self.stdout.write(f"{'='*60}\n")

        try:
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

            # Get messages from last 24 hours
            messages = client.messages.list(
                from_=settings.TWILIO_PHONE_NUMBER,
                date_sent_after=datetime.utcnow() - timedelta(days=1),
                limit=20
            )

            if not messages:
                self.stdout.write("No messages found in last 24 hours")
                return

            for msg in messages:
                sent_time_utc = msg.date_sent
                sent_time_uk = sent_time_utc.astimezone(uk_tz)

                self.stdout.write(f"\nSent: {sent_time_uk.strftime('%Y-%m-%d %H:%M:%S')} UK")
                self.stdout.write(f"To: {msg.to}")
                self.stdout.write(f"Status: {msg.status}")
                self.stdout.write(f"Body (first 200 chars):")
                self.stdout.write(f"{msg.body[:200]}")
                self.stdout.write(f"-" * 60)

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error: {str(e)}"))

        self.stdout.write(f"\n")
