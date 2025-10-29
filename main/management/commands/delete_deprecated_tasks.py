"""
Delete deprecated periodic tasks from Celery Beat
"""
from django.core.management.base import BaseCommand
from django_celery_beat.models import PeriodicTask


class Command(BaseCommand):
    help = 'Delete deprecated periodic tasks from Celery Beat'

    def handle(self, *args, **options):
        # List of deprecated task names
        deprecated_tasks = [
            'main.tasks.poll_booking_com_emails',
            'main.tasks.sync_booking_com_rooms_for_enrichment',
            'main.tasks.match_pending_to_reservation',
            'main.tasks.send_enrichment_failure_alert',
        ]
        
        # Find and delete deprecated tasks
        tasks_to_delete = PeriodicTask.objects.filter(task__in=deprecated_tasks)
        
        if not tasks_to_delete.exists():
            self.stdout.write(self.style.SUCCESS('✅ No deprecated tasks found!'))
            return
        
        self.stdout.write(f"\n⚠️  Found {tasks_to_delete.count()} deprecated task(s) to delete:\n")
        
        for task in tasks_to_delete:
            self.stdout.write(f"  - ID {task.id}: {task.name} ({task.task})")
        
        # Delete them
        deleted_count = tasks_to_delete.delete()[0]
        
        self.stdout.write(self.style.SUCCESS(f"\n✅ Successfully deleted {deleted_count} deprecated task(s)!\n"))
        
        # Also check for duplicate iCal polling tasks
        ical_tasks = PeriodicTask.objects.filter(task='main.tasks.poll_all_ical_feeds')
        
        if ical_tasks.count() > 1:
            self.stdout.write(self.style.WARNING(f"\n⚠️  Found {ical_tasks.count()} iCal polling tasks:"))
            for task in ical_tasks:
                self.stdout.write(f"  - ID {task.id}: {task.name} - Schedule: {task.schedule}")
            self.stdout.write(self.style.WARNING("\n  → You should manually delete duplicate iCal tasks via Django admin!"))
            self.stdout.write(self.style.WARNING("  → Keep only: 'poll-ical-feeds-every-15-minutes' (runs every 15 minutes)\n"))
