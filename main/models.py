import uuid
from django.db import models
from django.utils.timezone import now
from datetime import date, timedelta

def default_check_out_date():
    """Returns the next day with time set to 11:00 AM."""
    return date.today() + timedelta(days=1)


class Room(models.Model):
    name = models.CharField(max_length=100)  # Room name
    video_url = models.URLField()  # Link to the video instructions
    description = models.TextField(blank=True, null=True)  # Optional room description

    def __str__(self):
        return self.name


class Guest(models.Model):
    full_name = models.CharField(max_length=100, default="Guest")
    phone_number = models.CharField(max_length=15, unique=True)
    check_in_date = models.DateField(default=date.today)  # Default to the current date
    check_out_date = models.DateField(default=default_check_out_date)  # Default to the next day
    assigned_room = models.ForeignKey(Room, on_delete=models.CASCADE)
    is_archived = models.BooleanField(default=False)
    secure_token = models.CharField(max_length=10, blank=True)

    def save(self, *args, **kwargs):
        """Generate a secure token if it's not already set."""
        if not self.secure_token:
            self.secure_token = str(uuid.uuid4().hex[:10])  # Generates a unique 10-character token
        super().save(*args, **kwargs)

    def has_access(self):
        """Check if the guest's access is still valid."""
        current_time = now()
        return current_time.date() <= self.check_out_date and not self.is_archived  # Prevent access for archived guests ✅

    def __str__(self):
        return f"{self.full_name} - {self.phone_number} - {self.assigned_room.name}"
