"""
Phone Number Utilities for PickARooms
Handles normalization and validation for Twilio E.164 format
"""

import re
import logging

logger = logging.getLogger('main')

# Comprehensive list of country codes
COUNTRY_CODES = [
    ('+44', '🇬🇧 United Kingdom (+44)'),
    ('+1', '🇺🇸 United States (+1)'),
    ('+1', '🇨🇦 Canada (+1)'),
    ('+91', '🇮🇳 India (+91)'),
    ('+234', '🇳🇬 Nigeria (+234)'),
    ('+86', '🇨🇳 China (+86)'),
    ('+33', '🇫🇷 France (+33)'),
    ('+49', '🇩🇪 Germany (+49)'),
    ('+81', '🇯🇵 Japan (+81)'),
    ('+61', '🇦🇺 Australia (+61)'),
    ('+55', '🇧🇷 Brazil (+55)'),
    ('+7', '🇷🇺 Russia (+7)'),
    ('+82', '🇰🇷 South Korea (+82)'),
    ('+34', '🇪🇸 Spain (+34)'),
    ('+39', '🇮🇹 Italy (+39)'),
    ('+52', '🇲🇽 Mexico (+52)'),
    ('+62', '🇮🇩 Indonesia (+62)'),
    ('+90', '🇹🇷 Turkey (+90)'),
    ('+31', '🇳🇱 Netherlands (+31)'),
    ('+966', '🇸🇦 Saudi Arabia (+966)'),
    ('+41', '🇨🇭 Switzerland (+41)'),
    ('+27', '🇿🇦 South Africa (+27)'),
    ('+20', '🇪🇬 Egypt (+20)'),
    ('+48', '🇵🇱 Poland (+48)'),
    ('+66', '🇹🇭 Thailand (+66)'),
    ('+65', '🇸🇬 Singapore (+65)'),
    ('+60', '🇲🇾 Malaysia (+60)'),
    ('+63', '🇵🇭 Philippines (+63)'),
    ('+84', '🇻🇳 Vietnam (+84)'),
    ('+92', '🇵🇰 Pakistan (+92)'),
    ('+880', '🇧🇩 Bangladesh (+880)'),
    ('+98', '🇮🇷 Iran (+98)'),
    ('+353', '🇮🇪 Ireland (+353)'),
    ('+64', '🇳🇿 New Zealand (+64)'),
    ('+351', '🇵🇹 Portugal (+351)'),
    ('+30', '🇬🇷 Greece (+30)'),
    ('+32', '🇧🇪 Belgium (+32)'),
    ('+420', '🇨🇿 Czech Republic (+420)'),
    ('+40', '🇷🇴 Romania (+40)'),
    ('+46', '🇸🇪 Sweden (+46)'),
    ('+43', '🇦🇹 Austria (+43)'),
    ('+45', '🇩�� Denmark (+45)'),
    ('+358', '🇫🇮 Finland (+358)'),
    ('+47', '🇳🇴 Norway (+47)'),
    ('+36', '🇭🇺 Hungary (+36)'),
    ('+971', '🇦🇪 UAE (+971)'),
    ('+974', '🇶🇦 Qatar (+974)'),
    ('+965', '🇰🇼 Kuwait (+965)'),
    ('+962', '🇯🇴 Jordan (+962)'),
    ('+961', '🇱🇧 Lebanon (+961)'),
    ('+254', '🇰🇪 Kenya (+254)'),
    ('+233', '🇬🇭 Ghana (+233)'),
    ('+256', '🇺🇬 Uganda (+256)'),
    ('+255', '🇹🇿 Tanzania (+255)'),
    ('+216', '🇹🇳 Tunisia (+216)'),
    ('+212', '🇲🇦 Morocco (+212)'),
    ('+213', '🇩🇿 Algeria (+213)'),
    ('+251', '🇪🇹 Ethiopia (+251)'),
    ('+260', '🇿🇲 Zambia (+260)'),
    ('+263', '🇿🇼 Zimbabwe (+263)'),
    ('+244', '🇦🇴 Angola (+244)'),
    ('+258', '🇲🇿 Mozambique (+258)'),
    ('+225', '🇨🇮 Ivory Coast (+225)'),
    ('+237', '🇨🇲 Cameroon (+237)'),
    ('+242', '🇨🇬 Congo (+242)'),
    ('+221', '🇸🇳 Senegal (+221)'),
    ('+230', '🇲🇺 Mauritius (+230)'),
    ('+52', '🇲🇽 Mexico (+52)'),
    ('+506', '🇨🇷 Costa Rica (+506)'),
    ('+507', '🇵🇦 Panama (+507)'),
    ('+51', '🇵🇪 Peru (+51)'),
    ('+56', '🇨🇱 Chile (+56)'),
    ('+57', '🇨🇴 Colombia (+57)'),
    ('+58', '🇻🇪 Venezuela (+58)'),
    ('+54', '🇦🇷 Argentina (+54)'),
    ('+593', '🇪🇨 Ecuador (+593)'),
    ('+595', '🇵🇾 Paraguay (+595)'),
    ('+598', '🇺🇾 Uruguay (+598)'),
    ('+591', '🇧🇴 Bolivia (+591)'),
    ('+94', '🇱🇰 Sri Lanka (+94)'),
    ('+95', '🇲🇲 Myanmar (+95)'),
    ('+977', '🇳🇵 Nepal (+977)'),
    ('+93', '🇦🇫 Afghanistan (+93)'),
    ('+996', '🇰🇬 Kyrgyzstan (+996)'),
    ('+992', '🇹🇯 Tajikistan (+992)'),
    ('+998', '🇺🇿 Uzbekistan (+998)'),
    ('+994', '🇦🇿 Azerbaijan (+994)'),
    ('+995', '🇬🇪 Georgia (+995)'),
    ('+374', '🇦🇲 Armenia (+374)'),
    ('+380', '🇺🇦 Ukraine (+380)'),
    ('+375', '🇧🇾 Belarus (+375)'),
    ('+370', '🇱🇹 Lithuania (+370)'),
    ('+371', '🇱🇻 Latvia (+371)'),
    ('+372', '🇪🇪 Estonia (+372)'),
    ('+373', '🇲🇩 Moldova (+373)'),
    ('+381', '🇷🇸 Serbia (+381)'),
    ('+385', '🇭🇷 Croatia (+385)'),
    ('+386', '🇸🇮 Slovenia (+386)'),
    ('+387', '🇧🇦 Bosnia (+387)'),
    ('+382', '🇲🇪 Montenegro (+382)'),
    ('+383', '🇽🇰 Kosovo (+383)'),
    ('+389', '🇲🇰 North Macedonia (+389)'),
    ('+355', '🇦🇱 Albania (+355)'),
    ('+359', '🇧🇬 Bulgaria (+359)'),
]


def normalize_phone_to_e164(phone_number, country_code='+44'):
    """
    Normalize phone number to E.164 format for Twilio

    E.164 Format: +[country code][subscriber number]
    - ALWAYS requires + prefix
    - Maximum 15 digits total
    - UK numbers: Remove leading 0 from local format

    Args:
        phone_number (str): Raw phone number from user input
        country_code (str): Country code with + prefix (default +44 for UK)

    Returns:
        str: E.164 formatted number (e.g., +447123456789) or None if invalid

    Examples:
        normalize_phone_to_e164('7123456789', '+44') → '+447123456789'
        normalize_phone_to_e164('07123456789', '+44') → '+447123456789'
        normalize_phone_to_e164('+447123456789', '+44') → '+447123456789'
        normalize_phone_to_e164('9876543210', '+91') → '+919876543210'
        normalize_phone_to_e164('09876543210', '+91') → '+919876543210'
    """
    if not phone_number:
        return None

    # Remove all spaces, dashes, parentheses, dots
    phone = str(phone_number).strip()
    phone = re.sub(r'[\s\-\(\)\.]', '', phone)

    # Already in E.164 format (starts with +)
    if phone.startswith('+'):
        return phone

    # Remove 00 prefix (international dialing format)
    # e.g., 0091 → 91, then we'll add the + prefix
    if phone.startswith('00'):
        return '+' + phone[2:]

    # Remove leading 0 (local dialing format)
    # e.g., UK: 07123456789 → 7123456789
    if phone.startswith('0'):
        phone = phone[1:]

    # Combine country code + cleaned number
    e164_number = f"{country_code}{phone}"

    return e164_number


def validate_phone_number(phone_number):
    """
    Validate phone number format for Twilio E.164

    Rules:
    - Must start with +
    - Must contain only digits after +
    - Must be between 8 and 15 digits (country code + number)
    - Cannot contain letters or special characters

    Args:
        phone_number (str): Phone number to validate

    Returns:
        tuple: (is_valid: bool, error_message: str or None)

    Examples:
        validate_phone_number('+447123456789') → (True, None)
        validate_phone_number('+91987654321') → (True, None)
        validate_phone_number('07123456789') → (False, 'Phone number must start with + and country code')
        validate_phone_number('+44abc123') → (False, 'Phone number contains invalid characters')
        validate_phone_number('+4471234') → (False, 'Phone number is too short')
    """
    if not phone_number:
        return False, "Phone number is required"

    phone = str(phone_number).strip()

    # Must start with +
    if not phone.startswith('+'):
        return False, "Phone number must start with + and country code (e.g., +447123456789)"

    # Remove + for validation
    number_part = phone[1:]

    # Must contain only digits
    if not number_part.isdigit():
        return False, "Phone number contains invalid characters. Only digits allowed after +"

    # Must be between 8 and 15 digits (E.164 standard)
    if len(number_part) < 8:
        return False, "Phone number is too short (minimum 8 digits after country code)"

    if len(number_part) > 15:
        return False, "Phone number is too long (maximum 15 digits total)"

    return True, None


def get_country_codes_for_template():
    """
    Return country codes list formatted for Django template dropdown

    Returns:
        list: List of tuples (country_code, display_name)
    """
    return COUNTRY_CODES
