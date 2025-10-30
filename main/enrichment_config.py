"""
Configuration for Email Parsing + iCal Enrichment System
XLS Room Type Mapping and Constants
"""

# XLS "Unit type" → Database Room Name Mapping
# Maps Booking.com XLS export "Unit type" column to Room model names
XLS_ROOM_MAPPING = {
    'Single Room': 'Room 3',
    'Middle Floor Room with OnSuite': 'Room 2',
    'No Onsuite middle floor double room': 'Room 1',
    'Topmost Room': 'Room 4',
}

# Reverse mapping for display (Database Room → Room Number)
DATABASE_ROOM_TO_NUMBER = {
    'Room 1': 1,
    'Room 2': 2,
    'Room 3': 3,
    'Room 4': 4,
}

# Room Number → Database Room Name
ROOM_NUMBER_TO_NAME = {
    1: 'Room 1',
    2: 'Room 2',
    3: 'Room 3',
    4: 'Room 4',
}

# Booking.com Email Subject Patterns
BOOKING_COM_EMAIL_PATTERNS = {
    'new': r'Booking\.com - New booking! \((\d{10}), (.+?)\)',
    'new_lastminute': r'Booking\.com - New last-minute booking \((\d{10}), (.+?)\)',
    'modification': r'Booking\.com - Modified booking! \((\d{10}), (.+?)\)',
    'cancellation': r'Booking\.com - Cancelled booking! \((\d{10}), (.+?)\)',
}

# Email polling interval (seconds)
EMAIL_POLL_INTERVAL = 300  # 5 minutes (reduced from 2 min to reduce worker load)

# iCal sync retry schedule (seconds from email received)
# HYBRID APPROACH: Better spacing to give Booking.com more time to update iCal feeds
# Total time: 24 minutes (vs old 9 min), 4 attempts (vs old 5)
ICAL_SYNC_RETRY_SCHEDULE = [
    300,   # Attempt 1: 5 min after email (gives Booking.com initial time)
    480,   # Attempt 2: 8 min after email (3 min gap - moderate wait)
    720,   # Attempt 3: 12 min after email (4 min gap - longer wait)
    1080,  # Attempt 4: 18 min after email (6 min gap - max patience)
    # If no match after 18 min, alert sent (total 24 min from email)
]

# Security: Whitelisted numbers and emails for SMS/Email replies
WHITELISTED_SMS_NUMBERS = ['+447539029629']
WHITELISTED_EMAILS = ['easybulb@gmail.com']

# Admin contact
ADMIN_PHONE = '+447539029629'
ADMIN_EMAIL = 'easybulb@gmail.com'

# Email search configuration (iCal-driven enrichment)
# Adaptive search: Increases lookback count when collision detected
EMAIL_SEARCH_LOOKBACK_COUNT_NORMAL = 20  # Normal case: single booking on check-in date
EMAIL_SEARCH_LOOKBACK_COUNT_COLLISION = 30  # Collision case: multiple bookings on same date
EMAIL_SEARCH_LOOKBACK_DAYS = 30  # Only search emails from last N days


def get_adaptive_email_count(check_in_date):
    """
    Adaptive email search window based on collision detection
    
    Logic:
    - Normal case (1 booking): Search 20 emails (covers ~2 weeks of traffic)
    - Collision case (2+ bookings): Search 30 emails (covers ~3 weeks, handles multi-room payment delays)
    
    Args:
        check_in_date: Date to check for collisions
    
    Returns:
        int: Number of emails to search (20 or 30)
    """
    from main.models import Reservation
    
    same_day_bookings = Reservation.objects.filter(
        check_in_date=check_in_date,
        platform='booking',
        status='confirmed',
        guest__isnull=True  # Unenriched only
    ).count()
    
    if same_day_bookings > 1:
        # Collision detected: Search more emails to find all matching bookings
        return EMAIL_SEARCH_LOOKBACK_COUNT_COLLISION
    else:
        # Normal case: Standard search window
        return EMAIL_SEARCH_LOOKBACK_COUNT_NORMAL
