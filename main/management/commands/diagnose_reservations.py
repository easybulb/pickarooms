"""
Management command to diagnose reservation conflicts
Usage: python manage.py diagnose_reservations
"""

from django.core.management.base import BaseCommand
from main.models import Reservation
from collections import defaultdict
from datetime import date


class Command(BaseCommand):
    help = 'Diagnose reservation conflicts and duplicates'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('\n=== RESERVATION DIAGNOSTIC REPORT ===\n'))

        # Get today's date
        today = date.today()

        # Find duplicates (same booking_ref, room, check_in_date)
        all_reservations = Reservation.objects.filter(
            check_in_date__gte=today
        ).order_by('booking_reference', 'room', 'check_in_date', 'status')

        duplicates = defaultdict(list)
        for res in all_reservations:
            key = (res.booking_reference, res.room.name, res.check_in_date)
            duplicates[key].append(res)

        # Report duplicates
        self.stdout.write(self.style.WARNING('\n--- DUPLICATE RESERVATIONS ---'))
        duplicate_count = 0
        for key, reservations in duplicates.items():
            if len(reservations) > 1:
                duplicate_count += 1
                booking_ref, room, check_in = key
                self.stdout.write(f'\n🔴 Booking: {booking_ref} | Room: {room} | Check-in: {check_in}')
                for res in reservations:
                    status_emoji = '✅' if res.status == 'confirmed' else '❌'
                    enriched = '📝 Enriched' if res.guest else '⚠️  Unenriched'
                    self.stdout.write(
                        f'  {status_emoji} ID: {res.id} | Status: {res.status} | '
                        f'{enriched} | Guest: {res.guest_name}'
                    )

        if duplicate_count == 0:
            self.stdout.write(self.style.SUCCESS('✓ No duplicates found'))
        else:
            self.stdout.write(self.style.ERROR(f'\n⚠️  Found {duplicate_count} duplicate groups'))

        # Report today's reservations
        self.stdout.write(self.style.WARNING('\n\n--- TODAY\'S RESERVATIONS ---'))
        todays_reservations = Reservation.objects.filter(
            check_in_date=today,
            status='confirmed'
        ).select_related('room', 'guest').order_by('room__name')

        if not todays_reservations.exists():
            self.stdout.write(self.style.WARNING('No reservations for today'))
        else:
            for res in todays_reservations:
                enriched = '✅ Enriched' if res.guest else '⚠️  Unenriched'
                self.stdout.write(
                    f'{enriched} | Booking: {res.booking_reference} | '
                    f'Room: {res.room.name} | Guest: {res.guest_name}'
                )

        # Summary
        total_confirmed = Reservation.objects.filter(status='confirmed', check_in_date__gte=today).count()
        total_cancelled = Reservation.objects.filter(status='cancelled', check_in_date__gte=today).count()
        total_enriched = Reservation.objects.filter(guest__isnull=False, check_in_date__gte=today).count()

        self.stdout.write(self.style.SUCCESS('\n\n--- SUMMARY ---'))
        self.stdout.write(f'Total confirmed: {total_confirmed}')
        self.stdout.write(f'Total cancelled: {total_cancelled}')
        self.stdout.write(f'Total enriched: {total_enriched}')
        self.stdout.write(self.style.SUCCESS('\n=== END OF REPORT ===\n'))
