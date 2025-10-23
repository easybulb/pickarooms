"""
Celery tasks for PickARooms iCal integration
"""
from celery import shared_task
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0)
def poll_all_ical_feeds(self):
    """
    Main scheduled task - runs every 15 minutes (reduced from 10 min)
    Fetches all RoomICalConfig and syncs active platforms (Booking.com and/or Airbnb)
    """
    from main.models import RoomICalConfig

    logger.info("Starting iCal feed polling...")

    all_configs = RoomICalConfig.objects.all().select_related('room')

    if not all_configs.exists():
        logger.info("No iCal configurations found")
        return "No configurations"

    synced_count = 0
    for config in all_configs:
        # Sync Booking.com if active
        if config.booking_active and config.booking_ical_url:
            logger.info(f"Triggering Booking.com sync for room: {config.room.name}")
            sync_room_ical_feed.delay(config.id, platform='booking')
            synced_count += 1

        # Sync Airbnb if active
        if config.airbnb_active and config.airbnb_ical_url:
            logger.info(f"Triggering Airbnb sync for room: {config.room.name}")
            sync_room_ical_feed.delay(config.id, platform='airbnb')
            synced_count += 1

    logger.info(f"Triggered {synced_count} platform sync(s)")
    return f"Triggered {synced_count} platform sync(s)"


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def sync_room_ical_feed(self, config_id, platform='booking'):
    """
    Sync one room's iCal feed for a specific platform (booking or airbnb)
    Creates/updates/cancels reservations based on iCal data

    Args:
        config_id: RoomICalConfig ID
        platform: 'booking' or 'airbnb'
    """
    from main.services.ical_service import sync_reservations_for_room

    logger.info(f"Syncing {platform} iCal feed for config ID: {config_id}")

    result = sync_reservations_for_room(config_id, platform=platform)

    if result['success']:
        logger.info(
            f"Sync completed for config {config_id} ({platform}): "
            f"{result['created']} created, {result['updated']} updated, "
            f"{result['cancelled']} cancelled"
        )
        return f"Success: {result['created']} created, {result['updated']} updated, {result['cancelled']} cancelled"
    else:
        logger.error(f"Sync failed for config {config_id} ({platform}): {result['errors']}")
        return f"Failed: {result['errors']}"


@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def handle_reservation_cancellation(self, reservation_id):
    """
    Handle cancelled reservation with date-based logic

    Only deletes guest and PINs if cancellation occurs BEFORE check-in date.
    If cancellation comes on or after check-in date, assumes guest already checked in.

    - Check if today < check_in_date
    - If yes: Delete guest, delete TTLock PINs, send cancellation notification
    - If no: Ignore (guest likely already checked in)
    """
    from main.models import Reservation
    from main.ttlock_utils import TTLockClient
    import pytz

    logger.info(f"Handling cancellation for reservation ID: {reservation_id}")

    try:
        reservation = Reservation.objects.select_related('guest').get(id=reservation_id)

        # Only process if reservation has an enriched guest
        if not reservation.guest:
            logger.info(f"Reservation {reservation_id} has no linked guest, skipping")
            return f"No guest linked to reservation {reservation_id}"

        guest = reservation.guest
        logger.info(f"Processing cancellation for guest: {guest.full_name} ({guest.reservation_number})")

        # Check if cancellation is BEFORE check-in date (Option 2 logic)
        uk_tz = pytz.timezone("Europe/London")
        today = timezone.now().astimezone(uk_tz).date()

        if today >= reservation.check_in_date:
            # Check-in date has passed - guest likely already checked in
            logger.info(
                f"Ignoring cancellation for reservation {reservation_id}. "
                f"Check-in date ({reservation.check_in_date}) has passed or is today. "
                f"Guest {guest.full_name} likely already checked in."
            )
            return f"Cancellation ignored - check-in date passed (guest likely already in room)"

        # Cancellation is BEFORE check-in date - proceed with deletion
        logger.info(
            f"Cancellation is before check-in date ({reservation.check_in_date}). "
            f"Proceeding with guest and PIN deletion for {guest.full_name}."
        )

        # Delete TTLock PINs if they exist
        if guest.front_door_pin_id or guest.room_pin_id:
            try:
                ttlock_client = TTLockClient()

                if guest.front_door_pin_id:
                    # Get front door lock
                    front_door_lock = guest.assigned_room.ttlock
                    if front_door_lock and front_door_lock.is_front_door:
                        ttlock_client.delete_pin(front_door_lock.lock_id, guest.front_door_pin_id)
                        logger.info(f"Deleted front door PIN for guest {guest.reservation_number}")

                if guest.room_pin_id:
                    # Get room lock
                    room_lock = guest.assigned_room.ttlock
                    if room_lock:
                        ttlock_client.delete_pin(room_lock.lock_id, guest.room_pin_id)
                        logger.info(f"Deleted room PIN for guest {guest.reservation_number}")

            except Exception as e:
                logger.error(f"Failed to delete TTLock PINs for guest {guest.reservation_number}: {str(e)}")

        # Delete the guest (this will trigger send_cancellation_message via Guest.delete())
        guest_name = guest.full_name
        guest.delete()
        logger.info(f"Deleted guest {guest_name} due to reservation cancellation")

        return f"Successfully handled cancellation for {guest_name}"

    except Reservation.DoesNotExist:
        logger.error(f"Reservation {reservation_id} not found")
        return f"Reservation {reservation_id} not found"
    except Exception as e:
        logger.error(f"Error handling cancellation for reservation {reservation_id}: {str(e)}")
        return f"Error: {str(e)}"


@shared_task(bind=True, max_retries=0)
def cleanup_old_reservations(self):
    """
    Daily cleanup task
    Deletes old cancelled/completed reservations that are no longer needed
    - Cancelled reservations older than 7 days
    - Completed unenriched reservations older than 30 days
    """
    from main.models import Reservation
    from datetime import timedelta

    logger.info("Running daily cleanup of old reservations...")

    now = timezone.now().date()
    cancelled_cutoff = now - timedelta(days=7)
    completed_cutoff = now - timedelta(days=30)

    # Delete old cancelled reservations (7+ days old, no guest linked)
    old_cancelled = Reservation.objects.filter(
        status='cancelled',
        check_out_date__lt=cancelled_cutoff,
        guest__isnull=True  # Only delete if no guest linked
    )
    cancelled_count = old_cancelled.count()
    if cancelled_count > 0:
        old_cancelled.delete()
        logger.info(f"Deleted {cancelled_count} old cancelled reservation(s)")

    # Delete old completed unenriched reservations (30+ days past checkout, no guest)
    old_completed = Reservation.objects.filter(
        status='confirmed',
        check_out_date__lt=completed_cutoff,
        guest__isnull=True  # Only unenriched
    )
    completed_count = old_completed.count()
    if completed_count > 0:
        old_completed.delete()
        logger.info(f"Deleted {completed_count} old unenriched reservation(s)")

    total_deleted = cancelled_count + completed_count
    logger.info(f"Cleanup complete: {total_deleted} total reservation(s) deleted")

    return f"Deleted {cancelled_count} cancelled, {completed_count} unenriched (total: {total_deleted})"


@shared_task(bind=True, max_retries=0)
def archive_past_guests(self):
    """
    Task to archive guests whose check-out time has passed
    - Deletes TTLock PINs (front door + room)
    - Marks guest as archived
    - Sends post-stay message

    Runs 3 times per day:
    - 12:15 PM UK time: Catches default 11 AM checkouts (15 min buffer)
    - 3:00 PM UK time: Catches late checkouts (most late checkouts by 2 PM)
    - 11:00 PM UK time: End of day safety net for any missed guests

    Only checks guests whose check_out_date is today or earlier (optimization)
    Multi-night stays (e.g., 5 days) will NOT be archived until their actual checkout date
    """
    from main.models import Guest, TTLock
    from main.ttlock_utils import TTLockClient
    from datetime import time
    import pytz
    import datetime

    logger.info("Starting hourly guest archiving task...")

    uk_timezone = pytz.timezone("Europe/London")
    now_time = timezone.now().astimezone(uk_timezone)
    today = now_time.date()

    # Only check guests whose check_out_date is today or earlier (major optimization)
    guests_to_check = Guest.objects.filter(
        is_archived=False,
        check_out_date__lte=today
    ).select_related('assigned_room', 'assigned_room__ttlock')

    if not guests_to_check.exists():
        logger.info("No guests need archiving at this time")
        return "No guests to archive"

    logger.info(f"Found {guests_to_check.count()} guest(s) to check for archiving")

    front_door_lock = TTLock.objects.filter(is_front_door=True).first()
    ttlock_client = TTLockClient()

    archived_count = 0
    error_count = 0

    for guest in guests_to_check:
        try:
            # Determine the check-out datetime based on late_checkout_time or default to 11:00 AM
            check_out_time_val = guest.late_checkout_time if guest.late_checkout_time else time(11, 0)
            check_out_datetime = uk_timezone.localize(
                datetime.datetime.combine(guest.check_out_date, check_out_time_val)
            )

            # Only archive if current time has passed check-out time
            if now_time <= check_out_datetime:
                logger.debug(f"Guest {guest.reservation_number} check-out time not reached yet ({check_out_datetime})")
                continue

            logger.info(f"Archiving guest: {guest.full_name} (Res: {guest.reservation_number})")

            # Delete front door PIN
            if guest.front_door_pin_id and front_door_lock:
                try:
                    ttlock_client.delete_pin(
                        lock_id=front_door_lock.lock_id,
                        keyboard_pwd_id=guest.front_door_pin_id,
                    )
                    logger.info(f"Deleted front door PIN for guest {guest.reservation_number}")
                except Exception as e:
                    logger.error(f"Failed to delete front door PIN for guest {guest.reservation_number}: {str(e)}")

            # Delete room PIN
            room_lock = guest.assigned_room.ttlock
            if guest.room_pin_id and room_lock:
                try:
                    ttlock_client.delete_pin(
                        lock_id=room_lock.lock_id,
                        keyboard_pwd_id=guest.room_pin_id,
                    )
                    logger.info(f"Deleted room PIN for guest {guest.reservation_number}")
                except Exception as e:
                    logger.error(f"Failed to delete room PIN for guest {guest.reservation_number}: {str(e)}")

            # Update guest status
            guest.front_door_pin = None
            guest.front_door_pin_id = None
            guest.room_pin_id = None
            guest.is_archived = True
            guest.save()

            # Send post-stay message if the guest has contact info
            if guest.phone_number or guest.email:
                try:
                    guest.send_post_stay_message()
                    logger.info(f"Sent post-stay message to {guest.full_name}")
                except Exception as e:
                    logger.error(f"Failed to send post-stay message to {guest.full_name}: {str(e)}")

            archived_count += 1
            logger.info(f"Successfully archived guest {guest.full_name} (Res: {guest.reservation_number})")

        except Exception as e:
            error_count += 1
            logger.error(f"Failed to archive guest {guest.reservation_number}: {str(e)}")

    logger.info(f"Archiving task complete: {archived_count} archived, {error_count} errors")
    return f"Archived {archived_count} guest(s), {error_count} error(s)"


# =========================
# EMAIL ENRICHMENT TASKS
# =========================

@shared_task(bind=True, max_retries=0)
def poll_booking_com_emails(self):
    """
    Poll Gmail for Booking.com reservation emails
    Scheduled to run every 5 minutes (reduced from 2 min)
    Creates PendingEnrichment records and triggers iCal sync
    """
    from main.services.email_parser import parse_booking_com_email_subject
    from main.models import PendingEnrichment
    from main.services.gmail_client import GmailClient
    from main.enrichment_config import ICAL_SYNC_RETRY_SCHEDULE

    logger.info("Polling Booking.com emails...")

    try:
        # Initialize Gmail client
        gmail = GmailClient()

        # Search for unread Booking.com emails
        emails = gmail.get_unread_booking_emails()

        if not emails:
            logger.info("No new Booking.com emails found")
            return "No new emails"

        logger.info(f"Found {len(emails)} new Booking.com email(s)")
        processed_count = 0

        for email_data in emails:
            subject = email_data['subject']
            email_id = email_data['id']
            received_at = email_data['received_at']

            # Parse email subject
            parsed = parse_booking_com_email_subject(subject)

            if not parsed:
                logger.warning(f"Could not parse email subject: {subject}")
                gmail.mark_as_read(email_id)
                continue

            email_type, booking_ref, check_in_date = parsed

            # Check if we already have this pending enrichment
            existing = PendingEnrichment.objects.filter(
                booking_reference=booking_ref,
                check_in_date=check_in_date,
                email_type=email_type
            ).first()

            if existing:
                logger.info(f"Pending enrichment already exists for {booking_ref}")
                gmail.mark_as_read(email_id)
                continue

            # Create pending enrichment
            pending = PendingEnrichment.objects.create(
                platform='booking',
                booking_reference=booking_ref,
                check_in_date=check_in_date,
                email_type=email_type,
                status='pending'
            )

            logger.info(f"Created PendingEnrichment #{pending.id} for booking {booking_ref}")

            # Mark email as read
            gmail.mark_as_read(email_id)

            # Trigger iCal sync workflow
            # Schedule first attempt in 1 minute
            countdown = ICAL_SYNC_RETRY_SCHEDULE[0]
            sync_booking_com_rooms_for_enrichment.apply_async(
                args=[pending.id],
                countdown=countdown
            )
            match_pending_to_reservation.apply_async(
                args=[pending.id, 1],
                countdown=countdown + 30  # Wait 30 seconds after sync
            )

            processed_count += 1

        logger.info(f"Processed {processed_count} Booking.com email(s)")
        return f"Processed {processed_count} email(s)"

    except Exception as e:
        logger.error(f"Error polling Booking.com emails: {str(e)}")
        return f"Error: {str(e)}"


@shared_task(bind=True, max_retries=1, rate_limit='10/m')
def sync_booking_com_rooms_for_enrichment(self, pending_id):
    """
    Sync all Booking.com room iCal feeds
    Triggered by email arrival for a specific pending enrichment

    Args:
        pending_id (int): PendingEnrichment ID that triggered this sync
    """
    from main.models import RoomICalConfig
    from main.services.ical_service import sync_reservations_for_room

    logger.info(f"Syncing Booking.com rooms for pending enrichment {pending_id}")

    # Get all Booking.com iCal configs
    configs = RoomICalConfig.objects.filter(
        booking_active=True,
        booking_ical_url__isnull=False
    ).select_related('room')

    if not configs.exists():
        logger.warning("No active Booking.com iCal configurations found")
        return "No configurations"

    synced_count = 0
    for config in configs:
        try:
            result = sync_reservations_for_room(config.id, platform='booking')
            if result['success']:
                synced_count += 1
                logger.info(f"Synced {config.room.name}: {result['created']} created, {result['updated']} updated")
        except Exception as e:
            logger.error(f"Failed to sync {config.room.name}: {str(e)}")

    logger.info(f"Synced {synced_count}/{configs.count()} Booking.com rooms")
    return f"Synced {synced_count} room(s)"


@shared_task(bind=True, max_retries=0)
def match_pending_to_reservation(self, pending_id, attempt_number):
    """
    Attempt to match pending enrichment to iCal reservation
    Handles retry logic and collision detection

    Args:
        pending_id (int): PendingEnrichment ID
        attempt_number (int): Current attempt number (1-5)
    """
    from main.services.enrichment_service import match_pending_enrichment
    from main.enrichment_config import ICAL_SYNC_RETRY_SCHEDULE

    logger.info(f"Matching attempt {attempt_number} for pending {pending_id}")

    # Attempt to match
    matched = match_pending_enrichment(pending_id, attempt_number)

    if matched:
        logger.info(f"Successfully matched pending {pending_id}")
        return "Matched"

    # Not matched - schedule retry if under 5 attempts
    if attempt_number < 5:
        next_attempt = attempt_number + 1
        countdown = ICAL_SYNC_RETRY_SCHEDULE[next_attempt - 1] - ICAL_SYNC_RETRY_SCHEDULE[attempt_number - 1]

        logger.info(f"Scheduling retry {next_attempt} for pending {pending_id} in {countdown}s")

        # Schedule next sync + match
        sync_booking_com_rooms_for_enrichment.apply_async(
            args=[pending_id],
            countdown=countdown
        )
        match_pending_to_reservation.apply_async(
            args=[pending_id, next_attempt],
            countdown=countdown + 30  # Give sync 30 sec to complete
        )

        return f"Scheduled retry {next_attempt}"

    # Failed after 5 attempts - trigger alert
    logger.warning(f"Failed to match pending {pending_id} after {attempt_number} attempts")
    send_enrichment_failure_alert.delay(pending_id)
    return "Failed - alert sent"


@shared_task(bind=True, max_retries=2, rate_limit='5/m')
def send_enrichment_failure_alert(self, pending_id):
    """
    Send SMS and email alert for failed enrichment
    Handles both single booking and collision scenarios

    Args:
        pending_id (int): PendingEnrichment ID
    """
    from main.models import PendingEnrichment, Room
    from main.services.enrichment_service import get_collision_bookings
    from main.enrichment_config import ADMIN_PHONE, ADMIN_EMAIL, ROOM_NUMBER_TO_NAME
    from twilio.rest import Client
    from django.conf import settings
    from django.core.mail import send_mail

    try:
        pending = PendingEnrichment.objects.get(id=pending_id)
    except PendingEnrichment.DoesNotExist:
        logger.error(f"PendingEnrichment {pending_id} not found")
        return "Not found"

    # Check for collision (multiple bookings for same date)
    collision_bookings = get_collision_bookings(pending.check_in_date)

    if collision_bookings.count() > 1:
        # Multiple bookings - send batch alert
        send_collision_alert(collision_bookings)
    else:
        # Single booking - send individual alert
        send_single_booking_alert(pending)

    # Mark as alerted
    pending.alert_sent_at = timezone.now()
    pending.save()

    return "Alert sent"


def send_single_booking_alert(pending):
    """Send SMS/Email alert for single booking failure"""
    from main.enrichment_config import ADMIN_PHONE, ADMIN_EMAIL
    from twilio.rest import Client
    from django.conf import settings
    from django.core.mail import send_mail

    # SMS Message
    sms_body = (
        f"PickARooms Alert:\n"
        f"Booking #{pending.booking_reference} for {pending.check_in_date.strftime('%d %b %Y')} "
        f"not found in iCal.\n\n"
        f"Reply format:\n"
        f"1-3 = Room 1, 3 nights\n"
        f"2-2 = Room 2, 2 nights\n"
        f"3-1 = Room 3, 1 night\n"
        f"4-5 = Room 4, 5 nights\n"
        f"X = Cancel\n\n"
        f"Example: Reply \"2-3\" for Room 2, 3 nights"
    )

    # Email Message
    email_body = (
        f"Manual Assignment Needed\n\n"
        f"Booking Reference: {pending.booking_reference}\n"
        f"Check-in Date: {pending.check_in_date.strftime('%d %B %Y')}\n"
        f"Platform: Booking.com\n"
        f"Email Received: {pending.email_received_at.strftime('%d %b %Y %H:%M')}\n"
        f"Sync Attempts: 5 (failed)\n\n"
        f"REPLY WITH ROOM NUMBER AND NIGHTS:\n"
        f"Reply \"1-3\" - Room 1, 3 nights\n"
        f"Reply \"2-2\" - Room 2, 2 nights\n"
        f"Reply \"3-1\" - Room 3, 1 night\n"
        f"Reply \"4-5\" - Room 4, 5 nights\n"
        f"Reply \"X\" - Cancel assignment\n\n"
        f"Or log in to: https://pickarooms.com/admin-page/pending-enrichments/"
    )

    # Send SMS
    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            to=ADMIN_PHONE,
            from_=settings.TWILIO_PHONE_NUMBER,
            body=sms_body
        )
        pending.alert_sms_sid = message.sid
        pending.save()
        logger.info(f"SMS alert sent for pending {pending.id}: {message.sid}")
    except Exception as e:
        logger.error(f"Failed to send SMS alert: {str(e)}")

    # Send Email
    try:
        send_mail(
            subject=f"Manual Assignment Needed - Booking #{pending.booking_reference}",
            message=email_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[ADMIN_EMAIL],
            fail_silently=False,
        )
        logger.info(f"Email alert sent for pending {pending.id}")
    except Exception as e:
        logger.error(f"Failed to send email alert: {str(e)}")


def send_collision_alert(collision_bookings):
    """Send SMS/Email alert for multiple bookings (collision)"""
    from main.enrichment_config import ADMIN_PHONE, ADMIN_EMAIL
    from twilio.rest import Client
    from django.conf import settings
    from django.core.mail import send_mail

    bookings = list(collision_bookings[:4])  # Max 4
    check_in_date = bookings[0].check_in_date if bookings else None

    # Build SMS message
    sms_lines = [
        f"PickARooms Alert:",
        f"{len(bookings)} Bookings for {check_in_date.strftime('%d %b %Y')}:",
        ""
    ]

    letters = ['A', 'B', 'C', 'D']
    for idx, booking in enumerate(bookings):
        letter = letters[idx]
        sms_lines.append(f"{letter}) #{booking.booking_reference}")

    sms_lines.extend([
        "",
        "Reply format:",
        "A1-3 = Booking A, Room 1, 3 nights",
        "B2-2 = Booking B, Room 2, 2 nights",
        "X = Cancel all",
        "",
        "Example: Reply \"A2-3\""
    ])

    sms_body = "\n".join(sms_lines)

    # Send SMS
    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            to=ADMIN_PHONE,
            from_=settings.TWILIO_PHONE_NUMBER,
            body=sms_body
        )
        logger.info(f"Collision SMS alert sent: {message.sid}")
    except Exception as e:
        logger.error(f"Failed to send collision SMS: {str(e)}")

    # Send Email
    email_body = f"Multiple Bookings Detected\n\n{sms_body}"
    try:
        send_mail(
            subject=f"Multiple Bookings - {check_in_date.strftime('%d %b %Y')}",
            message=email_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[ADMIN_EMAIL],
            fail_silently=False,
        )
        logger.info("Collision email alert sent")
    except Exception as e:
        logger.error(f"Failed to send collision email: {str(e)}")
