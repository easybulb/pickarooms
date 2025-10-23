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
    'modification': r'Booking\.com - Modified booking! \((\d{10}), (.+?)\)',
    'cancellation': r'Booking\.com - Cancelled booking! \((\d{10}), (.+?)\)',
}

# Email polling interval (seconds)
EMAIL_POLL_INTERVAL = 120  # 2 minutes

# iCal sync retry schedule (seconds from email received)
ICAL_SYNC_RETRY_SCHEDULE = [
    60,    # Attempt 1: 1 min after email
    180,   # Attempt 2: 3 min after email (2 min since attempt 1)
    300,   # Attempt 3: 5 min after email (2 min since attempt 2)
    420,   # Attempt 4: 7 min after email (2 min since attempt 3)
    540,   # Attempt 5: 9 min after email (2 min since attempt 4)
]

# Security: Whitelisted numbers and emails for SMS/Email replies
WHITELISTED_SMS_NUMBERS = ['+447539029629']
WHITELISTED_EMAILS = ['easybulb@gmail.com']

# Admin contact
ADMIN_PHONE = '+447539029629'
ADMIN_EMAIL = 'easybulb@gmail.com'
