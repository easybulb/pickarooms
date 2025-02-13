import uuid
from django.db import models
from django.utils.timezone import now
from datetime import date, timedelta
from django.conf import settings
import pandas as pd
import json


# Import Cloudinary only if available (for production)
if not settings.DEBUG:
    from cloudinary.models import CloudinaryField


def default_check_out_date():
    """Returns the next day with time set to 11:00 AM."""
    return date.today() + timedelta(days=1)


class Room(models.Model):
    name = models.CharField(max_length=100)  # Room name
    access_pin = models.CharField(max_length=10, blank=True, null=True)  # House and Room Access PIN
    video_url = models.URLField()  # Link to the video instructions
    description = models.TextField(blank=True, null=True)  # Optional room description

    # Conditional Image Field for Local vs. Cloudinary Storage
    if settings.DEBUG:
        image = models.ImageField(upload_to='room_images/', default='default_room.jpg')  # Local storage
    else:
        image = CloudinaryField('image', default='default_room.jpg')  # Cloudinary storage in production

    def __str__(self):
        return self.name
    


class Guest(models.Model):
    full_name = models.CharField(max_length=100, default="Guest")
    phone_number = models.CharField(max_length=15, blank=True, null=True)  # ✅ Make optional
    reservation_number = models.CharField(max_length=15, unique=True)  # ✅ Required & must be unique
    check_in_date = models.DateField(default=date.today)
    check_out_date = models.DateField(default=default_check_out_date)
    assigned_room = models.ForeignKey(Room, on_delete=models.CASCADE)
    is_archived = models.BooleanField(default=False)
    is_returning = models.BooleanField(default=False)  # ✅ Track returning guests
    secure_token = models.CharField(max_length=10, unique=True, blank=True)

    def save(self, *args, **kwargs):
        """Ensure secure token is always generated"""
        if not self.secure_token:
            self.secure_token = str(uuid.uuid4().hex[:10])
        super().save(*args, **kwargs)

    def has_access(self):
        """Check if the guest's access is still valid."""
        return now().date() <= self.check_out_date and not self.is_archived  

    def __str__(self):
        return f"{self.full_name} - {self.reservation_number} - {self.phone_number or 'No Phone'} - {self.assigned_room.name}"





class ReviewCSVUpload(models.Model):
    file = models.FileField(upload_to="uploads/")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    data = models.JSONField(default=dict)  # Store reviews as JSON

    def save(self, *args, **kwargs):
        # Read CSV and store it as JSON
        if self.file:
            self.file.seek(0)  # Ensure file is at the beginning
            df = pd.read_csv(self.file)

            # Filter reviews and convert to JSON
            filtered_reviews = df[(df["Review score"] >= 9) & (df["Positive review"].notna()) & (df["Positive review"].str.strip() != "")]
            filtered_reviews = filtered_reviews[["Guest name", "Positive review", "Review score"]].rename(
                columns={"Guest name": "author", "Positive review": "text", "Review score": "score"}
            )

            self.data = filtered_reviews.to_dict(orient="records")

        super().save(*args, **kwargs)

