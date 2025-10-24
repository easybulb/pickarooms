"""
Helper functions for Admin Dashboard "Current Guests" feature
"""
from datetime import date
from django.db.models import Q
from .models import Guest, Reservation, Room


def get_current_guests_data(today=None):
    """
    Get all currently active guests (checked in, not checked out)
    
    Returns:
        dict: {
            'current_guests': QuerySet,
            'current_reservations': QuerySet,
            'dashboard_stats': dict
        }
    """
    if today is None:
        today = date.today()
    
    # Get all currently staying guests (already checked in, not checked out)
    current_guests = Guest.objects.filter(
        is_archived=False,
        check_in_date__lte=today,  # Already checked in
        check_out_date__gte=today   # Not yet checked out
    ).select_related('assigned_room').order_by('check_out_date')
    
    # Get unenriched reservations that are currently active
    current_reservations = Reservation.objects.filter(
        check_in_date__lte=today,
        check_out_date__gte=today,
        status='confirmed',
        guest__isnull=True
    ).select_related('room').order_by('check_out_date')
    
    # Calculate dashboard stats
    dashboard_stats = calculate_dashboard_stats(today, current_guests, current_reservations)
    
    return {
        'current_guests': current_guests,
        'current_reservations': current_reservations,
        'dashboard_stats': dashboard_stats
    }


def calculate_dashboard_stats(today, current_guests, current_reservations):
    """Calculate dashboard summary statistics"""
    
    # Currently In House (checked in before today, not yet checked out)
    in_house_count = current_guests.filter(check_in_date__lt=today).count()
    
    # Checking In Today
    checking_in_today_guests = Guest.objects.filter(
        is_archived=False,
        check_in_date=today
    ).count()
    
    checking_in_today_reservations = Reservation.objects.filter(
        check_in_date=today,
        status='confirmed',
        guest__isnull=True
    ).count()
    
    checking_in_today = checking_in_today_guests + checking_in_today_reservations
    
    # Checking Out Today
    checking_out_today = Guest.objects.filter(
        is_archived=False,
        check_out_date=today
    ).count()
    
    # Room Occupancy
    total_rooms = Room.objects.count()
    occupied_rooms = current_guests.values('assigned_room').distinct().count()
    
    # Pending Check-Ins (unenriched reservations)
    pending_checkins = current_reservations.count()
    
    return {
        'in_house': in_house_count,
        'checking_in_today': checking_in_today,
        'checking_out_today': checking_out_today,
        'total_rooms': total_rooms,
        'occupied_rooms': occupied_rooms,
        'pending_checkins': pending_checkins,
    }


def build_entries_list(guests_queryset, reservations_queryset):
    """
    Build unified list of entries (guests + reservations) for display
    
    Returns:
        list: List of entry dictionaries
    """
    entries = []
    
    # Add enriched guests
    for guest in guests_queryset:
        entries.append({
            'type': 'guest',
            'id': guest.id,
            'guest_id': guest.id,
            'object': guest,
            'is_enriched': True,
            'is_returning': guest.is_returning,
            'full_name': guest.full_name,
            'phone_number': guest.phone_number or '---',
            'email': guest.email or '---',
            'booking_ref': guest.reservation_number,
            'room': guest.assigned_room,
            'pin': guest.front_door_pin,
            'check_in_date': guest.check_in_date,
            'check_out_date': guest.check_out_date,
            'early_checkin_time': guest.early_checkin_time,
            'late_checkout_time': guest.late_checkout_time,
            'platform': '👤 Manual',  # Manually created or from old system
            'secure_token': guest.secure_token,
        })
    
    # Add unenriched reservations
    for reservation in reservations_queryset:
        platform_badge = '📘 Booking.com' if reservation.platform == 'booking' else '🏠 Airbnb'
        
        entries.append({
            'type': 'reservation',
            'id': reservation.id,
            'reservation_id': reservation.id,
            'object': reservation,
            'is_enriched': False,
            'is_returning': False,
            'full_name': reservation.guest_name or '(Guest Name Not Available)',
            'phone_number': '---',
            'email': '---',
            'booking_ref': reservation.booking_reference or '---',
            'room': reservation.room,
            'pin': None,
            'check_in_date': reservation.check_in_date,
            'check_out_date': reservation.check_out_date,
            'early_checkin_time': reservation.early_checkin_time,
            'late_checkout_time': reservation.late_checkout_time,
            'platform': platform_badge,
            'platform_raw': reservation.platform,
        })
    
    return entries


def get_guest_status(entry, today):
    """
    Get status indicator for a guest entry
    
    Returns:
        str: Status emoji + text
    """
    if not entry['is_enriched']:
        return '⚪ NOT CHECKED IN'
    
    if entry['check_in_date'] == today:
        return '🟡 JUST ARRIVED'
    elif entry['check_out_date'] == today:
        return '🔴 LEAVING TODAY'
    else:
        return '🟢 IN-STAY'


def get_night_progress(check_in_date, check_out_date, today):
    """
    Calculate night progress (e.g., "Night 2/3")
    
    Returns:
        str: Progress string
    """
    total_nights = (check_out_date - check_in_date).days
    if total_nights <= 0:
        return "N/A"
    
    nights_spent = max(0, (today - check_in_date).days)
    current_night = min(nights_spent + 1, total_nights)
    
    return f"Night {current_night}/{total_nights}"
