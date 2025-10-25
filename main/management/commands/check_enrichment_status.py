"""
Management command to check enrichment status for specific booking references
Usage: python manage.py check_enrichment_status 6582060925 5317556059
"""
from django.core.management.base import BaseCommand
from main.models import PendingEnrichment, Reservation, EnrichmentLog
from django.utils import timezone


class Command(BaseCommand):
    help = 'Check enrichment status for specific booking references'

    def add_arguments(self, parser):
        parser.add_argument('booking_refs', nargs='+', type=str, help='Booking reference numbers to check')

    def handle(self, *args, **options):
        booking_refs = options['booking_refs']
        
        self.stdout.write(self.style.SUCCESS(f"\n{'='*80}"))
        self.stdout.write(self.style.SUCCESS("ENRICHMENT STATUS CHECK"))
        self.stdout.write(self.style.SUCCESS(f"{'='*80}\n"))

        for ref in booking_refs:
            self.stdout.write(self.style.WARNING(f"\n--- Booking Reference: {ref} ---\n"))
            
            # Check PendingEnrichment
            pending_entries = PendingEnrichment.objects.filter(booking_reference=ref).order_by('-created_at')
            
            if pending_entries.exists():
                self.stdout.write(self.style.SUCCESS(f"✅ Found {pending_entries.count()} PendingEnrichment record(s):"))
                for idx, pending in enumerate(pending_entries, 1):
                    self.stdout.write(f"\n  Record #{idx}:")
                    self.stdout.write(f"    ID: {pending.id}")
                    self.stdout.write(f"    Status: {pending.get_status_display()}")
                    self.stdout.write(f"    Check-in Date: {pending.check_in_date}")
                    self.stdout.write(f"    Email Type: {pending.get_email_type_display()}")
                    self.stdout.write(f"    Email Received: {pending.email_received_at}")
                    self.stdout.write(f"    Attempts: {pending.attempts}")
                    self.stdout.write(f"    Alert Sent: {pending.alert_sent_at or 'Not sent'}")
                    self.stdout.write(f"    Enriched Via: {pending.enriched_via or 'Not enriched'}")
                    self.stdout.write(f"    Enriched At: {pending.enriched_at or 'N/A'}")
                    
                    if pending.matched_reservation:
                        self.stdout.write(f"    ✅ Matched Reservation: #{pending.matched_reservation.id}")
                        self.stdout.write(f"       Room: {pending.matched_reservation.room.name}")
                    else:
                        self.stdout.write(f"    ❌ No matched reservation")
            else:
                self.stdout.write(self.style.ERROR(f"❌ No PendingEnrichment records found"))

            # Check Reservation
            reservations = Reservation.objects.filter(booking_reference=ref).order_by('-created_at')
            
            if reservations.exists():
                self.stdout.write(self.style.SUCCESS(f"\n✅ Found {reservations.count()} Reservation record(s):"))
                for idx, res in enumerate(reservations, 1):
                    self.stdout.write(f"\n  Reservation #{idx}:")
                    self.stdout.write(f"    ID: {res.id}")
                    self.stdout.write(f"    Room: {res.room.name}")
                    self.stdout.write(f"    Check-in: {res.check_in_date}")
                    self.stdout.write(f"    Check-out: {res.check_out_date}")
                    self.stdout.write(f"    Platform: {res.get_platform_display()}")
                    self.stdout.write(f"    Status: {res.get_status_display()}")
                    self.stdout.write(f"    Guest Name: {res.guest_name or '(Not set)'}")
                    
                    if res.guest:
                        self.stdout.write(f"    ✅ Linked Guest: {res.guest.full_name} (ID: {res.guest.id})")
                        self.stdout.write(f"       Phone: {res.guest.phone_number or 'Not provided'}")
                        self.stdout.write(f"       Email: {res.guest.email or 'Not provided'}")
                        self.stdout.write(f"       PIN: {res.guest.front_door_pin or 'Not generated'}")
                    else:
                        self.stdout.write(f"    ⏳ Not enriched yet (awaiting guest check-in)")
            else:
                self.stdout.write(self.style.ERROR(f"\n❌ No Reservation records found"))

            # Check EnrichmentLog
            logs = EnrichmentLog.objects.filter(booking_reference=ref).order_by('-timestamp')[:5]
            
            if logs.exists():
                self.stdout.write(self.style.SUCCESS(f"\n📝 Recent EnrichmentLog entries (last 5):"))
                for idx, log in enumerate(logs, 1):
                    self.stdout.write(f"\n  Log #{idx}:")
                    self.stdout.write(f"    Action: {log.get_action_display()}")
                    self.stdout.write(f"    Room: {log.room.name if log.room else 'N/A'}")
                    self.stdout.write(f"    Method: {log.method or 'N/A'}")
                    self.stdout.write(f"    Timestamp: {log.timestamp}")
                    if log.details:
                        self.stdout.write(f"    Details: {log.details}")
            else:
                self.stdout.write(self.style.WARNING(f"\n⚠️ No EnrichmentLog entries found"))

            self.stdout.write("\n")

        self.stdout.write(self.style.SUCCESS(f"\n{'='*80}"))
        self.stdout.write(self.style.SUCCESS("CHECK COMPLETE"))
        self.stdout.write(self.style.SUCCESS(f"{'='*80}\n"))
