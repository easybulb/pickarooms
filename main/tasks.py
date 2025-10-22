"""
Celery tasks for PickARooms iCal integration
"""
from celery import shared_task
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


@shared_task
def poll_all_ical_feeds():
    """
    Main scheduled task - runs every 10 minutes
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


@shared_task
def sync_room_ical_feed(config_id, platform='booking'):
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


@shared_task
def handle_reservation_cancellation(reservation_id):
    """
    Handle cancelled reservation
    - Delete guest (if linked and TTLock PINs)
    - Send cancellation notification
    """
    from main.models import Reservation
    from main.ttlock_utils import TTLockClient

    logger.info(f"Handling cancellation for reservation ID: {reservation_id}")

    try:
        reservation = Reservation.objects.select_related('guest').get(id=reservation_id)

        # Only process if reservation has an enriched guest
        if not reservation.guest:
            logger.info(f"Reservation {reservation_id} has no linked guest, skipping")
            return f"No guest linked to reservation {reservation_id}"

        guest = reservation.guest
        logger.info(f"Processing cancellation for guest: {guest.full_name} ({guest.reservation_number})")

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


@shared_task
def cleanup_old_reservations():
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


@shared_task
def archive_past_guests():
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
