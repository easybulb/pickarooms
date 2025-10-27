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
from django.core.exceptions import ValidationError

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
    car_registration = models.CharField(max_length=20, null=True, blank=True, help_text="Guest's car registration number (optional)")

    def is_ical_guest(self):
        """Check if this guest is from iCal integration (has linked reservation)"""
        try:
            return self.reservations.exists()
        except Exception:
            return False

    def _get_message_context(self):
        """Build context dict for message template rendering"""
        # For multi-room bookings, get platform from first reservation
        first_reservation = self.reservations.first()
        platform_name = 'Booking.com' if (first_reservation and first_reservation.platform == 'booking') else 'Airbnb'
        
        return {
            'guest_name': self.full_name,
            'room_name': self.assigned_room.name,
            'check_in_date': self.check_in_date.strftime('%Y-%m-%d'),
            'check_out_date': self.check_out_date.strftime('%Y-%m-%d'),
            'reservation_number': self.reservation_number,
            'pin': self.front_door_pin or 'N/A',
            'room_detail_url': 'https://www.pickarooms.com',
            'platform_name': platform_name,
        }

    def _get_template_messages(self, message_type_prefix):
        """
        Generic method to load message templates for iCal guests
        Returns (subject, email_message, sms_message) tuple
        Falls back to None if templates not found
        """
        try:
            from main.models import MessageTemplate
            email_template = MessageTemplate.objects.filter(message_type=f'ical_{message_type_prefix}_email', is_active=True).first()
            sms_template = MessageTemplate.objects.filter(message_type=f'ical_{message_type_prefix}_sms', is_active=True).first()

            context = self._get_message_context()
            subject = email_template.subject if email_template else None
            email_message = email_template.render(**context) if email_template else None
            sms_message = sms_template.render(**context) if sms_template else None
            return (subject, email_message, sms_message)
        except Exception as e:
            logger.error(f"Failed to load {message_type_prefix} templates: {e}")
            return (None, None, None)

    def save(self, *args, **kwargs):
        if not self.secure_token:
            self.secure_token = str(uuid.uuid4())

        # Validate and normalize phone number if provided
        if self.phone_number:
            from main.phone_utils import validate_phone_number
            is_valid, error_msg = validate_phone_number(self.phone_number)
            if not is_valid:
                logger.warning(f"Invalid phone number for guest {self.reservation_number}: {error_msg}")
                # Store as-is but log the warning - validation should happen at form level
                # We don't want to block saving here in case admin manually enters data

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
        if self.is_ical_guest():
            # iCal guest - use editable MessageTemplates
            subject, email_message, sms_message = self._get_template_messages('welcome')
            if not subject:
                subject = "Welcome to Pickarooms!"
        else:
            # Manual guest - use legacy hardcoded messages (backward compatibility)
            checkin_url = "https://www.pickarooms.com"
            property_address = "8 Rylance Street M11 3NP, UK"
            subject = "Welcome to Pickarooms!"
            email_message = (
                f"Dear {self.full_name},\n\n"
                f"Welcome to Pickarooms! We're excited to have you.\n\n"
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

        # Send email if email is provided and message content exists
        if self.email and email_message:
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

        # Send SMS if phone number is provided and message content exists
        if self.phone_number and sms_message:
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
        if self.is_ical_guest():
            # iCal guest - use editable MessageTemplates
            subject, email_message, sms_message = self._get_template_messages('cancellation')
            if not subject:
                subject = "Pickarooms Reservation Cancelled"
        else:
            # Manual guest - use legacy hardcoded messages
            admin_email = "easybulb@gmail.com"
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

        # Send email if email is provided and message content exists
        if self.email and email_message:
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

        # Send SMS if phone number is provided and message content exists
        if self.phone_number and sms_message:
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
        if self.is_ical_guest():
            # iCal guest - use editable MessageTemplates
            subject, email_message, sms_message = self._get_template_messages('update')
            if not subject:
                subject = "Pickarooms Reservation Updated"
        else:
            # Manual guest - use legacy hardcoded messages
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

        # Send email if email is provided and message content exists
        if self.email and email_message:
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

        # Send SMS if phone number is provided and message content exists
        if self.phone_number and sms_message:
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
        """Send a platform-specific post-stay email and/or SMS to the guest after checkout."""
        if self.dont_send_review_message:
            logger.info(f"Skipped post-stay message for guest {self.full_name} (ID: {self.id}) as review message is blocked")
            return

        if self.is_ical_guest():
            # iCal guest - use editable MessageTemplates (platform-specific via {platform_name} variable)
            subject, email_message, sms_message = self._get_template_messages('post_stay')
            if not subject:
                subject = "Thank You for Staying at Pickarooms!"
        else:
            # Manual guest - use legacy hardcoded messages
            platform_name = "Booking.com"  # Default for manual guests
            subject = "Thank You for Staying at Pickarooms!"
            email_message = (
                f"Dear {self.full_name},\n\n"
                f"Thank you for staying with us at Pickarooms! We hope you enjoyed your time at {self.assigned_room.name}.\n\n"
                f"We'd love to welcome you back for your next visit. When {platform_name} prompts you, please leave us a review to share your experience—it means the world to us!\n\n"
                f"Best regards,\nThe Pickarooms Team"
            )
            sms_message = (
                f"Thank you for staying at Pickarooms! We'd love you back. Please leave a review on {platform_name} when prompted!"
            )

        # Send email if email is provided and message content exists
        if self.email and email_message:
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

        # Send SMS if phone number is provided and message content exists
        if self.phone_number and sms_message:
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
    guest = models.ForeignKey(Guest, on_delete=models.SET_NULL, null=True, blank=True, related_name='reservations', help_text="Linked Guest record (created after enrichment)")

    # Admin-configurable check-in/out times (set before guest checks in)
    early_checkin_time = models.TimeField(null=True, blank=True, help_text="Early check-in time (e.g., 12:00). If not set, defaults to 2:00 PM.")
    late_checkout_time = models.TimeField(null=True, blank=True, help_text="Late check-out time (e.g., 14:00). If not set, defaults to 11:00 AM.")

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


class MessageTemplate(models.Model):
    """
    Editable message templates for guest communications
    Supports variable substitution like {guest_name}, {pin}, {room_name}, etc.
    """
    MESSAGE_TYPES = [
        ('ical_welcome_email', 'iCal Welcome Email'),
        ('ical_welcome_sms', 'iCal Welcome SMS'),
        ('ical_update_email', 'iCal Update Email'),
        ('ical_update_sms', 'iCal Update SMS'),
        ('ical_cancellation_email', 'iCal Cancellation Email'),
        ('ical_cancellation_sms', 'iCal Cancellation SMS'),
        ('ical_post_stay_email', 'iCal Post-Stay Email'),
        ('ical_post_stay_sms', 'iCal Post-Stay SMS'),
    ]

    message_type = models.CharField(max_length=50, choices=MESSAGE_TYPES, unique=True, help_text="Type of message")
    subject = models.CharField(max_length=200, blank=True, help_text="Email subject (leave blank for SMS)")
    content = models.TextField(help_text="Message content with variables like {guest_name}, {pin}, {room_name}")
    is_active = models.BooleanField(default=True, help_text="Enable/disable this message without deleting it")
    last_edited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, help_text="User who last edited")
    last_edited_at = models.DateTimeField(auto_now=True, help_text="Last edit timestamp")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Message Template"
        verbose_name_plural = "Message Templates"
        ordering = ['message_type']

    def __str__(self):
        return f"{self.get_message_type_display()} {'(Active)' if self.is_active else '(Inactive)'}"

    def get_available_variables(self):
        """Return list of available variables for this message type"""
        common_vars = [
            '{guest_name}', '{room_name}', '{check_in_date}', '{check_out_date}',
            '{reservation_number}', '{room_detail_url}'
        ]

        if 'welcome' in self.message_type or 'update' in self.message_type:
            return common_vars + ['{pin}']
        elif 'post_stay' in self.message_type:
            return common_vars + ['{platform_name}']
        else:
            return common_vars

    def render(self, **context):
        """
        Render template with provided context variables
        Example: template.render(guest_name="John", pin="1234")
        """
        try:
            return self.content.format(**context)
        except KeyError as e:
            logger.error(f"Missing variable in template {self.message_type}: {e}")
            return self.content  # Return unformatted if variable missing

    def get_character_count(self):
        """Get character count (useful for SMS messages)"""
        return len(self.content)


class PendingEnrichment(models.Model):
    """
    Tracks booking references extracted from Booking.com emails
    awaiting matching with iCal reservations
    """
    STATUS_CHOICES = [
        ('pending', 'Pending Match'),
        ('matched', 'Matched'),
        ('failed_awaiting_manual', 'Failed - Awaiting Manual Assignment'),
        ('manually_assigned', 'Manually Assigned'),
        ('cancelled', 'Cancelled'),
    ]

    EMAIL_TYPE_CHOICES = [
        ('new', 'New Booking'),
        ('modification', 'Modification'),
        ('cancellation', 'Cancellation'),
    ]

    ENRICHMENT_METHOD_CHOICES = [
        ('email_ical_auto', 'Email + iCal Auto-Match'),
        ('sms_reply', 'SMS Reply'),
        ('email_reply', 'Email Reply'),
        ('csv_upload', 'CSV Upload'),
        ('admin_manual', 'Admin Manual'),
    ]

    platform = models.CharField(max_length=20, default='booking', choices=[('booking', 'Booking.com')])
    booking_reference = models.CharField(max_length=50, db_index=True)
    check_in_date = models.DateField(db_index=True)
    email_type = models.CharField(max_length=20, choices=EMAIL_TYPE_CHOICES, default='new')
    email_received_at = models.DateTimeField(auto_now_add=True)
    attempts = models.IntegerField(default=0)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending', db_index=True)

    # Matching results
    matched_reservation = models.ForeignKey('Reservation', on_delete=models.SET_NULL, null=True, blank=True, related_name='pending_enrichments')
    room_matched = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True, blank=True)

    # Alert tracking
    alert_sent_at = models.DateTimeField(null=True, blank=True)
    alert_sms_sid = models.CharField(max_length=100, blank=True, help_text="Twilio message SID")

    # Manual assignment tracking
    manual_assignment_method = models.CharField(max_length=20, null=True, blank=True, choices=[
        ('sms_reply', 'SMS Reply'),
        ('email_reply', 'Email Reply'),
        ('admin_ui', 'Admin UI'),
    ])

    # Enrichment tracking
    enriched_via = models.CharField(max_length=20, null=True, blank=True, choices=ENRICHMENT_METHOD_CHOICES)
    enriched_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pending Enrichment"
        verbose_name_plural = "Pending Enrichments"
        ordering = ['-email_received_at']
        unique_together = [('booking_reference', 'platform')]
        indexes = [
            models.Index(fields=['booking_reference']),
            models.Index(fields=['check_in_date']),
            models.Index(fields=['status']),
            models.Index(fields=['-email_received_at']),
        ]

    def __str__(self):
        return f"{self.booking_reference} - {self.check_in_date} ({self.get_status_display()})"


class EnrichmentLog(models.Model):
    """Audit trail for all enrichment actions (iCal-driven flow)"""
    ACTION_CHOICES = [
        # iCal-driven workflow
        ('ical_new_booking', 'iCal: New Booking Detected'),
        ('collision_detected', 'Collision: Multiple Same-Day Bookings'),
        ('email_search_started', 'Email Search Started'),
        ('email_found_matched', 'Email Found and Matched'),
        ('email_found_multi_room', 'Email Found - Multi-Room Detected'),
        ('email_not_found_alerted', 'Email Not Found - SMS Sent'),
        
        # Manual enrichment methods
        ('manual_enrichment_sms', 'Manual Enrichment via SMS'),
        ('multi_enrichment_sms', 'Multi-Booking Enrichment via SMS'),
        ('multi_room_confirmed', 'Multi-Room Booking Confirmed'),
        ('sms_reply_assigned', 'SMS Reply Assigned'),  # Legacy
        ('correction_applied', 'Correction Applied via SMS'),
        ('manual_admin_assigned', 'Manual Admin Assigned'),
        
        # Command tracking
        ('check_command_received', 'Check Command Received'),
        ('cancel_command_received', 'Cancel Command Received'),
        ('guide_command_received', 'Guide Command Received'),
        
        # Legacy actions (keep for backward compatibility)
        ('email_parsed', 'Email Parsed'),
        ('ical_synced', 'iCal Synced'),
        ('auto_matched_single', 'Auto-Matched Single Room'),
        ('auto_matched_multi_room', 'Auto-Matched Multi-Room'),
        ('xls_enriched_single', 'XLS Enriched Single Room'),
        ('xls_enriched_multi', 'XLS Enriched Multi-Room'),
        ('email_reply_assigned', 'Email Reply Assigned'),
        
        # Cancellation
        ('cancellation_detected', 'iCal: Booking Cancelled'),
    ]

    pending_enrichment = models.ForeignKey(PendingEnrichment, null=True, blank=True, on_delete=models.SET_NULL, related_name='logs')
    reservation = models.ForeignKey('Reservation', null=True, blank=True, on_delete=models.SET_NULL, related_name='enrichment_logs')

    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    booking_reference = models.CharField(max_length=50, db_index=True)
    room = models.ForeignKey(Room, null=True, blank=True, on_delete=models.SET_NULL)
    method = models.CharField(max_length=50, blank=True)
    details = models.JSONField(default=dict, help_text="Additional context (room_count, rooms list, etc.)")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Enrichment Log"
        verbose_name_plural = "Enrichment Logs"
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['booking_reference']),
            models.Index(fields=['-timestamp']),
        ]

    def __str__(self):
        return f"{self.booking_reference} - {self.get_action_display()} at {self.timestamp}"


class CSVEnrichmentLog(models.Model):
    """Tracks CSV/XLS upload enrichment sessions"""
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    file_name = models.CharField(max_length=255)

    # Results
    total_rows = models.IntegerField(default=0)
    single_room_count = models.IntegerField(default=0)
    multi_room_count = models.IntegerField(default=0)
    created_count = models.IntegerField(default=0)
    updated_count = models.IntegerField(default=0)
    discrepancies_count = models.IntegerField(default=0)
    errors_count = models.IntegerField(default=0)

    # Summary table (JSON field)
    enrichment_summary = models.JSONField(default=dict, help_text="Detailed results with enriched bookings and discrepancies")

    class Meta:
        verbose_name = "CSV Enrichment Log"
        verbose_name_plural = "CSV Enrichment Logs"
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"XLS Upload {self.file_name} at {self.uploaded_at}"


class CheckInAnalytics(models.Model):
    """Track check-in flow analytics to identify drop-off points"""
    session_id = models.CharField(max_length=100, help_text="Django session key")
    booking_reference = models.CharField(max_length=20, null=True, blank=True, help_text="Booking reference if entered")
    step_reached = models.IntegerField(help_text="Last step reached (1-4)")
    completed = models.BooleanField(default=False, help_text="Did guest complete full check-in?")
    device_type = models.CharField(max_length=20, help_text="mobile or desktop")
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Check-In Analytics"
        verbose_name_plural = "Check-In Analytics"
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['session_id']),
            models.Index(fields=['booking_reference']),
            models.Index(fields=['-started_at']),
        ]

    def __str__(self):
        status = "Completed" if self.completed else f"Dropped at Step {self.step_reached}"
        return f"{self.booking_reference or 'Unknown'} - {status} ({self.device_type})"
