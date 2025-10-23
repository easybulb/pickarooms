"""
iCal Service Layer for PickARooms
Handles fetching, parsing, and syncing iCal feeds from Booking.com and Airbnb
"""

import logging
import re
import requests
from datetime import datetime
from icalendar import Calendar
from django.utils import timezone
from django.db import transaction

from main.models import RoomICalConfig, Reservation, Room

logger = logging.getLogger('main')


def fetch_ical_feed(url, timeout=30):
    """
    Fetch iCal feed from URL

    Args:
        url (str): iCal feed URL
        timeout (int): Request timeout in seconds

    Returns:
        str: Raw iCal data

    Raises:
        requests.RequestException: If fetch fails
    """
    try:
        logger.info(f"Fetching iCal feed from: {url}")
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        logger.info(f"Successfully fetched iCal feed ({len(response.text)} bytes)")
        return response.text
    except requests.RequestException as e:
        logger.error(f"Failed to fetch iCal feed from {url}: {str(e)}")
        raise


def extract_booking_reference(text):
    """
    Extract booking reference from text using regex

    Supports:
    - Booking.com: 10-digit numeric codes (e.g., 5282674483)
    - Airbnb: 10-character alphanumeric codes (e.g., HMKHKPPZTQ)

    Args:
        text (str): Text to search (typically iCal SUMMARY field)

    Returns:
        str or None: Booking reference if found, None otherwise

    Examples:
        >>> extract_booking_reference("Booking.com Reservation 1234567890")
        '1234567890'
        >>> extract_booking_reference("Airbnb HMKHKPPZTQ Reservation")
        'HMKHKPPZTQ'
    """
    if not text:
        return None

    # First try: Match exactly 10 consecutive digits (Booking.com format)
    match = re.search(r'\b(\d{10})\b', text)
    if match:
        return match.group(1)

    # Second try: Match 10 uppercase letters (Airbnb format)
    match = re.search(r'\b([A-Z]{10})\b', text)
    if match:
        return match.group(1)

    return None


def parse_ical(ical_data):
    """
    Parse iCal data and extract event information

    Args:
        ical_data (str): Raw iCal data

    Returns:
        list: List of dicts containing event data:
            {
                'uid': str,
                'summary': str,
                'dtstart': date,
                'dtend': date,
                'status': str,
                'raw': str (raw event data for debugging)
            }

    Raises:
        ValueError: If iCal data is invalid
    """
    try:
        calendar = Calendar.from_ical(ical_data)
        events = []

        for component in calendar.walk('VEVENT'):
            # Extract event details
            uid = str(component.get('UID', ''))
            summary = str(component.get('SUMMARY', ''))
            dtstart = component.get('DTSTART')
            dtend = component.get('DTEND')
            status = str(component.get('STATUS', 'CONFIRMED')).upper()

            # Convert datetime to date if needed
            if hasattr(dtstart, 'dt'):
                dtstart = dtstart.dt
                if hasattr(dtstart, 'date'):
                    dtstart = dtstart.date()

            if hasattr(dtend, 'dt'):
                dtend = dtend.dt
                if hasattr(dtend, 'date'):
                    dtend = dtend.date()

            # Skip if missing required fields
            if not uid or not dtstart or not dtend:
                logger.warning(f"Skipping event with missing required fields: UID={uid}")
                continue

            events.append({
                'uid': uid,
                'summary': summary,
                'dtstart': dtstart,
                'dtend': dtend,
                'status': status,
                'raw': component.to_ical().decode('utf-8', errors='ignore')
            })

        logger.info(f"Parsed {len(events)} events from iCal feed")
        return events

    except Exception as e:
        logger.error(f"Failed to parse iCal data: {str(e)}")
        raise ValueError(f"Invalid iCal data: {str(e)}")


def sync_reservations_for_room(config_id, platform='booking'):
    """
    Sync reservations for a specific room from its iCal feed for a specific platform

    This is the main sync function that:
    1. Fetches the platform-specific iCal feed
    2. Parses events
    3. Creates/updates reservations with platform label
    4. Marks cancelled reservations
    5. Updates platform-specific sync status

    Args:
        config_id (int): RoomICalConfig ID
        platform (str): 'booking' or 'airbnb'

    Returns:
        dict: Sync results with counts
            {
                'success': bool,
                'created': int,
                'updated': int,
                'cancelled': int,
                'errors': list
            }
    """
    try:
        # Get configuration
        config = RoomICalConfig.objects.select_related('room').get(id=config_id)

        # Get platform-specific URL and active status
        if platform == 'booking':
            ical_url = config.booking_ical_url
            is_active = config.booking_active
        elif platform == 'airbnb':
            ical_url = config.airbnb_ical_url
            is_active = config.airbnb_active
        else:
            return {
                'success': False,
                'created': 0,
                'updated': 0,
                'cancelled': 0,
                'errors': [f'Invalid platform: {platform}']
            }

        if not is_active:
            logger.info(f"Skipping inactive {platform} config for room: {config.room.name}")
            return {
                'success': False,
                'created': 0,
                'updated': 0,
                'cancelled': 0,
                'errors': [f'{platform.capitalize()} configuration is inactive']
            }

        if not ical_url:
            logger.info(f"No {platform} iCal URL configured for room: {config.room.name}")
            return {
                'success': False,
                'created': 0,
                'updated': 0,
                'cancelled': 0,
                'errors': [f'No {platform} iCal URL configured']
            }

        logger.info(f"Starting {platform} sync for room: {config.room.name}")

        # Fetch and parse iCal feed
        ical_data = fetch_ical_feed(ical_url)
        events = parse_ical(ical_data)

        created_count = 0
        updated_count = 0
        cancelled_count = 0
        errors = []

        # Track current event UIDs to detect cancellations
        current_uids = set()

        with transaction.atomic():
            for event in events:
                try:
                    uid = event['uid']
                    current_uids.add(uid)

                    # Extract booking reference from summary
                    booking_ref = extract_booking_reference(event['summary'])

                    # Determine status
                    event_status = 'cancelled' if event['status'] == 'CANCELLED' else 'confirmed'

                    # Check if reservation already exists
                    # Strategy: Try multiple matching methods to prevent duplicates
                    # 1. Match by booking_reference + room + check_in (catches XLS-created reservations)
                    # 2. Match by ical_uid (catches iCal-created reservations)
                    reservation = None
                    created = False
                    match_method = None

                    # Method 1: Try matching by booking_reference + room + check_in_date
                    # This prevents duplicates when XLS upload happens before iCal sync
                    if booking_ref and len(booking_ref) >= 5:
                        reservation = Reservation.objects.filter(
                            booking_reference=booking_ref,
                            room=config.room,
                            check_in_date=event['dtstart']
                        ).first()
                        if reservation:
                            match_method = 'booking_ref'
                            logger.info(f"Found existing reservation by booking_ref: {booking_ref}")

                    # Method 2: Try matching by ical_uid (standard iCal behavior)
                    if not reservation:
                        try:
                            reservation = Reservation.objects.get(ical_uid=uid)
                            match_method = 'ical_uid'
                            logger.info(f"Found existing reservation by ical_uid: {uid}")
                        except Reservation.DoesNotExist:
                            pass

                    if reservation:
                        # UPDATE EXISTING: Preserve XLS-enriched data
                        # Only update fields that iCal should control (dates, status, raw data)
                        reservation.check_in_date = event['dtstart']
                        reservation.check_out_date = event['dtend']
                        reservation.status = event_status
                        reservation.raw_ical_data = event['raw']

                        # IMPORTANT: Update ical_uid if matched by booking_ref
                        # This links XLS-created reservations to iCal feed for future updates
                        if match_method == 'booking_ref' and reservation.ical_uid != uid:
                            old_uid = reservation.ical_uid
                            reservation.ical_uid = uid
                            logger.info(f"Updated ical_uid: {old_uid} → {uid}")

                        # Preserve XLS-enriched booking_reference (5+ chars)
                        # Only update if iCal has a valid booking_ref AND reservation doesn't have one yet
                        if booking_ref and len(booking_ref) >= 5:
                            # iCal has valid booking ref - update it
                            reservation.booking_reference = booking_ref
                            reservation.guest_name = event['summary']
                            logger.info(f"Updated booking_ref from iCal: {booking_ref}")
                        elif not reservation.booking_reference or len(reservation.booking_reference) < 5:
                            # No enrichment yet, update guest_name but keep booking_ref as-is (don't overwrite with empty)
                            reservation.guest_name = event['summary']
                            logger.info(f"Updated guest_name only, preserved booking_ref: {reservation.booking_reference or 'empty'}")
                        else:
                            # Preserve XLS-enriched data (booking_reference >= 5 chars)
                            logger.info(f"Preserved XLS-enriched booking_ref: {reservation.booking_reference}")

                        reservation.save()
                        updated_count += 1
                        logger.info(f"Updated reservation (method={match_method}, preserved enrichments): {reservation}")

                    else:
                        # CREATE NEW: First time seeing this iCal event
                        reservation = Reservation.objects.create(
                            ical_uid=uid,
                            room=config.room,
                            platform=platform,
                            guest_name=event['summary'],
                            booking_reference=booking_ref or '',
                            check_in_date=event['dtstart'],
                            check_out_date=event['dtend'],
                            status=event_status,
                            raw_ical_data=event['raw']
                        )
                        created_count += 1
                        logger.info(f"Created new reservation: {reservation}")

                except Exception as e:
                    error_msg = f"Error processing event {event.get('uid', 'unknown')}: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)

            # Mark reservations as cancelled if they're no longer in the feed
            # Includes both enriched and unenriched reservations
            # Signal handler will automatically trigger cancellation task for enriched ones
            missing_reservations = Reservation.objects.filter(
                room=config.room,
                platform=platform,
                status='confirmed',
            ).exclude(ical_uid__in=current_uids)

            for reservation in missing_reservations:
                reservation.status = 'cancelled'
                reservation.save()  # Triggers signal if enriched
                cancelled_count += 1
                enrichment_status = "enriched" if reservation.guest else "unenriched"
                logger.info(f"Marked as cancelled (removed from feed, {enrichment_status}): {reservation}")

        # Update platform-specific sync status
        sync_time = timezone.now()
        sync_status = f"Success: {created_count} created, {updated_count} updated, {cancelled_count} cancelled"

        if platform == 'booking':
            config.booking_last_synced = sync_time
            config.booking_last_sync_status = sync_status
        elif platform == 'airbnb':
            config.airbnb_last_synced = sync_time
            config.airbnb_last_sync_status = sync_status

        config.save()

        logger.info(f"{platform.capitalize()} sync completed for {config.room.name}: {created_count} created, {updated_count} updated, {cancelled_count} cancelled")

        return {
            'success': True,
            'created': created_count,
            'updated': updated_count,
            'cancelled': cancelled_count,
            'errors': errors
        }

    except RoomICalConfig.DoesNotExist:
        error_msg = f"RoomICalConfig with ID {config_id} not found"
        logger.error(error_msg)
        return {
            'success': False,
            'created': 0,
            'updated': 0,
            'cancelled': 0,
            'errors': [error_msg]
        }

    except Exception as e:
        error_msg = f"Sync failed for config {config_id} ({platform}): {str(e)}"
        logger.error(error_msg)

        # Update platform-specific sync status with error
        try:
            config = RoomICalConfig.objects.get(id=config_id)
            error_status = f"Error: {str(e)}"
            if platform == 'booking':
                config.booking_last_sync_status = error_status
            elif platform == 'airbnb':
                config.airbnb_last_sync_status = error_status
            config.save()
        except Exception:
            pass

        return {
            'success': False,
            'created': 0,
            'updated': 0,
            'cancelled': 0,
            'errors': [error_msg]
        }
