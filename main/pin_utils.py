# main/pin_utils.py
import random


def generate_memorable_4digit_pin():
    """
    Generate a memorable 4-digit PIN avoiding patterns like:
    - All same digits (1111, 2222, etc.)
    - Sequential ascending (1234, 5678, etc.)
    - Sequential descending (4321, 8765, etc.)
    - Repeating pairs (1212, 3434, etc.)
    """
    while True:
        pin = str(random.randint(1000, 9999))

        # Check if all digits are the same
        if len(set(pin)) == 1:
            continue

        # Check for sequential ascending (e.g., 1234, 5678)
        if all(int(pin[i]) + 1 == int(pin[i + 1]) for i in range(3)):
            continue

        # Check for sequential descending (e.g., 4321, 8765)
        if all(int(pin[i]) - 1 == int(pin[i + 1]) for i in range(3)):
            continue

        # Check for repeating pairs (e.g., 1212, 3434)
        if pin[0] == pin[2] and pin[1] == pin[3]:
            continue

        # If it passes all checks, it's memorable enough
        return pin


def add_wakeup_prefix(pin):
    """
    Add 2 random dummy digits as prefix to wake up TTLock physical keypad.
    These are for display only - the actual PIN sent to TTLock is still 4 digits.

    Args:
        pin: The actual 4-digit PIN

    Returns:
        A 6-digit string with 2 dummy prefix digits + 4-digit PIN
    """
    prefix = str(random.randint(10, 99))
    return f"{prefix}{pin}"
