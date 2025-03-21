"""
Django settings for pickarooms project.

Generated by 'django-admin startproject' using Django 5.1.5.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.1/ref/settings/
"""

import os
import dj_database_url
from pathlib import Path
from django.utils.translation import gettext_lazy as _
from django.core.files.storage import default_storage

# Import env.py if it exists
if os.path.isfile("env.py"):
    import env

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY', 'unsafe-default-key')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = os.environ.get(
    'ALLOWED_HOSTS',
    '127.0.0.1,localhost,.herokuapp.com,www.pickarooms.com,pickarooms.com'
).split(',')

GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')

# Enforce HTTPS only in production, disable for local development
if DEBUG:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
else:
    SECURE_SSL_REDIRECT = True  # Redirect HTTP to HTTPS
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True  # Cookies only sent over HTTPS
    CSRF_COOKIE_SECURE = True  # CSRF protection only works over HTTPS

# CSRF Trusted Origins (Includes Localhost and Dev Tunnels for Testing)
if DEBUG:
    CSRF_TRUSTED_ORIGINS = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "https://1ls3qkr5-8000.uks1.devtunnels.ms",
    ]
else:
    CSRF_TRUSTED_ORIGINS = [
        "https://www.pickarooms.com",
        "https://pickarooms.com",
    ]

# HTTP Strict Transport Security (HSTS) - Forces HTTPS (Only in Production)
if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000  # 1 year (recommended by Google)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True  # Apply to subdomains too
    SECURE_HSTS_PRELOAD = True  # Allow browser preload list

# TTLock API Configuration
SCIENER_CLIENT_ID = os.environ.get("SCIENER_CLIENT_ID")
SCIENER_CLIENT_SECRET = os.environ.get("SCIENER_CLIENT_SECRET")
SCIENER_ACCESS_TOKEN = os.environ.get("SCIENER_ACCESS_TOKEN")
SCIENER_REFRESH_TOKEN = os.environ.get("SCIENER_REFRESH_TOKEN")

# Validate required Sciener credentials
if not SCIENER_CLIENT_ID or not SCIENER_CLIENT_SECRET:
    raise ValueError("🚨 Sciener API credentials (client_id or client_secret) are missing in env.py!")
if not SCIENER_ACCESS_TOKEN or not SCIENER_REFRESH_TOKEN:
    raise ValueError("🚨 Sciener API tokens (access_token or refresh_token) are missing in env.py!")

TTLOCK_BASE_URL = os.environ.get("TTLOCK_BASE_URL", "https://euapi.sciener.com/v3")
TTLOCK_OAUTH_BASE_URL = os.environ.get("TTLOCK_OAUTH_BASE_URL", "https://euapi.sciener.com")  # For OAuth endpoints
TTLOCK_CALLBACK_URL = os.environ.get("TTLOCK_CALLBACK_URL", "https://pickarooms-3203aa136ccc.herokuapp.com/api/callback")

# Ticketmaster API Configuration
TICKETMASTER_CONSUMER_KEY = os.environ.get("TICKETMASTER_CONSUMER_KEY")
TICKETMASTER_CONSUMER_SECRET = os.environ.get("TICKETMASTER_CONSUMER_SECRET")

# Validate Ticketmaster credentials
if not TICKETMASTER_CONSUMER_KEY or not TICKETMASTER_CONSUMER_SECRET:
    raise ValueError("🚨 Ticketmaster API credentials (consumer_key or consumer_secret) are missing in env.py!")

# Twilio Configuration for SMS
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")

# Admin Phone Number for SMS forwarding
ADMIN_PHONE_NUMBER = os.environ.get("ADMIN_PHONE_NUMBER")

# Validate Twilio credentials and admin phone number
if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_PHONE_NUMBER:
    raise ValueError("🚨 Twilio API credentials (account_sid, auth_token, or phone_number) are missing in env.py!")
if not ADMIN_PHONE_NUMBER:
    raise ValueError("🚨 Admin phone number (ADMIN_PHONE_NUMBER) is missing in env.py!")

IPGEOLOCATION_API_KEY = os.environ.get("IPGEOLOCATION_API_KEY")

if not IPGEOLOCATION_API_KEY:
    raise ValueError("🚨 IPGeolocation API key (IPGEOLOCATION_API_KEY) is missing in env.py!")


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'ERROR',
            'class': 'logging.FileHandler',
            'filename': 'debug.log',
            'formatter': 'verbose',
        },
        'console': {
            'level': 'ERROR',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'main': {
            'handlers': ['file', 'console'],
            'level': 'ERROR',
            'propagate': False,
        },
        '': {  # Root logger
            'handlers': ['file', 'console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}


# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'main',
    'cloudinary',
    'cloudinary_storage',
]

LANGUAGE_CODE = 'en'  # Default language

# Add multiple languages (modify as needed)
LANGUAGES = [
    ('en', _('English')),
    ('fr', _('French')),
    ('de', _('German')),
    ('es', _('Spanish')),
    ('zh-hans', _('Chinese')),
    ('it', _('Italian')),
    ('pt', _('Portuguese')),
    ('ar', _('Arabic')),
    ('ja', _('Japanese')),
    ('hi', _('Hindi')),
]

USE_I18N = True  # Enable internationalization
USE_L10N = True  # Optional: Localization settings
USE_TZ = True  # Keep timezone support

LOCALE_PATHS = [os.path.join(BASE_DIR, "locale")]

# ✅ Gmail SMTP Configuration for Django
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD")
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

# ✅ reCAPTCHA Configuration
RECAPTCHA_PUBLIC_KEY = os.environ.get("RECAPTCHA_PUBLIC_KEY")
RECAPTCHA_PRIVATE_KEY = os.environ.get("RECAPTCHA_PRIVATE_KEY")

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware', # Required for language switching
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'pickarooms.middleware.restrict_staff_to_custom_admin',
    'main.middleware.PopularEventMonitorMiddleware',
]

MAJOR_VENUES = ['Co-op Live', 'AO Arena', 'Etihad Stadium', 'Old Trafford', 'Manchester Academy', 'O2 Apollo Manchester', 'O2 Ritz Manchester']

ROOT_URLCONF = 'pickarooms.urls'

# Templates settings
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],  # ✅ FIXED HERE
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                "django.template.context_processors.i18n",
                'main.context_processors.ipgeolocation_api_key',
            ],
        },
    },
]

WSGI_APPLICATION = 'pickarooms.wsgi.application'

# Database configuration
# Use DATABASE_URL if available, otherwise fall back to local PostgreSQL
if os.environ.get('DATABASE_URL'):
    DATABASES = {
        'default': dj_database_url.config(default=os.environ.get('DATABASE_URL'))
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DATABASE_NAME', 'guest_checkin'),
            'USER': os.environ.get('DATABASE_USER', 'checkin_user'),
            'PASSWORD': os.environ.get('DATABASE_PASSWORD', ''),
            'HOST': os.environ.get('DATABASE_HOST', '127.0.0.1'),
            'PORT': os.environ.get('DATABASE_PORT', '5432'),
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LOGIN_URL = '/admin/login/'  # Redirect unauthorized users to the login page

# Internationalization
LANGUAGE_CODE = 'en'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Configure Cloudinary Storage for Media Files
CLOUDINARY_STORAGE = {
    'CLOUD_NAME': os.environ.get('CLOUDINARY_CLOUD_NAME'),
    'API_KEY': os.environ.get('CLOUDINARY_API_KEY'),
    'API_SECRET': os.environ.get('CLOUDINARY_API_SECRET'),
}

# Set Default Media Storage to Cloudinary
DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'

# Media files - Remove local fallback entirely to force Cloudinary
MEDIA_URL = '/media/'
MEDIA_ROOT = None  # No local storage, rely on Cloudinary

# Debug Cloudinary config and storage backend
import cloudinary
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET')
)
print(f"Cloudinary config initialized: {cloudinary.config().cloud_name}")
print(f"Default storage backend after settings: {default_storage.__class__.__name__}")

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}