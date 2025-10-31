"""
SMS Command Handlers for PickARooms
Handles CHECK, CORRECT, CANCEL, GUIDE commands and enrichment workflows
"""

import logging
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from twilio.rest import Client

from main.models import Reservation, Room, EnrichmentLog
from main.enrichment_config import (
    ROOM_NUMBER_TO_NAME,
    EMAIL_SEARCH_LOOKBACK_DAYS,
    EMAIL_SEARCH_MAX_RESULTS
)

logger = logging.getLogger('main')


def mark_email_as_read_by_booking_ref(booking_ref):
    """
    Search for email with booking reference and mark it as read

    This is used after manual SMS enrichment to clean up Gmail inbox

    Args:
        booking_ref (str): 10-digit booking reference

    Returns:
        bool: True if email found and marked as read, False otherwise
    """
    try:
        from main.services.gmail_client import GmailClient
        from main.services.email_parser import parse_booking_com_email_subject

        gmail = GmailClient()

        # Search recent emails (same generous window as enrichment)
        emails = gmail.get_recent_booking_emails(
            max_results=EMAIL_SEARCH_MAX_RESULTS,
            lookback_days=EMAIL_SEARCH_LOOKBACK_DAYS
        )

        # Find the email with this booking ref
        for email_data in emails:
            subject = email_data['subject']
            parsed = parse_booking_com_email_subject(subject)

            if not parsed:
                continue

            email_type, email_booking_ref, check_in_date = parsed

            if email_booking_ref == booking_ref:
                # Found it! Mark as read
                gmail.mark_as_read(email_data['id'])
                logger.info(f"✅ Marked email as read for booking ref {booking_ref}")
                return True

        logger.warning(f"⚠️ Email not found in recent emails for booking ref {booking_ref}")
        return False

    except Exception as e:
        logger.error(f"Error marking email as read for booking ref {booking_ref}: {str(e)}")
        return False


def send_confirmation_sms(to_number, message):
    """Send SMS confirmation back to admin"""
    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        response = client.messages.create(
            to=to_number,
            from_=settings.TWILIO_PHONE_NUMBER,
            body=message
        )
        logger.info(f"Confirmation SMS sent to {to_number}: {response.sid}")
        return True
    except Exception as e:
        logger.error(f"Failed to send confirmation SMS: {str(e)}")
        return False


def handle_guide_command(from_number):
    """Return help guide with all SMS commands (shortened to fit SMS limits)"""
    guide_text = (
        "📘 SMS Commands\n\n"
        "COLLISION:\n"
        "REF: ROOM-NIGHTS\n"
        "Ex: 6588202211: 1-2\n\n"
        "MULTI-ROOM:\n"
        "Reply 'OK'\n\n"
        "EMAIL NOT FOUND:\n"
        "Reply ref only\n"
        "Ex: 6588202211\n\n"
        "CHECK:\n"
        "check 6588202211\n\n"
        "CORRECT:\n"
        "6588202211: 2-2 correct\n\n"
        "CANCEL:\n"
        "cancel 6588202211\n\n"
        "COMMANDS:\n"
        "commands | menu\n\n"
        "pickarooms.com/admin"
    )
    
    send_confirmation_sms(from_number, guide_text)
    logger.info(f"Sent guide to {from_number}")
    return "Guide sent"


def handle_check_command(from_number, booking_ref):
    """Query and return reservation status"""
    try:
        # Try to find reservation
        reservation = Reservation.objects.filter(
            booking_reference=booking_ref
        ).select_related('room', 'guest').first()
        
        if not reservation:
            msg = f"❌ Reservation #{booking_ref} not found.\n\nCheck dashboard:\npickarooms.com/admin"
            send_confirmation_sms(from_number, msg)
            return "Reservation not found"
        
        # Build status message
        if reservation.guest:
            # Enriched
            guest = reservation.guest
            status_msg = (
                f"Reservation #{booking_ref}\n\n"
                f"Status: Confirmed ✅\n"
                f"Room: {reservation.room.name}\n"
                f"Check-in: {reservation.check_in_date.strftime('%d %b %Y')} "
                f"({guest.early_checkin_time.strftime('%I:%M %p') if guest.early_checkin_time else '2:00 PM'})\n"
                f"Check-out: {reservation.check_out_date.strftime('%d %b %Y')} "
                f"({guest.late_checkout_time.strftime('%I:%M %p') if guest.late_checkout_time else '11:00 AM'})\n"
                f"Guest: {guest.full_name}\n"
                f"Phone: {guest.phone_number or 'N/A'}\n"
                f"Email: {guest.email or 'N/A'}\n"
                f"PIN: {guest.front_door_pin or 'N/A'} {'(active)' if guest.front_door_pin else ''}\n\n"
                f"Source: {dict(reservation.PLATFORM_CHOICES).get(reservation.platform, 'Manual')} iCal"
            )
        else:
            # Unenriched
            nights = (reservation.check_out_date - reservation.check_in_date).days
            status_msg = (
                f"Reservation #{booking_ref}\n\n"
                f"Status: Pending Enrichment ⏳\n"
                f"Room: {reservation.room.name}\n"
                f"Check-in: {reservation.check_in_date.strftime('%d %b %Y')}\n"
                f"Check-out: {reservation.check_out_date.strftime('%d %b %Y')} ({nights} nights)\n\n"
                f"Awaiting booking ref from email.\n\n"
                f"To enrich manually, reply:\n"
                f"{booking_ref}"
            )
        
        send_confirmation_sms(from_number, status_msg)
        logger.info(f"Sent check status for {booking_ref} to {from_number}")
        return "Check command executed"
        
    except Exception as e:
        logger.error(f"Error in check command for {booking_ref}: {str(e)}")
        msg = f"❌ Error checking {booking_ref}: {str(e)}"
        send_confirmation_sms(from_number, msg)
        return f"Error: {str(e)}"


def handle_cancel_command(from_number, booking_ref):
    """Cancel a reservation"""
    try:
        reservation = Reservation.objects.filter(
            booking_reference=booking_ref,
            status='confirmed'
        ).first()
        
        if not reservation:
            msg = f"❌ Reservation #{booking_ref} not found or already cancelled."
            send_confirmation_sms(from_number, msg)
            return "Reservation not found"
        
        # Check if enriched (has guest)
        if reservation.guest:
            # If enriched, delete guest (triggers PIN deletion and cancellation email)
            guest_name = reservation.guest.full_name
            reservation.guest.delete()
            
        # Mark reservation as cancelled
        reservation.status = 'cancelled'
        reservation.save()
        
        confirmation = (
            f"✅ CANCELLED\n\n"
            f"Booking: #{booking_ref}\n"
            f"Room: {reservation.room.name}\n"
            f"Check-in: {reservation.check_in_date.strftime('%d %b %Y')}\n\n"
            f"Reservation deleted."
        )
        send_confirmation_sms(from_number, confirmation)
        logger.info(f"Cancelled reservation {booking_ref} via SMS")
        return "Reservation cancelled"
        
    except Exception as e:
        logger.error(f"Error cancelling {booking_ref}: {str(e)}")
        msg = f"❌ Error cancelling {booking_ref}: {str(e)}"
        send_confirmation_sms(from_number, msg)
        return f"Error: {str(e)}"


def handle_correction_command(from_number, booking_ref, room_number, nights):
    """Correct a previous enrichment mistake"""
    try:
        # Find existing reservation
        old_reservation = Reservation.objects.filter(
            booking_reference=booking_ref
        ).first()
        
        if not old_reservation:
            msg = f"❌ Booking #{booking_ref} not found."
            send_confirmation_sms(from_number, msg)
            return "Booking not found"
        
        old_room = old_reservation.room.name
        old_nights = (old_reservation.check_out_date - old_reservation.check_in_date).days
        
        # Get new room
        room_name = ROOM_NUMBER_TO_NAME.get(room_number)
        if not room_name:
            msg = f"❌ Invalid room number: {room_number}\n\nValid rooms: 1, 2, 3, 4"
            send_confirmation_sms(from_number, msg)
            return f"Invalid room number"
        
        new_room = Room.objects.get(name=room_name)
        new_check_out = old_reservation.check_in_date + timedelta(days=nights)
        
        # Delete old reservation (and guest if enriched)
        if old_reservation.guest:
            old_reservation.guest.delete()
        old_reservation.delete()
        
        # Create new corrected reservation
        new_reservation = Reservation.objects.create(
            room=new_room,
            booking_reference=booking_ref,
            check_in_date=old_reservation.check_in_date,
            check_out_date=new_check_out,
            platform='booking',
            status='confirmed',
            ical_uid=f'corrected_{booking_ref}_{timezone.now().timestamp()}',
            guest_name='(Awaiting guest details)',
        )
        
        confirmation = (
            f"✅ CORRECTION APPLIED\n\n"
            f"Previous: {old_room}, {old_nights} nights\n"
            f"Updated: {new_room.name}, {nights} nights\n\n"
            f"Booking: #{booking_ref}\n"
            f"Room: {new_room.name} (corrected)\n"
            f"Check-in: {new_reservation.check_in_date.strftime('%d %b %Y')}\n"
            f"Check-out: {new_reservation.check_out_date.strftime('%d %b %Y')} ({nights} nights)\n\n"
            f"Old reservation deleted, new one created."
        )
        send_confirmation_sms(from_number, confirmation)
        logger.info(f"Corrected reservation {booking_ref}: {old_room}/{old_nights}n → {new_room.name}/{nights}n")
        return "Correction applied"
        
    except Exception as e:
        logger.error(f"Error correcting {booking_ref}: {str(e)}")
        msg = f"❌ Error correcting {booking_ref}: {str(e)}"
        send_confirmation_sms(from_number, msg)
        return f"Error: {str(e)}"


def handle_single_ref_enrichment(from_number, booking_ref):
    """
    Handle email not found case - just booking ref provided
    Find the unenriched reservation and update with booking ref
    """
    try:
        # Find unenriched reservation that needs this booking ref
        # This should be a reservation waiting for enrichment (no booking_ref yet)
        reservation = Reservation.objects.filter(
            platform='booking',
            status='confirmed',
            guest__isnull=True,
            booking_reference=''  # Empty string means unenriched
        ).order_by('-created_at').first()
        
        if not reservation:
            msg = (
                f"❌ No unenriched reservation found waiting for enrichment.\n\n"
                f"Check dashboard:\npickarooms.com/admin"
            )
            send_confirmation_sms(from_number, msg)
            return "No reservation waiting"
        
        # Update reservation with booking ref
        reservation.booking_reference = booking_ref
        reservation.guest_name = f"Guest {booking_ref}"
        reservation.save()

        # Mark email as read in Gmail
        mark_email_as_read_by_booking_ref(booking_ref)

        nights = (reservation.check_out_date - reservation.check_in_date).days

        confirmation = (
            f"✅ ENRICHMENT COMPLETE\n\n"
            f"Booking: #{booking_ref}\n"
            f"Room: {reservation.room.name}\n"
            f"Check-in: {reservation.check_in_date.strftime('%d %b %Y')}\n"
            f"Check-out: {reservation.check_out_date.strftime('%d %b %Y')} ({nights} nights)\n\n"
            f"Reservation ready for check-in."
        )
        send_confirmation_sms(from_number, confirmation)
        logger.info(f"Enriched reservation {reservation.id} with ref {booking_ref}")

        # Log the enrichment
        EnrichmentLog.objects.create(
            reservation=reservation,
            action='manual_enrichment_sms',
            booking_reference=booking_ref,
            room=reservation.room,
            method='sms_single_ref',
            details={'check_in_date': str(reservation.check_in_date)}
        )
        
        return "Single ref enrichment complete"
        
    except Exception as e:
        logger.error(f"Error in single ref enrichment for {booking_ref}: {str(e)}")
        msg = f"❌ Error: {str(e)}"
        send_confirmation_sms(from_number, msg)
        return f"Error: {str(e)}"


def handle_collision_enrichment(from_number, booking_ref, room_number, nights):
    """Handle single collision line enrichment"""
    try:
        # Get room
        room_name = ROOM_NUMBER_TO_NAME.get(room_number)
        if not room_name:
            msg = f"❌ Invalid room number: {room_number}\n\nValid rooms: 1, 2, 3, 4"
            send_confirmation_sms(from_number, msg)
            return f"Invalid room number"
        
        room = Room.objects.get(name=room_name)
        
        # Find unenriched reservation for this room
        reservation = Reservation.objects.filter(
            room=room,
            platform='booking',
            status='confirmed',
            guest__isnull=True,
            booking_reference=''  # Empty string means unenriched
        ).order_by('-created_at').first()
        
        if not reservation:
            msg = f"❌ No unenriched reservation found for {room.name}."
            send_confirmation_sms(from_number, msg)
            return "No reservation found"
        
        # Calculate checkout date
        check_out_date = reservation.check_in_date + timedelta(days=nights)
        
        # Update reservation
        reservation.booking_reference = booking_ref
        reservation.check_out_date = check_out_date
        reservation.guest_name = f"Guest {booking_ref}"
        reservation.save()

        # Mark email as read in Gmail
        mark_email_as_read_by_booking_ref(booking_ref)

        confirmation = (
            f"✅ ENRICHMENT COMPLETE\n\n"
            f"Booking: #{booking_ref}\n"
            f"Room: {room.name}\n"
            f"Check-in: {reservation.check_in_date.strftime('%d %b %Y')}\n"
            f"Check-out: {reservation.check_out_date.strftime('%d %b %Y')} ({nights} nights)\n\n"
            f"Reservation ready for check-in."
        )
        send_confirmation_sms(from_number, confirmation)
        logger.info(f"Collision enrichment: {booking_ref} → {room.name}, {nights}n")

        # Log the enrichment
        EnrichmentLog.objects.create(
            reservation=reservation,
            action='manual_enrichment_sms',
            booking_reference=booking_ref,
            room=room,
            method='sms_collision',
            details={'nights': nights}
        )

        return "Collision enrichment complete"
        
    except Exception as e:
        logger.error(f"Error in collision enrichment for {booking_ref}: {str(e)}")
        msg = f"❌ Error: {str(e)}"
        send_confirmation_sms(from_number, msg)
        return f"Error: {str(e)}"


def handle_multi_collision_enrichment(from_number, enrichments):
    """
    Handle multiple collision lines (multi-line SMS)
    
    Args:
        enrichments: List of dicts with booking_ref, room_number, nights
    """
    try:
        results = []
        
        for data in enrichments:
            booking_ref = data['booking_ref']
            room_number = data['room_number']
            nights = data['nights']
            
            # Get room
            room_name = ROOM_NUMBER_TO_NAME.get(room_number)
            if not room_name:
                results.append(f"❌ {booking_ref}: Invalid room {room_number}")
                continue
            
            room = Room.objects.get(name=room_name)
            
            # Find unenriched reservation
            reservation = Reservation.objects.filter(
                room=room,
                platform='booking',
                status='confirmed',
                guest__isnull=True,
                booking_reference=''  # Empty string means unenriched
            ).order_by('-created_at').first()
            
            if not reservation:
                results.append(f"❌ {booking_ref}: No reservation for {room.name}")
                continue
            
            # Calculate checkout
            check_out_date = reservation.check_in_date + timedelta(days=nights)
            
            # Update reservation
            reservation.booking_reference = booking_ref
            reservation.check_out_date = check_out_date
            reservation.guest_name = f"Guest {booking_ref}"
            reservation.save()

            # Mark email as read in Gmail
            mark_email_as_read_by_booking_ref(booking_ref)

            results.append(
                f"✅ #{booking_ref}\n"
                f"   {room.name}, {nights}n\n"
                f"   {reservation.check_in_date.strftime('%d %b')} - {check_out_date.strftime('%d %b')}"
            )

            logger.info(f"Multi-collision: {booking_ref} → {room.name}, {nights}n")
        
        # Send consolidated confirmation
        confirmation = (
            f"✅ ENRICHMENT COMPLETE ({len(results)} bookings)\n\n" +
            "\n\n".join(results) +
            "\n\nAll reservations ready for check-in."
        )
        send_confirmation_sms(from_number, confirmation)
        
        # Log multi-collision enrichment
        for data in enrichments:
            EnrichmentLog.objects.create(
                action='multi_enrichment_sms',
                booking_reference=data['booking_ref'],
                method='sms_multi_collision',
                details={'total_bookings': len(enrichments)}
            )
        
        return f"Multi-collision enrichment: {len(results)} processed"
        
    except Exception as e:
        logger.error(f"Error in multi-collision enrichment: {str(e)}")
        msg = f"❌ Error: {str(e)}"
        send_confirmation_sms(from_number, msg)
        return f"Error: {str(e)}"


def handle_multi_room_confirmation(from_number):
    """
    Handle admin confirmation of multi-room booking enrichment
    Admin replied 'OK' to confirm the multi-room enrichment is correct
    """
    try:
        # Find the most recently enriched multi-room booking
        # Look for multiple reservations with same booking_ref and recent creation
        from django.db.models import Count
        from datetime import timedelta
        
        recent_time = timezone.now() - timedelta(minutes=15)
        
        # Find booking refs that have multiple reservations created recently
        multi_room_refs = Reservation.objects.filter(
            platform='booking',
            status='confirmed',
            created_at__gte=recent_time,
            guest__isnull=True
        ).exclude(
            booking_reference=''
        ).values('booking_reference').annotate(
            room_count=Count('id')
        ).filter(room_count__gte=2).order_by('-room_count')
        
        if not multi_room_refs.exists():
            # Fallback to generic confirmation
            confirmation = (
                "✅ CONFIRMED\n\n"
                "Multi-room booking verified.\n"
                "All rooms ready for check-in."
            )
            send_confirmation_sms(from_number, confirmation)
            logger.info(f"Multi-room booking confirmed (no recent multi-room found)")
            return "Multi-room confirmed"
        
        # Get the first multi-room booking ref
        booking_ref = multi_room_refs[0]['booking_reference']
        
        # Get all reservations for this booking
        reservations = Reservation.objects.filter(
            booking_reference=booking_ref,
            platform='booking',
            status='confirmed'
        ).select_related('room').order_by('room__name')
        
        # Build detailed confirmation
        confirmation_lines = [
            "✅ MULTI-ROOM CONFIRMED\n",
            f"Booking #{booking_ref}",
            f"Total rooms: {reservations.count()}\n"
        ]
        
        for res in reservations:
            nights = (res.check_out_date - res.check_in_date).days
            confirmation_lines.append(
                f"✅ {res.room.name}\n"
                f"   {res.check_in_date.strftime('%d %b')} - {res.check_out_date.strftime('%d %b')} ({nights}n)"
            )
        
        confirmation_lines.append("\nAll rooms enriched and ready for guest check-in.")
        
        confirmation = "\n".join(confirmation_lines)
        send_confirmation_sms(from_number, confirmation)
        logger.info(f"Multi-room booking confirmed: {booking_ref} ({reservations.count()} rooms)")
        
        # Log the confirmation
        EnrichmentLog.objects.create(
            action='multi_room_confirmed',
            booking_reference=booking_ref,
            method='sms_confirmation',
            details={
                'confirmed_by': 'admin',
                'room_count': reservations.count(),
                'rooms': [r.room.name for r in reservations]
            }
        )
        
        return f"Multi-room confirmed: {booking_ref}"
    except Exception as e:
        logger.error(f"Error in multi-room confirmation: {str(e)}")
        msg = f"❌ Error confirming multi-room: {str(e)}"
        send_confirmation_sms(from_number, msg)
        return f"Error: {str(e)}"
