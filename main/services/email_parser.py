"""
Email Parser for Booking.com Confirmation Emails
Extracts booking references and check-in dates from email subjects
"""

import re
import logging
from datetime import datetime
from main.enrichment_config import BOOKING_COM_EMAIL_PATTERNS

logger = logging.getLogger('main')


def parse_booking_com_email_subject(subject):
    """
    Parse Booking.com email subject to extract booking details

    Args:
        subject (str): Email subject line

    Returns:
        tuple: (email_type, booking_ref, check_in_date) or None if not a reservation email

        Examples:
        >>> parse_booking_com_email_subject("Booking.com - New booking! (5592652343, Saturday, 20 December 2025)")
        ('new', '5592652343', datetime.date(2025, 12, 20))

        >>> parse_booking_com_email_subject("Booking.com - New last-minute booking (6936428721, Wednesday, 29 October 2025)")
        ('new_lastminute', '6936428721', datetime.date(2025, 10, 29))

        >>> parse_booking_com_email_subject("Booking.com - Cancelled booking! (6906335726, Friday, 14 November 2025)")
        ('cancellation', '6906335726', datetime.date(2025, 11, 14))
    """
    if not subject:
        return None

    for email_type, pattern in BOOKING_COM_EMAIL_PATTERNS.items():
        match = re.search(pattern, subject)
        if match:
            booking_ref = match.group(1)  # e.g., "5592652343"
            date_str = match.group(2)      # e.g., "Saturday, 20 December 2025"

            try:
                check_in_date = parse_date_string(date_str)
                return (email_type, booking_ref, check_in_date)
            except ValueError as e:
                logger.error(f"Failed to parse date '{date_str}' from email subject: {e}")
                return None

    # Not a reservation email - ignore
    return None


def parse_date_string(date_str):
    """
    Parse Booking.com date format to Python date object

    Args:
        date_str (str): Date string like "Saturday, 20 December 2025" or "Thursday, 11 June 2026"

    Returns:
        datetime.date: Parsed date

    Raises:
        ValueError: If date format is invalid
    """
    # Booking.com format: "DayName, DD MonthName YYYY"
    # Examples: "Saturday, 20 December 2025", "Thursday, 11 June 2026"

    try:
        # Remove day name (e.g., "Saturday, ")
        date_str_clean = re.sub(r'^[A-Za-z]+,\s*', '', date_str.strip())

        # Parse: "20 December 2025"
        parsed_date = datetime.strptime(date_str_clean, '%d %B %Y').date()
        return parsed_date
    except ValueError:
        # Try alternative format without day name
        try:
            parsed_date = datetime.strptime(date_str.strip(), '%d %B %Y').date()
            return parsed_date
        except ValueError as e:
            raise ValueError(f"Invalid date format: {date_str}") from e


def is_booking_com_reservation_email(subject):
    """
    Check if email subject is a Booking.com reservation-related email

    Args:
        subject (str): Email subject

    Returns:
        bool: True if reservation email, False otherwise
    """
    return parse_booking_com_email_subject(subject) is not None
