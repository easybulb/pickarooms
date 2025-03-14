# main/models.py
import uuid
from django.db import models
from django.utils.timezone import now
from datetime import date, timedelta
from django.conf import settings
import pandas as pd
import json
import cloudinary.uploader
from django.contrib.auth.models import User

def default_check_out_date():
    return date.today() + timedelta(days=1)

class TTLock(models.Model):
    lock_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=100)
    is_front_door = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} (Lock ID: {self.lock_id})"

class Room(models.Model):
    name = models.CharField(max_length=100)
    ttlock = models.ForeignKey(TTLock, on_delete=models.SET_NULL, null=True, blank=True)
    video_url = models.URLField()
    description = models.TextField(blank=True, null=True)
    image = models.URLField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.image and not self.image.startswith("http"):
            uploaded_image = cloudinary.uploader.upload(self.image, folder="room_images")
            self.image = uploaded_image['secure_url']
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class Guest(models.Model):
    full_name = models.CharField(max_length=100, default="Guest")
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    reservation_number = models.CharField(max_length=15, unique=True)
    check_in_date = models.DateField(default=date.today)
    check_out_date = models.DateField(default=default_check_out_date)
    assigned_room = models.ForeignKey(Room, on_delete=models.CASCADE)
    is_archived = models.BooleanField(default=False)
    is_returning = models.BooleanField(default=False)
    secure_token = models.CharField(max_length=36, unique=True, blank=True)
    front_door_pin = models.CharField(max_length=10, blank=True, null=True)
    front_door_pin_id = models.CharField(max_length=50, blank=True, null=True)
    room_pin_id = models.CharField(max_length=50, blank=True, null=True)
    early_checkin_time = models.TimeField(null=True, blank=True)
    late_checkout_time = models.TimeField(null=True, blank=True)
    # Remove id_image from Guest, replaced by GuestIDUpload

    def save(self, *args, **kwargs):
        if not self.secure_token:
            self.secure_token = str(uuid.uuid4())
        super().save(*args, **kwargs)

    def has_access(self):
        return now().date() <= self.check_out_date and not self.is_archived

    def __str__(self):
        return f"{self.full_name} - {self.reservation_number} - {self.phone_number or 'No Phone'} - {self.assigned_room.name}"

    class Meta:
        permissions = [
            ("can_give_access", "Can give access to doors"),
            ("view_admin_dashboard", "Can view the admin dashboard and manage guests"),
            ("manage_rooms", "Can manage rooms"),
        ]

class GuestIDUpload(models.Model):
    guest = models.ForeignKey(Guest, on_delete=models.CASCADE, related_name='id_uploads')
    id_image = models.CharField(max_length=500)  # Store the Cloudinary URL as a string
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ID for {self.guest.reservation_number} uploaded on {self.uploaded_at}"

class ReviewCSVUpload(models.Model):
    file = models.FileField(upload_to="uploads/")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    data = models.JSONField(default=list)

    def save(self, *args, **kwargs):
        if self.file:
            self.file.seek(0)
            df = pd.read_csv(self.file)
            filtered_reviews = df[(df["Review score"] >= 9) & (df["Positive review"].notna()) & (df["Positive review"].str.strip() != "")]
            filtered_reviews = filtered_reviews[["Guest name", "Positive review", "Review score"]].rename(
                columns={"Guest name": "author", "Positive review": "text", "Review score": "score"}
            )
            self.data = filtered_reviews.to_dict(orient="records")
        super().save(*args, **kwargs)

class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    action = models.CharField(max_length=255)
    object_type = models.CharField(max_length=100)
    object_id = models.PositiveIntegerField()
    details = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.action} - {self.object_type} (ID: {self.object_id}) by {self.user.username if self.user else 'Anonymous'} at {self.timestamp}"

    class Meta:
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"