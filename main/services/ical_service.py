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
    Extract 10-digit booking reference from text using regex

    Args:
        text (str): Text to search (typically iCal SUMMARY field)

    Returns:
        str or None: 10-digit booking reference if found, None otherwise

    Example:
        >>> extract_booking_reference("Booking.com Reservation 1234567890")
        '1234567890'
    """
    if not text:
        return None

    # Match exactly 10 consecutive digits
    match = re.search(r'\b(\d{10})\b', text)
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


def sync_reservations_for_room(config_id):
    """
    Sync reservations for a specific room from its iCal feed

    This is the main sync function that:
    1. Fetches the iCal feed
    2. Parses events
    3. Creates/updates reservations
    4. Marks cancelled reservations
    5. Updates sync status

    Args:
        config_id (int): RoomICalConfig ID

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

        if not config.is_active:
            logger.info(f"Skipping inactive config for room: {config.room.name}")
            return {
                'success': False,
                'created': 0,
                'updated': 0,
                'cancelled': 0,
                'errors': ['Configuration is inactive']
            }

        logger.info(f"Starting sync for room: {config.room.name}")

        # Fetch and parse iCal feed
        ical_data = fetch_ical_feed(config.ical_url)
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

                    # Get or create reservation
                    reservation, created = Reservation.objects.update_or_create(
                        ical_uid=uid,
                        defaults={
                            'room': config.room,
                            'guest_name': event['summary'],
                            'booking_reference': booking_ref or '',
                            'check_in_date': event['dtstart'],
                            'check_out_date': event['dtend'],
                            'status': event_status,
                            'raw_ical_data': event['raw']
                        }
                    )

                    if created:
                        created_count += 1
                        logger.info(f"Created reservation: {reservation}")
                    else:
                        updated_count += 1
                        logger.info(f"Updated reservation: {reservation}")

                except Exception as e:
                    error_msg = f"Error processing event {event.get('uid', 'unknown')}: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)

            # Mark reservations as cancelled if they're no longer in the feed
            # (Only for confirmed reservations that haven't been enriched yet)
            missing_reservations = Reservation.objects.filter(
                room=config.room,
                status='confirmed',
                guest__isnull=True  # Only unenriched reservations
            ).exclude(ical_uid__in=current_uids)

            for reservation in missing_reservations:
                reservation.status = 'cancelled'
                reservation.save()
                cancelled_count += 1
                logger.info(f"Marked as cancelled (removed from feed): {reservation}")

        # Update sync status
        config.last_synced = timezone.now()
        config.last_sync_status = f"Success: {created_count} created, {updated_count} updated, {cancelled_count} cancelled"
        config.save()

        logger.info(f"Sync completed for {config.room.name}: {created_count} created, {updated_count} updated, {cancelled_count} cancelled")

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
        error_msg = f"Sync failed for config {config_id}: {str(e)}"
        logger.error(error_msg)

        # Update sync status with error
        try:
            config = RoomICalConfig.objects.get(id=config_id)
            config.last_sync_status = f"Error: {str(e)}"
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
