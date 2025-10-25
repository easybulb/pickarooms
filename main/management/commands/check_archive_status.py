"""
Management command to check guest archiving status
Usage: python manage.py check_archive_status
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from main.models import Guest
from datetime import date, time
import pytz


class Command(BaseCommand):
    help = 'Check guest archiving status and diagnose issues'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('GUEST ARCHIVING STATUS CHECK'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write('')

        # 1. Count archived guests
        archived_count = Guest.objects.filter(is_archived=True).count()
        self.stdout.write(f"✅ Archived guests in database: {archived_count}")

        if archived_count > 0:
            self.stdout.write(self.style.SUCCESS(f"   → Archive is working! {archived_count} guests archived"))
            
            # Show recent 5
            recent = Guest.objects.filter(is_archived=True).order_by('-check_out_date')[:5]
            self.stdout.write("\n   Recent archived guests:")
            for g in recent:
                self.stdout.write(f"   - {g.full_name} | {g.reservation_number} | Checked out: {g.check_out_date}")
        else:
            self.stdout.write(self.style.WARNING("   → No archived guests yet"))

        self.stdout.write('')

        # 2. Guests that should be archived
        today = date.today()
        uk_timezone = pytz.timezone("Europe/London")
        now_time = timezone.now().astimezone(uk_timezone)

        should_be_archived = Guest.objects.filter(
            is_archived=False,
            check_out_date__lte=today
        ).select_related('assigned_room')

        self.stdout.write(f"⏳ Guests awaiting archive: {should_be_archived.count()}")

        if should_be_archived.exists():
            self.stdout.write(self.style.WARNING("   → These guests should be archived:"))
            for guest in should_be_archived[:10]:  # Show first 10
                check_out_time_val = guest.late_checkout_time if guest.late_checkout_time else time(11, 0)
                check_out_datetime = uk_timezone.localize(
                    timezone.datetime.combine(guest.check_out_date, check_out_time_val)
                )
                
                if now_time > check_out_datetime:
                    status = "❌ OVERDUE"
                else:
                    status = f"⏰ At {check_out_time_val.strftime('%H:%M')}"
                
                self.stdout.write(
                    f"   - {guest.full_name} | {guest.reservation_number} | "
                    f"Checkout: {guest.check_out_date} | {status}"
                )
        else:
            self.stdout.write(self.style.SUCCESS("   → All guests properly archived!"))

        self.stdout.write('')

        # 3. Total active guests
        active_count = Guest.objects.filter(is_archived=False).count()
        self.stdout.write(f"👥 Active guests (not archived): {active_count}")

        self.stdout.write('')

        # 4. Diagnosis
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('DIAGNOSIS'))
        self.stdout.write(self.style.SUCCESS('=' * 60))

        if archived_count == 0 and should_be_archived.count() > 0:
            self.stdout.write(self.style.ERROR("❌ ISSUE DETECTED: Guests need archiving but none archived"))
            self.stdout.write('')
            self.stdout.write("Possible causes:")
            self.stdout.write("1. Celery Beat not running (schedule not executing)")
            self.stdout.write("2. Archive task has errors (check logs)")
            self.stdout.write("3. Fresh deployment (no checkouts yet)")
            self.stdout.write('')
            self.stdout.write("Quick fixes:")
            self.stdout.write("- Check Celery Beat: heroku ps --app pickarooms-495ab160017c")
            self.stdout.write("- Scale Beat: heroku ps:scale beat=1 --app pickarooms-495ab160017c")
            self.stdout.write("- Manual trigger: python manage.py shell")
            self.stdout.write("  >>> from main.tasks import archive_past_guests")
            self.stdout.write("  >>> archive_past_guests()")

        elif archived_count > 0:
            self.stdout.write(self.style.SUCCESS("✅ ARCHIVING IS WORKING"))
            self.stdout.write('')
            self.stdout.write(f"→ {archived_count} guests archived successfully")
            self.stdout.write("→ Check past_guests page: /admin-page/past-guests/")
            
            if should_be_archived.count() > 0:
                self.stdout.write('')
                self.stdout.write(self.style.WARNING(f"⏳ {should_be_archived.count()} guests awaiting next archive run"))
                self.stdout.write("   (Archive runs at 12:15 PM, 3:00 PM, 11:00 PM UK time)")

        else:
            self.stdout.write(self.style.SUCCESS("ℹ️  NO ISSUES DETECTED"))
            self.stdout.write('')
            self.stdout.write("→ No guests have checked out yet")
            self.stdout.write("→ Archive task will run when guests check out")

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
