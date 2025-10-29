"""
Check for periodic tasks in Celery Beat
"""
from django.core.management.base import BaseCommand
from django_celery_beat.models import PeriodicTask


class Command(BaseCommand):
    help = 'Check for deprecated periodic tasks in Celery Beat'

    def handle(self, *args, **options):
        # Check for all periodic tasks
        all_tasks = PeriodicTask.objects.all()
        
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"Total Periodic Tasks: {all_tasks.count()}")
        self.stdout.write(f"{'='*60}\n")
        
        for task in all_tasks:
            status = "✅ ENABLED" if task.enabled else "❌ DISABLED"
            self.stdout.write(f"\n{status}")
            self.stdout.write(f"ID: {task.id}")
            self.stdout.write(f"Name: {task.name}")
            self.stdout.write(f"Task: {task.task}")
            self.stdout.write(f"Schedule: {task.schedule}")
            self.stdout.write(f"Last Run: {task.last_run_at}")
            self.stdout.write(f"-" * 60)
        
        # Check for deprecated tasks
        deprecated_tasks = PeriodicTask.objects.filter(
            task__in=[
                'main.tasks.poll_booking_com_emails',
                'main.tasks.sync_booking_com_rooms_for_enrichment',
                'main.tasks.match_pending_to_reservation',
                'main.tasks.send_enrichment_failure_alert',
            ]
        )
        
        if deprecated_tasks.exists():
            self.stdout.write(self.style.ERROR(f"\n⚠️  Found {deprecated_tasks.count()} DEPRECATED task(s):"))
            for task in deprecated_tasks:
                self.stdout.write(self.style.ERROR(f"  - {task.name} ({task.task}) - Enabled: {task.enabled}"))
                self.stdout.write(self.style.ERROR(f"    → DELETE THIS TASK!"))
        else:
            self.stdout.write(self.style.SUCCESS(f"\n✅ No deprecated tasks found!"))
        
        self.stdout.write(f"\n")
