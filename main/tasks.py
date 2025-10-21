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
    Fetches all active RoomICalConfig and syncs each one
    """
    from main.models import RoomICalConfig

    logger.info("Starting iCal feed polling...")

    active_configs = RoomICalConfig.objects.filter(is_active=True).select_related('room')

    if not active_configs.exists():
        logger.info("No active iCal configurations found")
        return "No active configurations"

    synced_count = 0
    for config in active_configs:
        logger.info(f"Triggering sync for room: {config.room.name}")
        sync_room_ical_feed.delay(config.id)
        synced_count += 1

    logger.info(f"Triggered sync for {synced_count} room(s)")
    return f"Triggered sync for {synced_count} room(s)"


@shared_task
def sync_room_ical_feed(config_id):
    """
    Sync one room's iCal feed
    Creates/updates/cancels reservations based on iCal data
    """
    from main.services.ical_service import sync_reservations_for_room

    logger.info(f"Syncing iCal feed for config ID: {config_id}")

    result = sync_reservations_for_room(config_id)

    if result['success']:
        logger.info(
            f"Sync completed for config {config_id}: "
            f"{result['created']} created, {result['updated']} updated, "
            f"{result['cancelled']} cancelled"
        )
        return f"Success: {result['created']} created, {result['updated']} updated, {result['cancelled']} cancelled"
    else:
        logger.error(f"Sync failed for config {config_id}: {result['errors']}")
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
