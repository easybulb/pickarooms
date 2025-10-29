"""
Forcefully disable and delete deprecated poll_booking_com_emails task
"""
from django.core.management.base import BaseCommand
from django_celery_beat.models import PeriodicTask, IntervalSchedule


class Command(BaseCommand):
    help = 'Forcefully disable and delete the deprecated poll_booking_com_emails task'

    def handle(self, *args, **options):
        self.stdout.write("\n" + "="*70)
        self.stdout.write("🗑️  REMOVING DEPRECATED TASK: poll_booking_com_emails")
        self.stdout.write("="*70 + "\n")
        
        # Find all tasks with this name or task path
        deprecated_task_name = 'poll-booking-com-emails'
        deprecated_task_path = 'main.tasks.poll_booking_com_emails'
        
        # Method 1: Delete by name
        tasks_by_name = PeriodicTask.objects.filter(name=deprecated_task_name)
        
        # Method 2: Delete by task path
        tasks_by_path = PeriodicTask.objects.filter(task=deprecated_task_path)
        
        # Combine both
        all_deprecated_tasks = (tasks_by_name | tasks_by_path).distinct()
        
        if not all_deprecated_tasks.exists():
            self.stdout.write(self.style.SUCCESS("✅ No deprecated tasks found!"))
            return
        
        self.stdout.write(f"Found {all_deprecated_tasks.count()} deprecated task(s):\n")
        
        for task in all_deprecated_tasks:
            self.stdout.write(f"\n  Task Details:")
            self.stdout.write(f"    ID: {task.id}")
            self.stdout.write(f"    Name: {task.name}")
            self.stdout.write(f"    Task: {task.task}")
            self.stdout.write(f"    Enabled: {task.enabled}")
            self.stdout.write(f"    Schedule: {task.schedule}")
            
            # Get the interval schedule if it exists
            if hasattr(task, 'interval') and task.interval:
                self.stdout.write(f"    Interval: Every {task.interval.every} {task.interval.period}")
        
        # Delete all deprecated tasks
        deleted_count = all_deprecated_tasks.delete()[0]
        
        self.stdout.write(self.style.SUCCESS(f"\n✅ Successfully deleted {deleted_count} task(s)!"))
        
        # Also clean up orphaned interval schedules
        self.stdout.write("\n🧹 Cleaning up orphaned interval schedules...")
        
        # Find interval schedule for "every 300 seconds" (5 minutes)
        orphaned_intervals = IntervalSchedule.objects.filter(
            every=300,
            period='seconds'
        ).filter(
            periodictask__isnull=True  # Not used by any task
        )
        
        if orphaned_intervals.exists():
            orphaned_count = orphaned_intervals.delete()[0]
            self.stdout.write(self.style.SUCCESS(f"✅ Deleted {orphaned_count} orphaned interval schedule(s)"))
        else:
            self.stdout.write("✅ No orphaned schedules found")
        
        self.stdout.write("\n" + "="*70)
        self.stdout.write("✅ CLEANUP COMPLETE!")
        self.stdout.write("="*70 + "\n")
        
        self.stdout.write("\n⚠️  IMPORTANT: Restart Celery Beat dyno for changes to take effect:")
        self.stdout.write("   heroku restart beat --app pickarooms\n")
