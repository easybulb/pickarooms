"""
XLS Parser for Booking.com Reservations Export
Handles multi-room bookings and enrichment
"""

import logging
import pandas as pd
from datetime import date
from django.utils import timezone

from main.models import Reservation, Room, CSVEnrichmentLog, EnrichmentLog
from main.enrichment_config import XLS_ROOM_MAPPING

logger = logging.getLogger('main')


def parse_multi_room_unit_type(unit_type_str):
    """
    Parse XLS "Unit type" field to detect multi-room bookings

    Args:
        unit_type_str (str): Unit type from XLS (e.g., "Single Room" or "Single Room, No Onsuite middle floor double room")

    Returns:
        list: List of database room names (e.g., ['Room 3'] or ['Room 3', 'Room 1'])

    Examples:
        >>> parse_multi_room_unit_type("Single Room")
        ['Room 3']

        >>> parse_multi_room_unit_type("Single Room, No Onsuite middle floor double room")
        ['Room 3', 'Room 1']

        >>> parse_multi_room_unit_type("Middle Floor Room with OnSuite, Topmost Room")
        ['Room 2', 'Room 4']
    """
    if not unit_type_str or pd.isna(unit_type_str):
        return []

    # Split by comma
    room_types = [rt.strip() for rt in str(unit_type_str).split(',')]

    rooms = []
    for room_type in room_types:
        if room_type in XLS_ROOM_MAPPING:
            rooms.append(XLS_ROOM_MAPPING[room_type])
        else:
            logger.warning(f"Unknown room type in XLS: {room_type}")

    return rooms


def create_reservations_from_xls_row(row, warnings_list=None):
    """
    Create one or more Reservation objects from XLS row
    Handles both single-room and multi-room bookings

    Args:
        row (pandas.Series): Row from XLS dataframe
        warnings_list (list): Optional list to append warnings to

    Returns:
        list: List of tuples (action, reservation) where action is 'created' or 'updated'
    """
    booking_ref = str(row['Book Number']).strip()
    guest_name = str(row['Guest Name(s)']).strip() if pd.notna(row.get('Guest Name(s)')) else '(Unknown)'
    check_in = pd.to_datetime(row['Check-in']).date()
    check_out = pd.to_datetime(row['Check-out']).date()
    unit_type = str(row['Unit type']) if pd.notna(row.get('Unit type')) else ''
    phone = str(row['Phone number']).strip() if pd.notna(row.get('Phone number')) else ''
    status = str(row['Status']).strip() if pd.notna(row.get('Status')) else 'ok'

    # Parse multi-room
    rooms = parse_multi_room_unit_type(unit_type)

    if not rooms:
        logger.error(f"No rooms mapped for booking {booking_ref}, unit type: {unit_type}")
        return []

    # Check for room changes (booking moved to different room)
    existing_reservations = Reservation.objects.filter(
        booking_reference=booking_ref,
        check_in_date=check_in
    )

    if existing_reservations.exists():
        existing_rooms = set(res.room.name for res in existing_reservations)
        new_rooms = set(rooms)

        # Detect room changes
        removed_rooms = existing_rooms - new_rooms
        added_rooms = new_rooms - existing_rooms

        if removed_rooms or added_rooms:
            warning_msg = f"⚠️ ROOM CHANGE DETECTED for booking {booking_ref} ({guest_name}, {check_in}):"
            if removed_rooms:
                warning_msg += f" Removed from {', '.join(removed_rooms)}."
            if added_rooms:
                warning_msg += f" Added to {', '.join(added_rooms)}."
            warning_msg += " Please manually check/delete old reservations from Django admin."

            logger.warning(warning_msg)
            if warnings_list is not None:
                warnings_list.append({
                    'type': 'room_change',
                    'booking_ref': booking_ref,
                    'guest_name': guest_name,
                    'check_in': check_in,
                    'removed_rooms': list(removed_rooms),
                    'added_rooms': list(added_rooms),
                    'message': warning_msg
                })

    created_reservations = []

    for room_name in rooms:
        try:
            room = Room.objects.get(name=room_name)
        except Room.DoesNotExist:
            logger.error(f"Room {room_name} not found in database")
            continue

                                # Check if reservation already exists
        # CRITICAL: Prioritize confirmed reservations over cancelled ones
        # This prevents XLS from enriching the wrong reservation when both exist
        existing = Reservation.objects.filter(
            booking_reference=booking_ref,
            room=room,
            check_in_date=check_in,
            status='confirmed'  # Only match confirmed reservations
        ).first()
        
        # If no confirmed reservation found, check for cancelled (fallback)
        if not existing:
            existing = Reservation.objects.filter(
                booking_reference=booking_ref,
                room=room,
                check_in_date=check_in,
                status='cancelled'
            ).first()

        if existing:
            # Update existing
            existing.booking_reference = booking_ref  # FIX: Ensure booking ref is set (for iCal-synced reservations)
            existing.guest_name = guest_name
            existing.check_out_date = check_out
            if status == 'cancelled_by_guest':
                existing.status = 'cancelled'
            existing.save()
            created_reservations.append(('updated', existing))
            logger.info(f"Updated reservation: {booking_ref} → {room.name}")
        else:
            # Create new
            reservation_status = 'cancelled' if status == 'cancelled_by_guest' else 'confirmed'
            reservation = Reservation.objects.create(
                room=room,
                booking_reference=booking_ref,
                guest_name=guest_name,
                check_in_date=check_in,
                check_out_date=check_out,
                platform='booking',
                status=reservation_status,
                ical_uid=f'xls_{booking_ref}_{room_name}_{timezone.now().timestamp()}',
            )
            created_reservations.append(('created', reservation))
            logger.info(f"Created reservation: {booking_ref} → {room.name}")

    return created_reservations


def process_xls_file(xls_file, uploaded_by=None):
    """
    Process Booking.com XLS export with multi-room support
    Filters to today onwards only (no past bookings)

    Args:
        xls_file: File object (uploaded XLS file)
        uploaded_by: User who uploaded the file

    Returns:
        dict: Processing results
    """
    try:
        df = pd.read_excel(xls_file)
    except Exception as e:
        logger.error(f"Failed to read XLS file: {str(e)}")
        return {
            'success': False,
            'error': f"Failed to read XLS file: {str(e)}"
        }

    today = date.today()

    results = {
        'success': True,
        'total_rows': 0,
        'single_room_count': 0,
        'multi_room_count': 0,
        'created_count': 0,
        'updated_count': 0,
        'enrichment_results': [],
        'discrepancies': [],
        'warnings': [],  # Room change warnings
    }

    for _, row in df.iterrows():
        # Filter: Today onwards only
        try:
            check_in = pd.to_datetime(row['Check-in']).date()
        except Exception:
            continue

        if check_in < today:
            continue

        results['total_rows'] += 1

        # Parse multi-room
        unit_type = str(row['Unit type']) if pd.notna(row.get('Unit type')) else ''
        rooms = parse_multi_room_unit_type(unit_type)

        if len(rooms) > 1:
            results['multi_room_count'] += 1
        else:
            results['single_room_count'] += 1

        # Create reservations (pass warnings list for room change detection)
        created_reservations = create_reservations_from_xls_row(row, warnings_list=results['warnings'])

        for action, reservation in created_reservations:
            if action == 'created':
                results['created_count'] += 1
            elif action == 'updated':
                results['updated_count'] += 1

            # Get guest name safely (handle NaN values)
            guest_name_value = row.get('Guest Name(s)', '')
            if pd.isna(guest_name_value):
                guest_name_value = '(Unknown)'
            else:
                guest_name_value = str(guest_name_value).strip()

            # Log enrichment
            EnrichmentLog.objects.create(
                reservation=reservation,
                action='xls_enriched_multi' if len(rooms) > 1 else 'xls_enriched_single',
                booking_reference=str(row['Book Number']).strip(),
                room=reservation.room,
                method='csv_upload',
                details={
                    'room_count': len(rooms),
                    'rooms': rooms,
                    'guest_name': guest_name_value,
                }
            )

        # Get guest name safely for results
        guest_name_display = row.get('Guest Name(s)', '')
        if pd.isna(guest_name_display):
            guest_name_display = '(Unknown)'
        else:
            guest_name_display = str(guest_name_display).strip()

        results['enrichment_results'].append({
            'booking_ref': str(row['Book Number']).strip(),
            'guest_name': guest_name_display,
            'rooms': rooms,
            'action': f"{len(created_reservations)} reservation(s) processed",
        })

    # Save CSV enrichment log
    csv_log = CSVEnrichmentLog.objects.create(
        uploaded_by=uploaded_by,
        file_name=getattr(xls_file, 'name', 'unknown.xls'),
        total_rows=results['total_rows'],
        single_room_count=results['single_room_count'],
        multi_room_count=results['multi_room_count'],
        created_count=results['created_count'],
        updated_count=results['updated_count'],
        enrichment_summary=results
    )

    logger.info(
        f"XLS processing complete: {results['created_count']} created, "
        f"{results['updated_count']} updated, {results['multi_room_count']} multi-room"
    )

    results['csv_log_id'] = csv_log.id
    return results
