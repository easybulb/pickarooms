# PickARooms - Intelligent Hotel Management System

**A sophisticated Django-based hotel management platform with automated guest check-in, multi-source reservation enrichment, smart lock integration, dynamic pricing, and comprehensive analytics.**

[![Django](https://img.shields.io/badge/Django-5.1.5-green.svg)](https://www.djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Latest-blue.svg)](https://www.postgresql.org/)
[![Heroku](https://img.shields.io/badge/Deployed%20on-Heroku-purple.svg)](https://www.heroku.com/)

---

## 📑 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [System Architecture](#-system-architecture)
- [Core Systems](#-core-systems)
- [Tech Stack](#-tech-stack)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Deployment](#-deployment)
- [Documentation](#-documentation)
- [API Integrations](#-api-integrations)
- [Security](#-security)
- [Contributing](#-contributing)

---

## 🎯 Overview

PickARooms is an enterprise-grade hotel management system that automates the entire guest lifecycle—from reservation syncing and enrichment to check-in and smart lock access. Built with Django 5.1.5, it seamlessly integrates with Booking.com, Airbnb, Gmail, and smart lock systems to provide a fully automated, contactless guest experience.

### What Makes PickARooms Unique?

- **Multi-Source Data Enrichment**: Automatically syncs and enriches reservations from iCal feeds, email confirmations, and XLS uploads
- **Intelligent Collision Detection**: Prevents duplicate reservations using sophisticated matching algorithms
- **Smart Reconciliation**: XLS uploads automatically fix mistakes, restore cancelled bookings, and maintain data integrity
- **Dynamic Pricing**: Ticketmaster event-based pricing suggestions with automatic SMS/email alerts
- **Contactless Experience**: Fully automated check-in with QR codes and smart lock PIN generation
- **Real-time Analytics**: Comprehensive dashboards tracking enrichment status, check-ins, and revenue

---

## 🌟 Key Features

### Guest Management
- ✅ **Self-Service Check-in**: Multi-language check-in portal with ID upload and verification
- ✅ **Smart Lock Integration**: Automated PIN generation for TTLock smart locks
- ✅ **QR Code Check-in**: Scan and check-in with unique guest QR codes
- ✅ **Guest Portal**: Personal dashboard with reservation details, PINs, and property info
- ✅ **Multi-language Support**: 10 languages (English, French, German, Spanish, Chinese, Italian, Portuguese, Arabic, Japanese, Hindi)

### Reservation Management
- ✅ **Multi-Platform Sync**: iCal sync from Booking.com and Airbnb (every 15 minutes)
- ✅ **Email Enrichment**: Automatic Gmail parsing to extract booking references
- ✅ **XLS Upload**: Single source of truth with smart reconciliation
- ✅ **Collision Detection**: Prevents duplicate reservations across all platforms
- ✅ **Auto-Correction**: Deletes wrong assignments, restores cancelled victims
- ✅ **Enrichment Workflow**: 3-stage enrichment (iCal → Email → XLS)

### Admin Features
- ✅ **Comprehensive Dashboard**: Real-time view of all reservations and enrichment status
- ✅ **Last Upload Analysis**: Detailed report of XLS upload actions (deletions, restorations, fixes)
- ✅ **Bulk Operations**: Batch check-in, PIN generation, email sending
- ✅ **Review Management**: Import and display guest reviews from Booking.com
- ✅ **Audit Logging**: Track all admin actions with timestamps and user info
- ✅ **SMS Commands**: Remote property management via SMS (unlock doors, check status)

### Pricing & Events
- ✅ **Ticketmaster Integration**: Track events at priority venues (Co-op Live, AO Arena, etc.)
- ✅ **Dynamic Pricing**: Event-based price suggestions with priority alerts
- ✅ **Automated Alerts**: SMS/email notifications for high-demand dates
- ✅ **Polling System**: Automatic event checking every 10 minutes
- ✅ **Priority Scoring**: Custom algorithms for event popularity and relevance

### Automation
- ✅ **Celery Beat Tasks**: Scheduled jobs for iCal sync, email parsing, event polling
- ✅ **Background Workers**: Asynchronous task processing with Celery
- ✅ **Auto-Enrichment**: Trigger enrichment workflow when new reservations detected
- ✅ **Email Monitoring**: Continuous Gmail scanning for booking confirmations
- ✅ **Cancellation Detection**: Automatic handling of cancelled reservations

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        External Sources                          │
├──────────────┬──────────────┬──────────────┬───────────────────┤
│  Booking.com │   Airbnb     │    Gmail     │  Manual XLS Upload │
│  iCal Feed   │  iCal Feed   │ Confirmation │   (Booking.com)    │
└──────┬───────┴──────┬───────┴──────┬───────┴──────┬────────────┘
       │              │              │              │
       v              v              v              v
┌─────────────────────────────────────────────────────────────────┐
│                     PickARooms Platform                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │            Reservation Enrichment Pipeline               │   │
│  │                                                           │   │
│  │  1. iCal Sync (Every 15 min)                            │   │
│  │     - Fetch Booking.com + Airbnb feeds                  │   │
│  │     - Create placeholder reservations                    │   │
│  │     - Collision detection (prevent duplicates)           │   │
│  │     - Trigger enrichment workflow                        │   │
│  │                                                           │   │
│  │  2. Email Parser (Continuous)                            │   │
│  │     - Scan Gmail for booking confirmations              │   │
│  │     - Extract booking references (10 digits)             │   │
│  │     - Match to existing reservations                     │   │
│  │     - Update with enriched data                          │   │
│  │                                                           │   │
│  │  3. XLS Upload (Manual/On-Demand)                        │   │
│  │     - Smart reconciliation (Option B++)                  │   │
│  │     - Delete wrong assignments                           │   │
│  │     - Restore cancelled victims                          │   │
│  │     - Update status (cancelled → confirmed)              │   │
│  │     - Generate analysis report                           │   │
│  │                                                           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Core Business Logic                         │   │
│  │                                                           │   │
│  │  • Guest Check-in Flow                                   │   │
│  │  • Smart Lock PIN Generation (TTLock API)               │   │
│  │  • QR Code Generation & Validation                       │   │
│  │  • Email/SMS Notifications (Twilio + Gmail)              │   │
│  │  • Dynamic Pricing (Ticketmaster Events)                 │   │
│  │  • Review Management                                      │   │
│  │  • Audit Logging                                          │   │
│  │                                                           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │             Background Tasks (Celery Beat)               │   │
│  │                                                           │   │
│  │  • iCal Sync: Every 15 minutes                           │   │
│  │  • Email Parser: Continuous polling                      │   │
│  │  • Ticketmaster Polling: Every 10 minutes                │   │
│  │  • Enrichment Workflow: Triggered on new reservations    │   │
│  │                                                           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔧 Core Systems

### 1. Reservation Enrichment System

**The Heart of PickARooms**: A sophisticated 3-stage enrichment pipeline that combines data from multiple sources to create complete guest records.

#### Stage 1: iCal Sync
```python
# Runs every 15 minutes via Celery Beat
# File: main/services/ical_service.py

Features:
• Fetches iCal feeds from Booking.com and Airbnb
• Creates placeholder reservations with basic info
• Collision detection (Method 1, 2, 3) prevents duplicates
• Preserves XLS-enriched data during updates
• Triggers enrichment workflow for new bookings
```

#### Stage 2: Email Parser
```python
# Continuous Gmail monitoring
# File: main/services/email_parser.py

Features:
• Scans Gmail for booking confirmations
• Extracts 10-digit booking references from subjects
• Matches to existing reservations by reference + dates
• Updates with guest name and confirmation details
• Handles multi-room bookings
```

#### Stage 3: XLS Upload
```python
# Manual upload from Booking.com
# File: main/services/xls_parser.py

Features:
• Smart reconciliation (Option B++)
• Deletes wrong room assignments (if guest not checked in)
• Restores cancelled victims when rooms freed
• Updates status (cancelled → confirmed if XLS says ok)
• Generates detailed analysis report
• File age detection (FRESH/OLD/DUPLICATE)
```

**Documentation**: See [docs/XLS_UPLOAD_SYSTEM_UPDATE.md](docs/XLS_UPLOAD_SYSTEM_UPDATE.md) and [docs/ICAL_SYNC_REVAMP.md](docs/ICAL_SYNC_REVAMP.md)

---

### 2. Smart Lock System

**TTLock Integration**: Automated PIN generation and smart lock management.

```python
# File: main/services/ttlock_service.py

Features:
• Generate unique PINs for guests (room + front door)
• TTLock API integration (passcode creation/deletion)
• Automatic PIN cleanup after checkout
• SMS/Email PIN delivery
• Bulk PIN generation for multiple guests
```

**Setup Guide**: See [TTLOCK_CALLBACK_CHANGE.md](TTLOCK_CALLBACK_CHANGE.md) and [ttlock_manual_instructions.md](ttlock_manual_instructions.md)

---

### 3. Dynamic Pricing System

**Ticketmaster Event-Based Pricing**: Automatically track events at priority venues and suggest dynamic pricing.

```python
# File: main/ticketmaster_tasks.py

Features:
• Poll Ticketmaster API every 10 minutes
• Track events at priority venues (Co-op Live, AO Arena, etc.)
• Priority scoring algorithm (popularity, sold out status, venue)
• Automated SMS/email alerts for high-priority events
• Date-based pricing suggestions
• Event filtering and deduplication
```

**Priority Criteria**:
- Venue = "Warehouse Project" (Manchester's premier venue)
- Popularity ≥ 80/100
- Sold out + Priority venue

---

### 4. Guest Check-in System

**Contactless Check-in**: Multi-language self-service portal.

```python
# File: main/views/guest_checkin.py

Flow:
1. Guest receives check-in link via email/SMS
2. Select language (10 options)
3. Upload ID photo (Cloudinary)
4. Review reservation details
5. Confirm check-in
6. Receive PINs (room + front door)
7. Access guest portal
```

**Supported Languages**: EN, FR, DE, ES, ZH, IT, PT, AR, JA, HI

---

### 5. Admin Dashboard

**Comprehensive Management Interface**: Real-time view of all operations.

```python
# File: main/views/admin_dashboard.py

Features:
• Reservation list with enrichment status
• Bulk operations (check-in, PIN generation, emails)
• Last Upload Analysis (XLS actions breakdown)
• Search and filtering
• Audit log viewer
• SMS command interface
• Review management
```

---

## 🛠️ Tech Stack

### Backend
- **Framework**: Django 5.1.5
- **Language**: Python 3.13
- **Database**: PostgreSQL (Heroku Postgres Essential-0)
- **ORM**: Django ORM with JSONField support
- **Task Queue**: Celery 5.4.0
- **Task Scheduler**: Celery Beat
- **Message Broker**: Redis 5.2.1 (via Heroku Redis)

### Frontend
- **Templates**: Django Templates (Jinja2-style)
- **CSS**: Custom CSS with responsive design
- **JavaScript**: Vanilla JS (no frameworks)
- **Icons**: Unicode emojis + custom SVG

### APIs & Integrations
- **Smart Locks**: TTLock/Sciener API (v3)
- **SMS**: Twilio API
- **Email**: Gmail SMTP + Gmail API
- **Events**: Ticketmaster Discovery API
- **Storage**: Cloudinary (image uploads)
- **iCal**: icalendar 6.1.0 (Booking.com, Airbnb feeds)
- **Security**: Google reCAPTCHA v2

### Infrastructure
- **Hosting**: Heroku (Web + Worker dynos)
- **Server**: Gunicorn 23.0.0
- **Static Files**: WhiteNoise 6.8.2
- **Caching**: Redis (via channels-redis)
- **Logging**: Python logging + Heroku logs

### Data Processing
- **Excel/XLS**: pandas 2.2.3 + openpyxl 3.1.5 + xlrd 2.0.1
- **CSV**: Django CSV import/export
- **JSON**: Native Python json + JSONField

---

## 📦 Installation

### Prerequisites

- Python 3.13+
- PostgreSQL 13+
- Redis 5+
- Git
- Heroku CLI (for production deployment)

### Local Development Setup

#### 1. Clone Repository

```bash
git clone https://github.com/easybulb/pickarooms.git
cd pickarooms
```

#### 2. Create Virtual Environment

```bash
python -m venv venv

# Windows
.\venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

#### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

#### 4. Set Up Environment Variables

```bash
# Copy example file
cp env.py.example env.py

# Edit env.py with your credentials
# IMPORTANT: Never commit env.py to git!
```

**Required Variables**:
```python
# Django
SECRET_KEY = 'your-secret-key-here'
DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1']

# Database
DATABASE_URL = 'postgresql://user:password@localhost:5432/pickarooms'

# Cloudinary
CLOUDINARY_CLOUD_NAME = 'your-cloud-name'
CLOUDINARY_API_KEY = 'your-api-key'
CLOUDINARY_API_SECRET = 'your-api-secret'

# TTLock
TTLOCK_CLIENT_ID = 'your-client-id'
TTLOCK_CLIENT_SECRET = 'your-client-secret'
TTLOCK_USERNAME = 'your-username'
TTLOCK_PASSWORD = 'your-md5-password'

# Twilio (optional)
TWILIO_ACCOUNT_SID = 'your-sid'
TWILIO_AUTH_TOKEN = 'your-token'
TWILIO_PHONE_NUMBER = '+1234567890'

# Gmail (optional)
EMAIL_HOST_USER = 'your-email@gmail.com'
EMAIL_HOST_PASSWORD = 'your-app-password'

# Ticketmaster (optional)
TICKETMASTER_API_KEY = 'your-api-key'
```

#### 5. Set Up PostgreSQL Database

```sql
CREATE DATABASE pickarooms;
CREATE USER pickarooms_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE pickarooms TO pickarooms_user;
GRANT ALL PRIVILEGES ON SCHEMA public TO pickarooms_user;
ALTER SCHEMA public OWNER TO pickarooms_user;
```

Update `env.py` with database credentials.

#### 6. Run Migrations

```bash
python manage.py migrate
```

#### 7. Create Superuser

```bash
python manage.py createsuperuser
```

#### 8. Collect Static Files

```bash
python manage.py collectstatic
```

#### 9. Run Development Server

```bash
python manage.py runserver
```

Visit `http://localhost:8000` to see your application!

#### 10. Run Celery Worker (Optional - for background tasks)

**Terminal 1** (Redis):
```bash
redis-server
```

**Terminal 2** (Celery Worker):
```bash
celery -A pickarooms worker --loglevel=info
```

**Terminal 3** (Celery Beat):
```bash
celery -A pickarooms beat --loglevel=info
```

---

## ⚙️ Configuration

### iCal Feed Setup

Configure iCal URLs for each room in Django admin:

1. Go to `/admin/`
2. Navigate to **Room iCal Configs**
3. Add configuration:
   - **Room**: Select room
   - **Booking.com iCal URL**: Paste iCal feed URL
   - **Booking Active**: Check to enable
   - **Airbnb iCal URL**: Paste iCal feed URL (if applicable)
   - **Airbnb Active**: Check to enable

**Where to find iCal URLs**:
- **Booking.com**: Extranet → Calendar → Export Calendar → Copy iCal link
- **Airbnb**: Calendar → Availability Settings → Export Calendar → Copy link

### Gmail API Setup

Enable Gmail API for email enrichment:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create new project or select existing
3. Enable Gmail API
4. Create OAuth 2.0 credentials
5. Download `credentials.json`
6. Place in project root
7. Run authentication flow (first time only):
   ```bash
   python manage.py shell
   >>> from main.services.email_parser import authenticate_gmail
   >>> authenticate_gmail()
   ```

### TTLock Setup

See detailed guides:
- [TTLOCK_CALLBACK_CHANGE.md](TTLOCK_CALLBACK_CHANGE.md)
- [ttlock_manual_instructions.md](ttlock_manual_instructions.md)

---

## 🚀 Deployment

### Heroku Deployment

#### 1. Login to Heroku

```bash
heroku login
```

#### 2. Create Heroku App

```bash
heroku create pickarooms
```

#### 3. Add PostgreSQL

```bash
heroku addons:create heroku-postgresql:essential-0
```

#### 4. Add Redis

```bash
heroku addons:create heroku-redis:mini
```

#### 5. Set Environment Variables

```bash
heroku config:set SECRET_KEY="your-secret-key"
heroku config:set DEBUG=False
heroku config:set CLOUDINARY_CLOUD_NAME="your-cloud-name"
heroku config:set CLOUDINARY_API_KEY="your-api-key"
heroku config:set CLOUDINARY_API_SECRET="your-api-secret"
# ... set all other variables from env.py
```

**Quick Setup** (from env.py):
```bash
# Extract and set all variables at once
heroku config:set $(cat env.py | grep '=' | grep -v '#' | sed 's/ //g')
```

#### 6. Deploy

```bash
git push heroku main
```

#### 7. Run Migrations

```bash
heroku run python manage.py migrate
```

#### 8. Create Superuser

```bash
heroku run python manage.py createsuperuser
```

#### 9. Scale Dynos

```bash
# Web dyno (required)
heroku ps:scale web=1

# Worker dyno (required for background tasks)
heroku ps:scale worker=1

# Beat dyno (required for scheduled tasks)
heroku ps:scale beat=1
```

#### 10. View Logs

```bash
heroku logs --tail
```

### Production Checklist

- [ ] Set `DEBUG=False`
- [ ] Configure `ALLOWED_HOSTS` with your domain
- [ ] Set strong `SECRET_KEY`
- [ ] Enable HTTPS (automatic on Heroku)
- [ ] Set up custom domain (optional)
- [ ] Configure backups for PostgreSQL
- [ ] Set up monitoring (Heroku metrics)
- [ ] Test all integrations (TTLock, Twilio, Gmail, Ticketmaster)
- [ ] Upload initial XLS file
- [ ] Verify iCal sync working (check logs after 15 min)
- [ ] Test guest check-in flow
- [ ] Verify PIN generation working

---

## 📖 Documentation

### System Documentation

- **[XLS Upload System](docs/XLS_UPLOAD_SYSTEM_UPDATE.md)**: Smart reconciliation, collision handling, analysis
- **[iCal Sync System](docs/ICAL_SYNC_REVAMP.md)**: Multi-source sync, collision detection, enrichment workflow
- **[TTLock Callback Setup](TTLOCK_CALLBACK_CHANGE.md)**: Webhook configuration for smart locks
- **[TTLock Manual Instructions](ttlock_manual_instructions.md)**: Step-by-step TTLock integration guide
- **[Deployment Success Guide](DEPLOYMENT_SUCCESS.md)**: Production deployment checklist

### Management Commands

```bash
# Nuclear reset (delete all reservations)
heroku run python manage.py nuclear_reset_reservations

# Cleanup empty bookings
heroku run python manage.py cleanup_empty_bookings

# Trigger iCal sync manually
heroku run python manage.py shell
>>> from main.tasks import sync_all_ical_feeds
>>> sync_all_ical_feeds()
```

### Diagnostic Scripts

```bash
# Check unenriched reservations
python check_future_unenriched.py

# Analyze unenriched reservations
python analyze_unenriched_reservations.py

# Delete unenriched without booking ref
python delete_unenriched_no_booking_ref.py

# Clear all reservation data (nuclear option)
python clear_all_reservation_data.py
```

---

## 🔌 API Integrations

### TTLock/Sciener API

**Purpose**: Smart lock PIN generation and management

**Endpoints Used**:
- `/v3/lock/listLock` - Get all locks
- `/v3/keyboardPwd/add` - Create passcode
- `/v3/keyboardPwd/delete` - Delete passcode
- `/v3/lock/unlock` - Remote unlock

**Rate Limits**: 100 requests/minute

**Documentation**: [TTLock API Docs](https://open.ttlock.com/)

### Twilio API

**Purpose**: SMS notifications (check-in links, PINs, alerts)

**Features**:
- Send check-in links
- Deliver PINs
- Price suggester alerts
- SMS commands (unlock, status check)

**Documentation**: [Twilio Docs](https://www.twilio.com/docs)

### Gmail API

**Purpose**: Email monitoring and enrichment

**Features**:
- Parse booking confirmations
- Extract booking references
- Match to reservations
- Send check-in emails

**Authentication**: OAuth 2.0 with `credentials.json` and `tokens.json`

**Documentation**: [Gmail API Docs](https://developers.google.com/gmail/api)

### Ticketmaster Discovery API

**Purpose**: Event tracking for dynamic pricing

**Endpoints Used**:
- `/discovery/v2/events.json` - Search events by date range and venue

**Features**:
- Poll every 10 minutes
- Filter by Manchester venues
- Calculate priority scores
- Send alerts for high-priority events

**Documentation**: [Ticketmaster API Docs](https://developer.ticketmaster.com/)

### Cloudinary API

**Purpose**: Image storage and management

**Features**:
- Guest ID uploads
- Room images
- Automatic optimization
- CDN delivery

**Documentation**: [Cloudinary Docs](https://cloudinary.com/documentation)

---

## 🔒 Security

### Sensitive Files (Never Commit!)

```
env.py                    # All API keys and secrets
main/tokens.json          # Gmail OAuth tokens
credentials.json          # Google API credentials
db.sqlite3               # Local database (use PostgreSQL in prod)
*.pyc                    # Python bytecode
__pycache__/             # Python cache
```

### Security Best Practices

- ✅ Use strong, unique `SECRET_KEY` (50+ random characters)
- ✅ Set `DEBUG=False` in production
- ✅ Use environment variables for all secrets
- ✅ Enable HTTPS (automatic on Heroku)
- ✅ Use Django's built-in CSRF protection
- ✅ Implement rate limiting on public endpoints
- ✅ Sanitize user inputs (guest names, email, phone)
- ✅ Use Google reCAPTCHA on check-in forms
- ✅ Regularly update dependencies (`pip list --outdated`)
- ✅ Monitor logs for suspicious activity

### Database Security

- ✅ Use strong database passwords
- ✅ Enable SSL connections (automatic on Heroku Postgres)
- ✅ Regular backups (Heroku Postgres automatic backups)
- ✅ Limit database access to application only
- ✅ Use database connection pooling

---

## 🎯 Project Structure

```
pickarooms/
├── main/                           # Main Django app
│   ├── management/
│   │   └── commands/
│   │       ├── nuclear_reset_reservations.py
│   │       └── cleanup_empty_bookings.py
│   ├── migrations/                 # Database migrations
│   ├── services/                   # Business logic layer
│   │   ├── ical_service.py        # iCal sync + collision detection
│   │   ├── xls_parser.py          # XLS upload + reconciliation
│   │   ├── email_parser.py        # Gmail parsing + enrichment
│   │   ├── ttlock_service.py      # Smart lock integration
│   │   └── sms_commands.py        # SMS command handler
│   ├── templates/
│   │   └── main/
│   │       ├── admin_dashboard.html
│   │       ├── guest_checkin.html
│   │       ├── xls_upload.html
│   │       └── ...
│   ├── views/
│   │   ├── admin_dashboard.py      # Admin interface
│   │   ├── guest_checkin.py        # Guest check-in flow
│   │   ├── enrichment.py           # XLS upload + analysis
│   │   └── ...
│   ├── models.py                   # Database models
│   ├── tasks.py                    # Celery tasks
│   ├── ticketmaster_tasks.py       # Event polling + pricing
│   ├── urls.py                     # URL routing
│   ├── admin.py                    # Django admin config
│   └── middleware.py               # Custom middleware
├── pickarooms/                     # Project settings
│   ├── settings.py                 # Django configuration
│   ├── celery.py                   # Celery configuration
│   ├── urls.py                     # Root URL config
│   └── wsgi.py                     # WSGI entry point
├── static/                         # Static files
│   ├── css/
│   │   ├── admin_dashboard.css
│   │   ├── guest_checkin.css
│   │   ├── xls_upload.css
│   │   └── ...
│   ├── js/
│   └── images/
├── templates/                      # Global templates
│   └── base.html
├── docs/                           # Documentation
│   ├── XLS_UPLOAD_SYSTEM_UPDATE.md
│   ├── ICAL_SYNC_REVAMP.md
│   └── ...
├── locale/                         # Translation files
│   ├── fr/
│   ├── de/
│   ├── es/
│   └── ...
├── requirements.txt                # Python dependencies
├── Procfile                        # Heroku process types
├── runtime.txt                     # Python version
├── manage.py                       # Django management
└── README.md                       # This file
```

---

## 🤝 Contributing

### Development Workflow

1. **Fork the repository**
   ```bash
   git clone https://github.com/easybulb/pickarooms.git
   cd pickarooms
   ```

2. **Create feature branch**
   ```bash
   git checkout -b feature/amazing-feature
   ```

3. **Make changes**
   - Write clean, documented code
   - Follow Django best practices
   - Add tests if applicable

4. **Test locally**
   ```bash
   python manage.py test
   python manage.py runserver
   ```

5. **Commit changes**
   ```bash
   git add .
   git commit -m "Add amazing feature"
   ```

6. **Push to branch**
   ```bash
   git push origin feature/amazing-feature
   ```

7. **Open Pull Request**
   - Provide clear description
   - Reference any related issues
   - Wait for review

### Code Standards

- **Python**: PEP 8 style guide
- **Django**: Follow Django coding style
- **Comments**: Document complex logic
- **Logging**: Use appropriate log levels (DEBUG, INFO, WARNING, ERROR)
- **Error Handling**: Always catch and log exceptions

---

## 📊 Database Models

### Core Models

**Reservation**
- Represents a booking (from iCal, email, or XLS)
- Fields: booking_reference, guest_name, room, dates, status, platform, ical_uid, raw_ical_data
- Foreign Keys: room, guest (optional)

**Guest**
- Enriched guest data after check-in
- Fields: name, email, phone, check_in_date, pin_code, front_door_pin, id_image
- Foreign Keys: reservation

**Room**
- Physical rooms/properties
- Fields: name, lock_id, front_door_lock_id, capacity
- Related: room_ical_config

**RoomICalConfig**
- iCal feed configuration per room
- Fields: booking_ical_url, airbnb_ical_url, active flags, last_synced timestamps

**CSVEnrichmentLog**
- XLS upload history and analysis
- Fields: file_name, total_rows, created_count, updated_count, enrichment_summary (JSON)

**EnrichmentLog**
- Per-reservation enrichment history
- Fields: reservation, action, timestamp, details

**PendingEnrichment**
- Queue for email enrichment workflow
- Fields: reservation, priority, retry_count, last_attempted

---

## 🧪 Testing

### Run Tests

```bash
# All tests
python manage.py test

# Specific app
python manage.py test main

# Specific test case
python manage.py test main.tests.TestICalService

# With coverage
coverage run --source='.' manage.py test
coverage report
```

### Manual Testing Checklist

- [ ] iCal sync creates reservations
- [ ] Email parser enriches with booking refs
- [ ] XLS upload reconciles correctly
- [ ] Collision detection prevents duplicates
- [ ] XLS reservations not cancelled by iCal
- [ ] Guest check-in flow works
- [ ] PINs generated successfully
- [ ] Emails/SMS delivered
- [ ] Ticketmaster polling working
- [ ] Admin dashboard loads
- [ ] Last Upload Analysis displays

---

## 📞 Support & Contact

**Author**: Henry (easybulb)
- **Email**: easybulb@gmail.com
- **GitHub**: [@easybulb](https://github.com/easybulb)

**Issues**: [GitHub Issues](https://github.com/easybulb/pickarooms/issues)

**Production URL**: https://pickarooms-495ab160017c.herokuapp.com/

---

## 📝 License

This project is **private and proprietary**.

Unauthorized copying, distribution, or use is strictly prohibited.

---

## 🙏 Acknowledgments

### Technologies
- [Django](https://www.djangoproject.com/) - The web framework for perfectionists with deadlines
- [PostgreSQL](https://www.postgresql.org/) - The world's most advanced open source database
- [Celery](https://docs.celeryq.dev/) - Distributed task queue
- [Redis](https://redis.io/) - In-memory data structure store
- [Heroku](https://www.heroku.com/) - Cloud application platform

### APIs
- [TTLock/Sciener](https://open.ttlock.com/) - Smart lock integration
- [Twilio](https://www.twilio.com/) - SMS messaging
- [Cloudinary](https://cloudinary.com/) - Image management
- [Ticketmaster](https://developer.ticketmaster.com/) - Event data
- [Google Gmail API](https://developers.google.com/gmail/api) - Email automation

### Open Source Packages
- pandas, openpyxl, xlrd - Excel/XLS processing
- icalendar - iCal feed parsing
- requests - HTTP library
- Pillow - Image processing
- gunicorn - WSGI server
- whitenoise - Static file serving

---

## 🔮 Roadmap

### Planned Features
- [ ] Automated review response system
- [ ] Guest satisfaction surveys
- [ ] Revenue analytics dashboard
- [ ] Multi-property support
- [ ] Mobile app (iOS + Android)
- [ ] Channel manager integration (Expedia, Vrbo)
- [ ] Automated messaging sequences
- [ ] AI-powered pricing recommendations

### Under Consideration
- [ ] Stripe payment integration
- [ ] Housekeeping management
- [ ] Maintenance tracking
- [ ] Guest loyalty program
- [ ] Referral system

---

**🏨 PickARooms** - Automating hospitality, one check-in at a time.

**Version**: 1.0.0
**Last Updated**: November 2025
**Status**: Production ✅