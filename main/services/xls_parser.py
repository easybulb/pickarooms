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


def create_reservations_from_xls_row(row, warnings_list=None, action_log=None):
    """
    Create one or more Reservation objects from XLS row
    Handles both single-room and multi-room bookings

    Args:
        row (pandas.Series): Row from XLS dataframe
        warnings_list (list): Optional list to append warnings to
        action_log (dict): Optional dict to track detailed actions (deletions, restorations, status_changes)

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

        # CRITICAL: Skip cancelled bookings from XLS - don't process them at all
    # Booking.com uses multiple cancellation statuses: cancelled_by_guest, cancelled_by_hotel, cancelled_by_booking_dot_com
    if 'cancelled' in status.lower():
        logger.info(f"Skipping cancelled booking {booking_ref} from XLS (status: {status})")
        return []

    # Parse multi-room
    rooms = parse_multi_room_unit_type(unit_type)

    if not rooms:
        logger.error(f"No rooms mapped for booking {booking_ref}, unit type: {unit_type}")
        return []

    # ===========================================================================
    # XLS RECONCILIATION LOGIC (Option B++: Smart Room Assignment with Victim Restoration)
    # ===========================================================================
    # XLS is the single source of truth. This logic:
    # 1. Finds ALL existing reservations for this booking
    # 2. Deletes reservations for rooms NOT in XLS (wrong assignments)
    # 3. Restores any "victim" bookings that were auto-cancelled by the wrong assignment
    # 4. Updates existing correct room assignments (fixes status, guest name, etc.)
    # 5. Creates missing room assignments from XLS
    # ===========================================================================

    # STEP 1: Find ALL existing reservations for this booking reference
    all_existing = Reservation.objects.filter(
        booking_reference=booking_ref,
        check_in_date=check_in
    )

    existing_rooms_map = {res.room.name: res for res in all_existing}
    new_rooms_set = set(rooms)  # Rooms from XLS (truth)
    existing_rooms_set = set(existing_rooms_map.keys())  # Rooms in DB

    # STEP 2: Identify room changes
    rooms_to_delete = existing_rooms_set - new_rooms_set  # In DB but NOT in XLS (wrong!)
    rooms_to_create = new_rooms_set - existing_rooms_set  # In XLS but NOT in DB (missing)
    rooms_to_update = new_rooms_set & existing_rooms_set  # In both (correct rooms, may need data update)

    # Track actions for logging and analysis
    created_reservations = []
    restored_victims = []
    deleted_assignments = []
    status_restorations = []

    # Initialize action_log if provided
    if action_log is not None:
        if 'deleted_assignments' not in action_log:
            action_log['deleted_assignments'] = []
        if 'restored_victims' not in action_log:
            action_log['restored_victims'] = []
        if 'status_restorations' not in action_log:
            action_log['status_restorations'] = []

    # STEP 3: Delete wrong room assignments and restore victims
    if rooms_to_delete:
        logger.info(f"Room change detected for {booking_ref}: Removing from {rooms_to_delete}")
        if warnings_list is not None:
            warnings_list.append({
                'type': 'room_change',
                'booking_ref': booking_ref,
                'guest_name': guest_name,
                'check_in': check_in.isoformat(),
                'removed_rooms': list(rooms_to_delete),
                'added_rooms': list(rooms_to_create),
                'message': f"Auto-corrected: Removed {booking_ref} from {', '.join(rooms_to_delete)}"
            })

        for room_name in rooms_to_delete:
            wrong_res = existing_rooms_map[room_name]
            room = wrong_res.room

            # CRITICAL: Check if another booking was auto-cancelled due to this wrong assignment
            victim_booking = Reservation.objects.filter(
                room=room,
                check_in_date=check_in,
                status='cancelled'
            ).exclude(
                booking_reference__in=[booking_ref, '', None]
            ).order_by('-updated_at').first()

            # Delete the wrong assignment (only if guest not checked in)
            if wrong_res.guest is None:
                # Track deletion before deleting
                deleted_assignments.append({
                    'booking_ref': booking_ref,
                    'guest_name': guest_name,
                    'room': room_name
                })
                if action_log is not None:
                    action_log['deleted_assignments'].append({
                        'booking_ref': booking_ref,
                        'guest_name': guest_name,
                        'room': room_name,
                        'check_in': check_in.isoformat()
                    })

                wrong_res.delete()
                logger.info(f"✓ Deleted wrong assignment: {booking_ref} from {room_name}")

                # Restore victim booking if found
                if victim_booking:
                    victim_booking.status = 'confirmed'
                    victim_booking.save()
                    restored_victims.append(victim_booking)

                    # Track restoration
                    if action_log is not None:
                        action_log['restored_victims'].append({
                            'booking_ref': victim_booking.booking_reference,
                            'guest_name': victim_booking.guest_name,
                            'room': room_name,
                            'check_in': check_in.isoformat()
                        })

                    logger.info(f"✓ RESTORED victim: {victim_booking.booking_reference} ({victim_booking.guest_name}) to {room_name}")
            else:
                logger.warning(f"Cannot delete {booking_ref} from {room_name}: Guest already checked in")

    # STEP 4: Update existing correct room assignments
    for room_name in rooms_to_update:
        existing = existing_rooms_map[room_name]

        # Update all fields from XLS (XLS is truth)
        existing.booking_reference = booking_ref
        existing.guest_name = guest_name
        existing.check_out_date = check_out

        # CRITICAL: If XLS says status='ok', restore from cancelled
        if status == 'ok' and existing.status == 'cancelled':
            existing.status = 'confirmed'

            # Track status restoration
            status_restorations.append({
                'booking_ref': booking_ref,
                'guest_name': guest_name,
                'room': room_name
            })
            if action_log is not None:
                action_log['status_restorations'].append({
                    'booking_ref': booking_ref,
                    'guest_name': guest_name,
                    'room': room_name,
                    'check_in': check_in.isoformat()
                })

            logger.info(f"✓ RESTORED status: {booking_ref} -> {room_name} (was cancelled, now confirmed)")
        elif status == 'cancelled_by_guest':
            existing.status = 'cancelled'
        else:
            existing.status = 'confirmed'

        existing.save()
        created_reservations.append(('updated', existing))
        logger.info(f"✓ Updated: {booking_ref} -> {room_name}")

    # STEP 5: Create missing room assignments
    for room_name in rooms_to_create:
        try:
            room = Room.objects.get(name=room_name)
        except Room.DoesNotExist:
            logger.error(f"Room {room_name} not found in database")
            continue

        # Check if room already has a different booking (collision)
        # First try to match by room + dates (for iCal-synced reservations without booking_ref)
        ical_match = Reservation.objects.filter(
            room=room,
            check_in_date=check_in,
            check_out_date=check_out,
            status='confirmed',
            booking_reference__in=['', None]
        ).first()

        if ical_match:
            # Enrich the iCal reservation with booking ref from XLS
            ical_match.booking_reference = booking_ref
            ical_match.guest_name = guest_name
            ical_match.status = 'confirmed' if status == 'ok' else 'cancelled'
            ical_match.save()
            created_reservations.append(('updated', ical_match))
            logger.info(f"✓ Enriched iCal reservation: {booking_ref} -> {room_name}")
        else:
            # Check for collision with existing confirmed booking
            collision = Reservation.objects.filter(
                room=room,
                check_in_date=check_in,
                status='confirmed'
            ).exclude(
                booking_reference__in=[booking_ref, '', None]
            ).first()

            if collision:
                # Cancel the collision (XLS is truth)
                collision.status = 'cancelled'
                collision.save()
                logger.warning(f"⚠ Collision detected: Cancelled {collision.booking_reference} in {room_name} (XLS says {booking_ref} should be there)")

            # Create new reservation from XLS
            reservation = Reservation.objects.create(
                room=room,
                booking_reference=booking_ref,
                guest_name=guest_name,
                check_in_date=check_in,
                check_out_date=check_out,
                platform='booking',
                status='confirmed' if status == 'ok' else 'cancelled',
                ical_uid=f'xls_{booking_ref}_{room_name}_{timezone.now().timestamp()}',
            )
            created_reservations.append(('created', reservation))
            logger.info(f"✓ Created: {booking_ref} -> {room_name}")

    # Log summary of restoration
    if restored_victims:
        logger.info(f"✓ XLS reconciliation complete for {booking_ref}: Restored {len(restored_victims)} cancelled victim(s)")

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

    # Extract file metadata for age detection
    latest_booked_on = None
    if 'Booked on' in df.columns:
        try:
            booked_dates = pd.to_datetime(df['Booked on'], errors='coerce').dropna()
            if len(booked_dates) > 0:
                latest_booked_on = booked_dates.max()
        except Exception as e:
            logger.warning(f"Could not extract 'Booked on' dates: {e}")

    # Get file upload timestamp (current time - will be compared on next upload)
    from django.utils import timezone as dj_timezone
    current_upload_time = dj_timezone.now()

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
        'deleted_assignments': [],  # Track deletions
        'restored_victims': [],  # Track restorations
        'status_restorations': [],  # Track status changes
        'file_metadata': {
            'upload_timestamp': current_upload_time.isoformat(),
            'latest_booking_date': latest_booked_on.isoformat() if latest_booked_on else None,
        }
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

        # Create reservations (pass warnings list and action_log for detailed tracking)
        created_reservations = create_reservations_from_xls_row(
            row,
            warnings_list=results['warnings'],
            action_log=results  # Pass results dict which contains action tracking lists
        )

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
