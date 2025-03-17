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
from django.core.mail import send_mail
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
import logging

logger = logging.getLogger('main')

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
    email = models.EmailField(blank=True, null=True)  # Optional email field
    phone_number = models.CharField(max_length=15, blank=True, null=True)  # Optional phone number
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
        is_new = self._state.adding  # True if the guest is being created
        super().save(*args, **kwargs)  # Save the guest first
        if is_new and self.phone_number and self.email:  # Only send if both phone and email are provided
            self.send_welcome_message()

    def delete(self, *args, **kwargs):
        if self.phone_number and self.email:  # Only send if both phone and email are provided
            self.send_cancellation_message()
        super().delete(*args, **kwargs)

    def send_welcome_message(self):
        """Send a welcome email and SMS to the guest when added."""
        checkin_url = "https://www.pickarooms.com/checkin/"  # Adjust URL as needed
        subject = "Welcome to Pickarooms!"
        email_message = (
            f"Dear {self.full_name},\n\n"
            f"Welcome to Pickarooms! Your check-in details:\n"
            f"Reservation Number: {self.reservation_number}\n"
            f"Check-In Date: {self.check_in_date}\n"
            f"Assigned Room: {self.assigned_room.name}\n\n"
            f"Please visit {checkin_url} to complete your check-in.\n\n"
            f"Best regards,\nThe Pickarooms Team"
        )
        sms_message = (
            f"Welcome to Pickarooms! Check-in: Reservation #{self.reservation_number}, "
            f"Date: {self.check_in_date}, Room: {self.assigned_room.name}. Visit {checkin_url}"
        )

        # Send email
        try:
            send_mail(
                subject,
                email_message,
                settings.DEFAULT_FROM_EMAIL,
                [self.email],
                fail_silently=False,
            )
            logger.info(f"Welcome email sent to {self.email} for guest {self.full_name}")
        except Exception as e:
            logger.error(f"Failed to send welcome email to {self.email}: {str(e)}")

        # Send SMS via Twilio with detailed logging
        try:
            logger.info(f"Attempting to send SMS to {self.phone_number} with Twilio credentials: SID={settings.TWILIO_ACCOUNT_SID}, From={settings.TWILIO_PHONE_NUMBER}")
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            message = client.messages.create(
                body=sms_message,
                from_=settings.TWILIO_PHONE_NUMBER,
                to=self.phone_number
            )
            logger.info(f"Welcome SMS sent to {self.phone_number} for guest {self.full_name}, SID: {message.sid}")
        except TwilioRestException as e:
            logger.error(f"Failed to send welcome SMS to {self.phone_number}: {str(e)}, Status: {e.status}, Code: {e.code}, Details: {e.details}")

    def send_cancellation_message(self):
        """Send a cancellation email and SMS to the guest when deleted."""
        admin_email = "easybulb@gmail.com"  # Adjust as needed
        subject = "Pickarooms Reservation Cancelled"
        email_message = (
            f"Dear {self.full_name},\n\n"
            f"Your reservation at Pickarooms has been cancelled.\n"
            f"Reservation Number: {self.reservation_number}\n"
            f"Check-In Date: {self.check_in_date}\n"
            f"Assigned Room: {self.assigned_room.name}\n\n"
            f"If this was a mistake, please contact us at {admin_email}.\n\n"
            f"Best regards,\nThe Pickarooms Team"
        )
        sms_message = (
            f"Pickarooms: Your reservation (#{self.reservation_number}) "
            f"on {self.check_in_date} for {self.assigned_room.name} has been cancelled. "
            f"Contact us if needed."
        )

        # Send email
        try:
            send_mail(
                subject,
                email_message,
                settings.DEFAULT_FROM_EMAIL,
                [self.email],
                fail_silently=False,
            )
            logger.info(f"Cancellation email sent to {self.email} for guest {self.full_name}")
        except Exception as e:
            logger.error(f"Failed to send cancellation email to {self.email}: {str(e)}")

        # Send SMS via Twilio with detailed logging
        try:
            logger.info(f"Attempting to send SMS to {self.phone_number} with Twilio credentials: SID={settings.TWILIO_ACCOUNT_SID}, From={settings.TWILIO_PHONE_NUMBER}")
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            message = client.messages.create(
                body=sms_message,
                from_=settings.TWILIO_PHONE_NUMBER,
                to=self.phone_number
            )
            logger.info(f"Cancellation SMS sent to {self.phone_number} for guest {self.full_name}, SID: {message.sid}")
        except TwilioRestException as e:
            logger.error(f"Failed to send cancellation SMS to {self.phone_number}: {str(e)}, Status: {e.status}, Code: {e.code}, Details: {e.details}")

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

class PopularEvent(models.Model):
    event_id = models.CharField(max_length=100, unique=True)  # Ticketmaster event ID
    name = models.CharField(max_length=255)
    date = models.DateField()
    venue = models.CharField(max_length=255)
    ticket_price = models.CharField(max_length=50)
    suggested_price = models.CharField(max_length=50)
    email_sent = models.BooleanField(default=False)  # Track if email has been sent
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('name', 'date', 'venue')  # Ensure uniqueness across name, date, and venue

    def __str__(self):
        return f"{self.name} at {self.venue} on {self.date}"