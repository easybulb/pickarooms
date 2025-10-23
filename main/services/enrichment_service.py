"""
Enrichment Service - Handles matching pending enrichments to iCal reservations
Includes multi-room detection and collision handling
"""

import logging
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Count

from main.models import (
    PendingEnrichment,
    Reservation,
    Room,
    EnrichmentLog
)

logger = logging.getLogger('main')


def match_pending_enrichment(pending_id, attempt_number):
    """
    Attempt to match pending enrichment to iCal reservation(s)
    Handles multi-room bookings and collision detection

    Args:
        pending_id (int): PendingEnrichment ID
        attempt_number (int): Current attempt number (1-5)

    Returns:
        bool: True if matched, False if needs retry
    """
    try:
        pending = PendingEnrichment.objects.get(id=pending_id)
    except PendingEnrichment.DoesNotExist:
        logger.error(f"PendingEnrichment {pending_id} not found")
        return False

    # Skip if already matched
    if pending.status in ['matched', 'manually_assigned']:
        logger.info(f"Pending {pending_id} already {pending.status}, skipping")
        return True

    # Find ALL unenriched reservations with matching check-in date
    candidates = Reservation.objects.filter(
        check_in_date=pending.check_in_date,
        platform='booking',
        booking_reference__isnull=True,
        status='confirmed'
    ).order_by('-created_at')

    # Check for collision: Multiple pending enrichments for same date
    competing_pendings = PendingEnrichment.objects.filter(
        check_in_date=pending.check_in_date,
        platform='booking',
        status='pending'
    ).exclude(id=pending_id)

    # SCENARIO 1: Collision detected (multiple emails for same date)
    if competing_pendings.exists() and candidates.count() > 1:
        logger.warning(
            f"Collision detected: {competing_pendings.count() + 1} pendings, "
            f"{candidates.count()} candidates for {pending.check_in_date}"
        )

        # Mark all as failed - will trigger batch alert
        for comp_pending in competing_pendings:
            if comp_pending.status == 'pending':
                comp_pending.status = 'failed_awaiting_manual'
                comp_pending.save()

        pending.status = 'failed_awaiting_manual'
        pending.save()

        # Log collision
        EnrichmentLog.objects.create(
            pending_enrichment=pending,
            action='collision_detected',
            booking_reference=pending.booking_reference,
            details={
                'pending_count': competing_pendings.count() + 1,
                'candidate_count': candidates.count(),
                'check_in_date': str(pending.check_in_date),
            }
        )

        return False  # Will trigger manual assignment

    # SCENARIO 2: Multi-room booking (multiple candidates, single email)
    if not competing_pendings.exists() and candidates.count() > 1:
        logger.info(
            f"Multi-room booking detected: {candidates.count()} rooms "
            f"for booking {pending.booking_reference}"
        )

        # Assign booking reference to ALL candidates
        rooms = []
        for reservation in candidates:
            reservation.booking_reference = pending.booking_reference
            reservation.save()
            rooms.append(reservation.room.name)

        pending.status = 'matched'
        pending.enriched_via = 'email_ical_auto'
        pending.enriched_at = timezone.now()
        pending.save()

        # Log multi-room match
        EnrichmentLog.objects.create(
            pending_enrichment=pending,
            action='auto_matched_multi_room',
            booking_reference=pending.booking_reference,
            details={
                'room_count': candidates.count(),
                'rooms': rooms,
            }
        )

        logger.info(f"Multi-room match successful: {pending.booking_reference} → {', '.join(rooms)}")
        return True

    # SCENARIO 3: Single room booking
    if candidates.count() == 1:
        reservation = candidates.first()
        reservation.booking_reference = pending.booking_reference
        reservation.save()

        pending.status = 'matched'
        pending.matched_reservation = reservation
        pending.room_matched = reservation.room
        pending.enriched_via = 'email_ical_auto'
        pending.enriched_at = timezone.now()
        pending.save()

        # Log single room match
        EnrichmentLog.objects.create(
            pending_enrichment=pending,
            reservation=reservation,
            action='auto_matched_single',
            booking_reference=pending.booking_reference,
            room=reservation.room,
        )

        logger.info(
            f"Single room match successful: {pending.booking_reference} → {reservation.room.name}"
        )
        return True

    # SCENARIO 4: No match yet
    logger.info(
        f"No match found for {pending.booking_reference} on attempt {attempt_number}, "
        f"found {candidates.count()} candidates"
    )

    pending.attempts = attempt_number
    pending.save()

    return False  # Needs retry


def detect_multi_room_booking(check_in_date, platform='booking'):
    """
    Detect if multiple rooms are booked for same check-in date

    Args:
        check_in_date (date): Check-in date
        platform (str): Platform ('booking' or 'airbnb')

    Returns:
        int: Number of unenriched reservations for that date
    """
    count = Reservation.objects.filter(
        check_in_date=check_in_date,
        platform=platform,
        booking_reference__isnull=True,
        status='confirmed'
    ).count()

    return count


def get_collision_bookings(check_in_date):
    """
    Get all pending enrichments for a specific check-in date
    (Used for batch alert)

    Args:
        check_in_date (date): Check-in date

    Returns:
        QuerySet: PendingEnrichment objects
    """
    return PendingEnrichment.objects.filter(
        check_in_date=check_in_date,
        platform='booking',
        status='failed_awaiting_manual',
        alert_sent_at__isnull=True  # Not yet alerted
    ).order_by('email_received_at')
