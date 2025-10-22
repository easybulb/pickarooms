"""
Django signals for PickARooms
Handles automatic actions when model state changes
"""

import logging
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from main.models import Reservation

logger = logging.getLogger('main')


@receiver(pre_save, sender=Reservation)
def track_reservation_status_change(sender, instance, **kwargs):
    """
    Track the previous status of a reservation before save
    This allows us to detect status changes in post_save signal
    """
    if instance.pk:  # Only for existing reservations (not new ones)
        try:
            old_instance = Reservation.objects.get(pk=instance.pk)
            instance._old_status = old_instance.status
        except Reservation.DoesNotExist:
            instance._old_status = None
    else:
        instance._old_status = None


@receiver(post_save, sender=Reservation)
def handle_reservation_status_change(sender, instance, created, **kwargs):
    """
    Automatically handle reservation status changes

    When a reservation changes to 'cancelled' and has an enriched guest:
    - Trigger cancellation handling task (which will check dates and delete if needed)
    """
    # Skip if this is a new reservation being created
    if created:
        return

    # Check if status changed to 'cancelled'
    old_status = getattr(instance, '_old_status', None)
    if old_status and old_status != 'cancelled' and instance.status == 'cancelled':
        # Status changed from something else to 'cancelled'

        if instance.guest:
            # Reservation has an enriched guest - trigger cancellation handling
            logger.info(f"Reservation {instance.id} status changed to cancelled with enriched guest. Triggering cancellation task.")

            # Import task here to avoid circular imports
            from main.tasks import handle_reservation_cancellation

            # Trigger async task to handle the cancellation
            handle_reservation_cancellation.delay(instance.id)
        else:
            # Unenriched reservation cancelled - no action needed
            logger.info(f"Reservation {instance.id} cancelled (unenriched, no guest linked)")
