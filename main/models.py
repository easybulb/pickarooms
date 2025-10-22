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

class TTLockToken(models.Model):
    """Model to store TTLock API tokens"""
    access_token = models.TextField()
    refresh_token = models.TextField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "TTLock Token"
        verbose_name_plural = "TTLock Tokens"

    def __str__(self):
        return f"TTLock Token (expires: {self.expires_at})"

    @classmethod
    def get_latest(cls):
        """Get the most recent token"""
        return cls.objects.order_by('-created_at').first()

    def is_expired(self):
        """Check if token is expired"""
        from django.utils import timezone
        return timezone.now() >= self.expires_at

class Room(models.Model):
    name = models.CharField(max_length=100)
    ttlock = models.ForeignKey(TTLock, on_delete=models.SET_NULL, null=True, blank=True)
    video_url = models.URLField()
    description = models.TextField(blank=True, null=True)
    image = models.URLField(blank=True, null=True)

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
    dont_send_review_message = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.secure_token:
            self.secure_token = str(uuid.uuid4())
        is_new = self._state.adding  # True if the guest is being created
        super().save(*args, **kwargs)  # Save the guest first
        if is_new and (self.phone_number or self.email):  # Send message if either phone_number or email is provided
            self.send_welcome_message()

    def delete(self, *args, **kwargs):
        if self.phone_number or self.email:  # Send message if either phone_number or email is provided
            self.send_cancellation_message()
        super().delete(*args, **kwargs)

    def send_welcome_message(self):
        """Send a welcome email and/or SMS to the guest when added, based on available contact info."""
        checkin_url = "https://www.pickarooms.com"
        property_address = "8 Rylance Street M11 3NP, UK"
        subject = "Welcome to Pickarooms!"
        email_message = (
            f"Dear {self.full_name},\n\n"
            f"Welcome to Pickarooms! We’re excited to have you.\n\n"
            f"Check-In Date: {self.check_in_date}\n"
            f"Assigned Room: {self.assigned_room.name}\n\n"
            f"Please visit {checkin_url} to complete your check-in and obtain your unique PIN for the doors. "
            f"The webapp provides all the details you need for a seamless stay, including your check-in guide and room information.\n\n"
            f"Property address is {property_address}\n\n"
            f"Best regards,\nThe Pickarooms Team"
        )
        sms_message = (
            f"Welcome to Pickarooms! Check-in on {self.check_in_date} for {self.assigned_room.name}. "
            f"Visit {checkin_url} to get your PIN and enjoy a breeze with all stay details! "
            f"Property address is {property_address}"
        )

        # Send email if email is provided
        if self.email:
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

        # Send SMS if phone number is provided
        if self.phone_number:
            try:
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
        """Send a cancellation email and/or SMS to the guest when deleted, based on available contact info."""
        admin_email = "easybulb@gmail.com"  # Adjust as needed
        subject = "Pickarooms Reservation Cancelled"
        email_message = (
            f"Dear {self.full_name},\n\n"
            f"Your reservation at Pickarooms has been cancelled.\n"
            f"Check-In Date: {self.check_in_date}\n"
            f"Assigned Room: {self.assigned_room.name}\n\n"
            f"If this was a mistake, please contact us at {admin_email}.\n\n"
            f"Best regards,\nThe Pickarooms Team"
        )
        sms_message = (
            f"Pickarooms: Your reservation on {self.check_in_date} for {self.assigned_room.name} has been cancelled. "
            f"Contact us if needed."
        )

        # Send email if email is provided
        if self.email:
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

        # Send SMS if phone number is provided
        if self.phone_number:
            try:
                client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                message = client.messages.create(
                    body=sms_message,
                    from_=settings.TWILIO_PHONE_NUMBER,
                    to=self.phone_number
                )
                logger.info(f"Cancellation SMS sent to {self.phone_number} for guest {self.full_name}, SID: {message.sid}")
            except TwilioRestException as e:
                logger.error(f"Failed to send cancellation SMS to {self.phone_number}: {str(e)}, Status: {e.status}, Code: {e.code}, Details: {e.details}")

    def send_update_message(self):
        """Send an update email and/or SMS to the guest when their details are edited, based on available contact info."""
        checkin_url = "https://www.pickarooms.com"
        property_address = "8 Rylance Street M11 3NP, UK"
        subject = "Pickarooms Reservation Updated"
        early_checkin_display = f"{self.early_checkin_time.strftime('%I:%M %p')}" if self.early_checkin_time else "2:00 PM"
        late_checkout_display = f"{self.late_checkout_time.strftime('%I:%M %p')}" if self.late_checkout_time else "11:00 AM"
        email_message = (
            f"Dear {self.full_name},\n\n"
            f"Your reservation at Pickarooms has been updated and a new access PIN generated. Here are your updated details:\n\n"
            f"Check-In Date: {self.check_in_date} at {early_checkin_display}\n"
            f"Check-Out Date: {self.check_out_date} at {late_checkout_display}\n"
            f"Assigned Room: {self.assigned_room.name}\n\n"
            f"Please visit {checkin_url} to complete your check-in and access your room details, including your PIN. "
            f"The webapp provides all the information you need for a seamless stay.\n\n"
            f"Property address is {property_address}\n\n"
            f"Best regards,\nThe Pickarooms Team"
        )
        sms_message = (
            f"Pickarooms: Your reservation has been updated and a new access PIN genereated for you. Check-in on {self.check_in_date} at {early_checkin_display}, "
            f"Check-out on {self.check_out_date} at {late_checkout_display}, Room: {self.assigned_room.name}. "
            f"Visit {checkin_url} for details and your PIN."
        )

        # Send email if email is provided
        if self.email:
            try:
                send_mail(
                    subject,
                    email_message,
                    settings.DEFAULT_FROM_EMAIL,
                    [self.email],
                    fail_silently=False,
                )
                logger.info(f"Update email sent to {self.email} for guest {self.full_name}")
            except Exception as e:
                logger.error(f"Failed to send update email to {self.email}: {str(e)}")

        # Send SMS if phone number is provided
        if self.phone_number:
            try:
                client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                message = client.messages.create(
                    body=sms_message,
                    from_=settings.TWILIO_PHONE_NUMBER,
                    to=self.phone_number
                )
                logger.info(f"Update SMS sent to {self.phone_number} for guest {self.full_name}, SID: {message.sid}")
            except TwilioRestException as e:
                logger.error(f"Failed to send update SMS to {self.phone_number}: {str(e)}, Status: {e.status}, Code: {e.code}, Details: {e.details}")

    def send_post_stay_message(self):
        """Send a post-stay email and/or SMS to the guest after their reservation elapses, based on available contact info."""
        if self.dont_send_review_message:  # Skip if guest is blocked from receiving review messages
            logger.info(f"Skipped post-stay message for guest {self.full_name} (ID: {self.id}) as review message is blocked")
            return

        subject = "Thank You for Staying at Pickarooms!"
        email_message = (
            f"Dear {self.full_name},\n\n"
            f"Thank you for staying with us at Pickarooms! We hope you enjoyed your time at {self.assigned_room.name}.\n\n"
            f"We’d love to welcome you back for your next visit. When Booking.com prompts you, please leave us a review to share your experience—it means the world to us!\n\n"
            f"Best regards,\nThe Pickarooms Team"
        )
        sms_message = (
            f"Thank you for staying at Pickarooms! We’d love you back. Please leave a review on Booking.com when prompted!"
        )

        # Send email if email is provided
        if self.email:
            try:
                send_mail(
                    subject,
                    email_message,
                    settings.DEFAULT_FROM_EMAIL,
                    [self.email],
                    fail_silently=False,
                )
                logger.info(f"Post-stay email sent to {self.email} for guest {self.full_name}")
            except Exception as e:
                logger.error(f"Failed to send post-stay email to {self.email}: {str(e)}")

        # Send SMS if phone number is provided
        if self.phone_number:
            try:
                client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                message = client.messages.create(
                    body=sms_message,
                    from_=settings.TWILIO_PHONE_NUMBER,
                    to=self.phone_number
                )
                logger.info(f"Post-stay SMS sent to {self.phone_number} for guest {self.full_name}, SID: {message.sid}")
            except TwilioRestException as e:
                logger.error(f"Failed to send post-stay SMS to {self.phone_number}: {str(e)}, Status: {e.status}, Code: {e.code}, Details: {e.details}")

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

class RoomICalConfig(models.Model):
    """Configuration for iCal feed polling per room - supports both Booking.com and Airbnb"""
    room = models.OneToOneField(Room, on_delete=models.CASCADE, related_name='ical_config')

    # Booking.com configuration
    booking_ical_url = models.URLField(max_length=500, blank=True, null=True, help_text="Booking.com iCal feed URL")
    booking_active = models.BooleanField(default=False, help_text="Enable Booking.com polling")
    booking_last_synced = models.DateTimeField(null=True, blank=True, help_text="Last Booking.com sync timestamp")
    booking_last_sync_status = models.CharField(max_length=255, blank=True, help_text="Booking.com last sync status")

    # Airbnb configuration
    airbnb_ical_url = models.URLField(max_length=500, blank=True, null=True, help_text="Airbnb iCal feed URL")
    airbnb_active = models.BooleanField(default=False, help_text="Enable Airbnb polling")
    airbnb_last_synced = models.DateTimeField(null=True, blank=True, help_text="Last Airbnb sync timestamp")
    airbnb_last_sync_status = models.CharField(max_length=255, blank=True, help_text="Airbnb last sync status")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Room iCal Configuration"
        verbose_name_plural = "Room iCal Configurations"

    def __str__(self):
        active_platforms = []
        if self.booking_active:
            active_platforms.append('Booking.com')
        if self.airbnb_active:
            active_platforms.append('Airbnb')
        status = ', '.join(active_platforms) if active_platforms else 'Inactive'
        return f"iCal Config for {self.room.name} ({status})"

class Reservation(models.Model):
    """iCal booking reservation - synced from external platforms"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ]

    PLATFORM_CHOICES = [
        ('booking', 'Booking.com'),
        ('airbnb', 'Airbnb'),
    ]

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='reservations')
    ical_uid = models.CharField(max_length=500, unique=True, help_text="Unique identifier from iCal event (UID)")
    booking_reference = models.CharField(max_length=50, blank=True, help_text="Extracted booking reference (10-digit number)")
    guest_name = models.CharField(max_length=200, help_text="Guest name from iCal SUMMARY")
    check_in_date = models.DateField()
    check_out_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='confirmed')
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES, default='booking', help_text="Source platform (Booking.com or Airbnb)")
    guest = models.OneToOneField(Guest, on_delete=models.SET_NULL, null=True, blank=True, related_name='reservation', help_text="Linked Guest record (created after enrichment)")
    raw_ical_data = models.TextField(blank=True, help_text="Raw iCal event data for debugging")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Reservation"
        verbose_name_plural = "Reservations"
        ordering = ['-check_in_date']
        indexes = [
            models.Index(fields=['ical_uid']),
            models.Index(fields=['booking_reference']),
            models.Index(fields=['check_in_date']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        guest_info = f"{self.guest_name} ({self.booking_reference})" if self.booking_reference else self.guest_name
        platform_display = dict(self.PLATFORM_CHOICES).get(self.platform, self.platform)
        return f"[{platform_display}] {guest_info} - {self.room.name} ({self.check_in_date} to {self.check_out_date})"

    def is_enriched(self):
        """Check if reservation has been enriched with full guest details"""
        return self.guest is not None