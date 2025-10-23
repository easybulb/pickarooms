"""
SMS Reply Handler for Manual Room Assignment
Parses SMS replies and assigns rooms to pending enrichments
"""

import re
import logging
from datetime import timedelta
from django.utils import timezone

from main.models import PendingEnrichment, Reservation, Room, EnrichmentLog
from main.enrichment_config import WHITELISTED_SMS_NUMBERS, ROOM_NUMBER_TO_NAME

logger = logging.getLogger('main')


def parse_sms_reply(body):
    """
    Parse SMS reply in format: "A1-3" or "2-3"

    Args:
        body (str): SMS message body

    Returns:
        tuple: (booking_letter, room_number, nights) or None if invalid

    Examples:
        - "A1-3" → ('A', 1, 3)  # Booking A, Room 1, 3 nights
        - "2-3"  → (None, 2, 3) # Single booking, Room 2, 3 nights
        - "X"    → ('X', None, None)  # Cancel
    """
    body = body.strip().upper()

    if body == 'X':
        return ('X', None, None)

    # Multi-booking format: A1-3, B2-2, C3-1, D4-5
    match = re.match(r'([A-D])([1-4])-(\d+)', body)
    if match:
        booking_letter = match.group(1)
        room_number = int(match.group(2))
        nights = int(match.group(3))
        return (booking_letter, room_number, nights)

    # Single booking format: 1-3, 2-2, 3-1, 4-5
    match = re.match(r'([1-4])-(\d+)', body)
    if match:
        room_number = int(match.group(1))
        nights = int(match.group(2))
        return (None, room_number, nights)

    return None  # Invalid format


def is_authorized_sms(from_number):
    """Check if SMS sender is whitelisted"""
    return from_number in WHITELISTED_SMS_NUMBERS


def handle_sms_room_assignment(from_number, body):
    """
    Handle SMS reply for room assignment

    Args:
        from_number (str): Sender phone number
        body (str): SMS message body

    Returns:
        str: Response message
    """
    # Security check
    if not is_authorized_sms(from_number):
        logger.warning(f"Unauthorized SMS from: {from_number}")
        return "Unauthorized"

    # Parse reply
    parsed = parse_sms_reply(body)
    if not parsed:
        logger.warning(f"Invalid SMS format from {from_number}: {body}")
        return "Invalid format"

    booking_letter, room_number, nights = parsed

    # Handle cancellation
    if booking_letter == 'X':
        return handle_cancellation_reply(from_number)

    # Handle room assignment
    return assign_room_from_sms(booking_letter, room_number, nights)


def handle_cancellation_reply(from_number):
    """Cancel pending assignment"""
    # Find most recent failed pending enrichment
    pending = PendingEnrichment.objects.filter(
        status='failed_awaiting_manual',
        alert_sent_at__isnull=False
    ).order_by('-alert_sent_at').first()

    if not pending:
        return "No pending assignment found"

    pending.status = 'cancelled'
    pending.save()

    logger.info(f"Cancelled pending enrichment {pending.id} via SMS")
    return "Assignment cancelled"


def assign_room_from_sms(booking_letter, room_number, nights):
    """
    Assign room to pending enrichment based on SMS reply

    Args:
        booking_letter (str or None): Booking letter (A-D) for collision, None for single
        room_number (int): Room number (1-4)
        nights (int): Number of nights

    Returns:
        str: Result message
    """
    # Get room
    room_name = ROOM_NUMBER_TO_NAME.get(room_number)
    if not room_name:
        return f"Invalid room number: {room_number}"

    try:
        room = Room.objects.get(name=room_name)
    except Room.DoesNotExist:
        logger.error(f"Room {room_name} not found")
        return f"Room {room_name} not found"

    # Find pending enrichment
    if booking_letter:
        # Multi-booking scenario - find by letter
        pending = find_pending_by_letter(booking_letter)
    else:
        # Single booking scenario - find most recent failed
        pending = PendingEnrichment.objects.filter(
            status='failed_awaiting_manual',
            alert_sent_at__isnull=False
        ).order_by('-alert_sent_at').first()

    if not pending:
        return "No pending assignment found"

    # IDEMPOTENCY CHECK
    if pending.status == 'manually_assigned':
        logger.warning(f"Pending {pending.id} already manually assigned")
        return "Already assigned"

    # Calculate checkout date
    check_out_date = pending.check_in_date + timedelta(days=nights)

    # Create reservation
    reservation = Reservation.objects.create(
        room=room,
        booking_reference=pending.booking_reference,
        check_in_date=pending.check_in_date,
        check_out_date=check_out_date,
        platform='booking',
        status='confirmed',
        ical_uid=f'manual_{pending.booking_reference}_{timezone.now().timestamp()}',
        guest_name='(Awaiting guest details)',
    )

    # Update pending
    pending.status = 'manually_assigned'
    pending.matched_reservation = reservation
    pending.room_matched = room
    pending.manual_assignment_method = 'sms_reply'
    pending.enriched_via = 'sms_reply'
    pending.enriched_at = timezone.now()
    pending.save()

    # Log
    EnrichmentLog.objects.create(
        pending_enrichment=pending,
        reservation=reservation,
        action='sms_reply_assigned',
        booking_reference=pending.booking_reference,
        room=room,
        method='sms_reply',
        details={
            'nights': nights,
            'check_out_date': str(check_out_date),
            'room_number': room_number,
        }
    )

    logger.info(
        f"SMS assignment successful: {pending.booking_reference} → {room.name}, {nights} nights"
    )

    return f"Assigned: {pending.booking_reference} → {room.name}, {nights} nights"


def find_pending_by_letter(letter):
    """
    Find pending enrichment by collision letter (A, B, C, D)

    Args:
        letter (str): Letter A-D

    Returns:
        PendingEnrichment or None
    """
    # Get most recent collision alert
    recent_collision = PendingEnrichment.objects.filter(
        status='failed_awaiting_manual',
        alert_sent_at__isnull=False
    ).order_by('-alert_sent_at').first()

    if not recent_collision:
        return None

    # Get all pending enrichments for same check-in date
    collision_bookings = list(PendingEnrichment.objects.filter(
        check_in_date=recent_collision.check_in_date,
        platform='booking',
        status='failed_awaiting_manual',
        alert_sent_at__isnull=False
    ).order_by('email_received_at')[:4])

    # Map letter to index
    letter_to_index = {'A': 0, 'B': 1, 'C': 2, 'D': 3}
    index = letter_to_index.get(letter)

    if index is not None and index < len(collision_bookings):
        return collision_bookings[index]

    return None
