"""
Environment variables for Pickarooms Django project
Fill in the actual values for production use
"""

import os

# =========================
# Django Core Settings
# =========================
os.environ.setdefault('SECRET_KEY', 'vs8(r)o$z8ccn=ctmo6y*6*_1#*yu)9mg7epxog492!zms+95i')
os.environ.setdefault('DEBUG', 'True')  # Set to 'False' in production
os.environ.setdefault('ALLOWED_HOSTS', '127.0.0.1,localhost,.herokuapp.com,pickarooms-495ab160017c.herokuapp.com,www.pickarooms.com,pickarooms.com')

# =========================
# Database Configuration (PostgreSQL)
# =========================
# Option 1: Use DATABASE_URL (for Heroku/production)
# os.environ.setdefault('DATABASE_URL', 'postgres://user:password@host:port/database')

# Option 2: Use individual database settings (for local development)
os.environ.setdefault('DATABASE_NAME', 'guest_checkin')
os.environ.setdefault('DATABASE_USER', 'checkin_user')
os.environ.setdefault('DATABASE_PASSWORD', 'Ifeoma123*')
os.environ.setdefault('DATABASE_HOST', '127.0.0.1')
os.environ.setdefault('DATABASE_PORT', '5432')

# =========================
# Google Maps API
# =========================
os.environ.setdefault('GOOGLE_MAPS_API_KEY', 'your_google_maps_api_key_here')

# =========================
# TTLock / Sciener API Configuration
# =========================
os.environ.setdefault('SCIENER_CLIENT_ID', 'a599a704ba2c4d41969b2c75408ead2b')
os.environ.setdefault('SCIENER_CLIENT_SECRET', 'd1f5f0ab5576c708502b9f51f31babd0')
os.environ.setdefault('SCIENER_ACCESS_TOKEN', 'f998166fb628f555c29fb2a8eeb89f38')
os.environ.setdefault('SCIENER_REFRESH_TOKEN', '196259dbe2977821578b3188bb75539a')
os.environ.setdefault('TTLOCK_BASE_URL', 'https://euapi.sciener.com/v3')
os.environ.setdefault('TTLOCK_OAUTH_BASE_URL', 'https://euapi.sciener.com')
os.environ.setdefault('TTLOCK_CALLBACK_URL', 'https://pickarooms-495ab160017c.herokuapp.com/api/callback')

# =========================
# Ticketmaster API Configuration
# =========================
os.environ.setdefault('TICKETMASTER_CONSUMER_KEY', 'your_ticketmaster_consumer_key_here')
os.environ.setdefault('TICKETMASTER_CONSUMER_SECRET', 'your_ticketmaster_consumer_secret_here')

# =========================
# Twilio SMS Configuration
# =========================
os.environ.setdefault('TWILIO_ACCOUNT_SID', 'your_twilio_account_sid_here')
os.environ.setdefault('TWILIO_AUTH_TOKEN', 'your_twilio_auth_token_here')
os.environ.setdefault('TWILIO_PHONE_NUMBER', 'your_twilio_phone_number_here')  # Format: +1234567890
os.environ.setdefault('ADMIN_PHONE_NUMBER', 'your_admin_phone_number_here')  # Format: +1234567890

# =========================
# IPGeolocation API
# =========================
os.environ.setdefault('IPGEOLOCATION_API_KEY', 'your_ipgeolocation_api_key_here')

# =========================
# Email Configuration (Gmail SMTP)
# =========================
os.environ.setdefault('EMAIL_HOST_USER', 'your_email@gmail.com')
os.environ.setdefault('EMAIL_HOST_PASSWORD', 'your_gmail_app_password_here')  # Use App Password, not regular password

# =========================
# Google reCAPTCHA Configuration
# =========================
os.environ.setdefault('RECAPTCHA_PUBLIC_KEY', 'your_recaptcha_public_key_here')
os.environ.setdefault('RECAPTCHA_PRIVATE_KEY', 'your_recaptcha_private_key_here')

# =========================
# Cloudinary Configuration (Image/File Storage)
# =========================
os.environ.setdefault('CLOUDINARY_CLOUD_NAME', 'dkqpb7vwr')
os.environ.setdefault('CLOUDINARY_API_KEY', '475218196462836')
os.environ.setdefault('CLOUDINARY_API_SECRET', 'VDsDshXBr9rZAWrPMxDStqCNwhc')

# =========================
# NOTES:
# =========================
# 1. For Gmail: Enable 2FA and create an App Password at https://myaccount.google.com/apppasswords
# 2. For Cloudinary: Sign up at https://cloudinary.com/ and get your credentials
# 3. For Twilio: Sign up at https://www.twilio.com/ for SMS service
# 4. For TTLock: Contact Sciener for API access
# 5. For Ticketmaster: Register at https://developer.ticketmaster.com/
# 6. For reCAPTCHA: Get keys at https://www.google.com/recaptcha/admin
# 7. For IPGeolocation: Sign up at https://ipgeolocation.io/
# 8. This file should be added to .gitignore to keep secrets safe!
