"""
SMS Reply Handler for Manual Room Assignment
Parses SMS replies and assigns rooms to pending enrichments
"""

import re
import logging
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from twilio.rest import Client

from main.models import PendingEnrichment, Reservation, Room, EnrichmentLog
from main.enrichment_config import WHITELISTED_SMS_NUMBERS, ROOM_NUMBER_TO_NAME
from main.services.sms_commands import (
    handle_guide_command,
    handle_check_command,
    handle_cancel_command,
    handle_correction_command,
    handle_single_ref_enrichment,
    handle_collision_enrichment,
    handle_multi_collision_enrichment,
    handle_multi_room_confirmation,
    send_confirmation_sms as send_sms
)

logger = logging.getLogger('main')


def parse_sms_reply(body):
    """
    Parse SMS reply with support for multiple formats:
    
    1. Single ref only: "6588202211" (email not found case)
    2. Collision format: "6588202211: 1-2" (single line)
    3. Multi-line collision: Multiple lines of format 2
    4. CHECK command: "check 6588202211" or "6588202211 check"
    5. CORRECT command: "6588202211: 1-2 correct"
    6. CANCEL command: "cancel 6588202211" or "6588202211 cancel"
    7. GUIDE command: "guide" or "help"

    Args:
        body (str): SMS message body

    Returns:
        dict with:
        - 'type': 'single_ref', 'collision', 'multi_collision', 'check', 'correct', 'cancel', 'guide'
        - 'data': Parsed data (varies by type)
    """
    body = body.strip()
    
    # GUIDE command (using 'commands' or 'menu' to avoid Twilio reserved keywords)
    if body.lower() in ['commands', 'menu', 'guide']:
        return {'type': 'guide', 'data': None}
    
    # OK confirmation (for multi-room booking)
    if body.strip().upper() == 'OK':
        return {'type': 'confirm_multi_room', 'data': None}
    
    # CHECK command (flexible format)
    check_match = re.match(r'(?:check\s+)?(\d{10})(?:\s+check)?', body, re.IGNORECASE)
    if check_match and ('check' in body.lower()):
        return {'type': 'check', 'data': {'booking_ref': check_match.group(1)}}
    
    # CANCEL command (flexible format)
    cancel_match = re.match(r'(?:cancel\s+)?(\d{10})(?:\s+cancel)?', body, re.IGNORECASE)
    if cancel_match and ('cancel' in body.lower()):
        return {'type': 'cancel', 'data': {'booking_ref': cancel_match.group(1)}}
    
    # CORRECT command
    correct_match = re.match(r'(\d{10})\s*:\s*([1-4])-(\d+)\s+correct', body, re.IGNORECASE)
    if correct_match:
        return {
            'type': 'correct',
            'data': {
                'booking_ref': correct_match.group(1),
                'room_number': int(correct_match.group(2)),
                'nights': int(correct_match.group(3))
            }
        }
    
    # Multi-line collision (multiple lines with format REF: ROOM-NIGHTS)
    lines = [line.strip() for line in body.split('\n') if line.strip()]
    if len(lines) > 1:
        # Check if all lines match collision format
        parsed_lines = []
        for line in lines:
            match = re.match(r'(\d{10})\s*:\s*([1-4])-(\d+)', line)
            if match:
                parsed_lines.append({
                    'booking_ref': match.group(1),
                    'room_number': int(match.group(2)),
                    'nights': int(match.group(3))
                })
        
        if len(parsed_lines) == len(lines):  # All lines valid
            return {'type': 'multi_collision', 'data': parsed_lines}
    
    # Single ref only (email not found case - just the booking reference)
    if re.match(r'^\d{10}$', body):
        return {'type': 'single_ref', 'data': {'booking_ref': body}}
    
    # Collision format (single line: REF: ROOM-NIGHTS)
    collision_match = re.match(r'(\d{10})\s*:\s*([1-4])-(\d+)', body)
    if collision_match:
        return {
            'type': 'collision',
            'data': {
                'booking_ref': collision_match.group(1),
                'room_number': int(collision_match.group(2)),
                'nights': int(collision_match.group(3))
            }
        }
    
    return None  # Invalid format


def is_authorized_sms(from_number):
    """Check if SMS sender is whitelisted"""
    return from_number in WHITELISTED_SMS_NUMBERS


# Use send_confirmation_sms from sms_commands module
send_confirmation_sms = send_sms


def handle_sms_room_assignment(from_number, body):
    """
    Handle SMS reply - routes to appropriate handler based on command type

    Args:
        from_number (str): Sender phone number
        body (str): SMS message body

    Returns:
        str: Response message
    """
    # Security check
    if not is_authorized_sms(from_number):
        logger.warning(f"Unauthorized SMS from: {from_number}")
        send_confirmation_sms(from_number, "❌ Unauthorized sender. Access denied.")
        return "Unauthorized"

    # Parse reply
    parsed = parse_sms_reply(body)
    if not parsed:
        logger.warning(f"Invalid SMS format from {from_number}: {body}")
        send_confirmation_sms(
            from_number,
            f"❌ Invalid format: '{body}'\n\n"
            "Send 'guide' for help"
        )
        return "Invalid format"

    # Route to appropriate handler
    cmd_type = parsed['type']
    
    if cmd_type == 'guide':
        return handle_guide_command(from_number)
    elif cmd_type == 'confirm_multi_room':
        return handle_multi_room_confirmation(from_number)
    elif cmd_type == 'check':
        return handle_check_command(from_number, parsed['data']['booking_ref'])
    elif cmd_type == 'cancel':
        return handle_cancel_command(from_number, parsed['data']['booking_ref'])
    elif cmd_type == 'correct':
        return handle_correction_command(
            from_number,
            parsed['data']['booking_ref'],
            parsed['data']['room_number'],
            parsed['data']['nights']
        )
    elif cmd_type == 'single_ref':
        # Email not found case - just booking ref provided
        return handle_single_ref_enrichment(from_number, parsed['data']['booking_ref'])
    elif cmd_type == 'collision':
        # Single collision line
        return handle_collision_enrichment(
            from_number,
            parsed['data']['booking_ref'],
            parsed['data']['room_number'],
            parsed['data']['nights']
        )
    elif cmd_type == 'multi_collision':
        # Multiple collision lines
        return handle_multi_collision_enrichment(from_number, parsed['data'])
    else:
        send_confirmation_sms(from_number, "❌ Unknown command. Send 'guide' for help")
        return "Unknown command"


def handle_cancellation_reply(from_number):
    """Cancel pending assignment"""
    # Find most recent failed pending enrichment
    pending = PendingEnrichment.objects.filter(
        status='failed_awaiting_manual',
        alert_sent_at__isnull=False
    ).order_by('-alert_sent_at').first()

    if not pending:
        msg = "❌ No pending assignment found to cancel."
        send_confirmation_sms(from_number, msg)
        return "No pending assignment found"

    booking_ref = pending.booking_reference
    check_in = pending.check_in_date.strftime('%d %b %Y')

    pending.status = 'cancelled'
    pending.save()

    logger.info(f"Cancelled pending enrichment {pending.id} via SMS")

    # Send confirmation
    confirmation = (
        f"✅ CANCELLED\n\n"
        f"Booking: #{booking_ref}\n"
        f"Check-in: {check_in}\n\n"
        f"No reservation created. Guest will need to book again if they still want the room."
    )
    send_confirmation_sms(from_number, confirmation)

    return "Assignment cancelled"


def assign_room_from_sms(booking_ref, room_number, nights, from_number):
    """
    Assign room to pending enrichment based on SMS reply

    Args:
        booking_ref (str): Booking reference number (10 digits)
        room_number (int): Room number (1-4)
        nights (int): Number of nights
        from_number (str): Admin phone number for confirmation SMS

    Returns:
        str: Result message
    """
    # Get room
    room_name = ROOM_NUMBER_TO_NAME.get(room_number)
    if not room_name:
        msg = f"❌ Invalid room number: {room_number}\n\nValid rooms: 1, 2, 3, 4"
        send_confirmation_sms(from_number, msg)
        return f"Invalid room number: {room_number}"

    try:
        room = Room.objects.get(name=room_name)
    except Room.DoesNotExist:
        logger.error(f"Room {room_name} not found")
        msg = f"❌ Room {room_name} not found in database. Please contact support."
        send_confirmation_sms(from_number, msg)
        return f"Room {room_name} not found"

    # Find pending enrichment by booking reference
    pending = PendingEnrichment.objects.filter(
        booking_reference=booking_ref,
        status='failed_awaiting_manual'
    ).order_by('-created_at').first()

    if not pending:
        # Check if booking ref exists but in wrong status
        any_pending = PendingEnrichment.objects.filter(
            booking_reference=booking_ref
        ).order_by('-created_at').first()
        
        if any_pending:
            msg = (
                f"❌ Booking #{booking_ref} found but status is '{any_pending.status}'.\n\n"
                f"Expected: failed_awaiting_manual\n"
                f"Check /admin-page/pending-enrichments/"
            )
        else:
            msg = (
                f"❌ Booking #{booking_ref} not found in system.\n\n"
                f"Check /admin-page/pending-enrichments/"
            )
        
        send_confirmation_sms(from_number, msg)
        return "Booking not found"

    # IDEMPOTENCY CHECK
    if pending.status == 'manually_assigned':
        logger.warning(f"Pending {pending.id} already manually assigned")
        msg = (
            f"⚠️ ALREADY ASSIGNED\n\n"
            f"Booking #{pending.booking_reference} was already assigned to "
            f"{pending.room_matched.name if pending.room_matched else 'a room'} earlier.\n\n"
            f"No duplicate reservation created."
        )
        send_confirmation_sms(from_number, msg)
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

    # Send confirmation SMS
    confirmation = (
        f"✅ ENRICHMENT COMPLETE\n\n"
        f"Booking: #{pending.booking_reference}\n"
        f"Room: {room.name}\n"
        f"Check-in: {pending.check_in_date.strftime('%d %b %Y')}\n"
        f"Check-out: {check_out_date.strftime('%d %b %Y')} ({nights} nights)\n\n"
        f"Reservation created and awaiting guest check-in. Guest will provide contact details when they check in via the app."
    )
    send_confirmation_sms(from_number, confirmation)

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
