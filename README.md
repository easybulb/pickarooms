# Pickarooms - Automated Guest Check-in System

A Django-based accommodation management system with automated guest check-in, smart lock integration, and comprehensive guest management features.

## 🌟 Features

- **Automated Guest Check-in**: Self-service check-in system for guests
- **Smart Lock Integration**: TTLock API integration for automated door access
- **PIN Generation**: Automatic generation of unique PINs for room and front door access
- **Multi-language Support**: Support for 10 languages including English, French, German, Spanish, Chinese, Italian, Portuguese, Arabic, Japanese, and Hindi
- **Guest Management**: Comprehensive admin dashboard for managing reservations
- **Email & SMS Notifications**: Automated messaging via Twilio and Gmail
- **Event Tracking**: Ticketmaster integration for event-based pricing
- **Image Storage**: Cloudinary integration for guest ID uploads and room images
- **Review Management**: CSV import for guest reviews from Booking.com
- **Audit Logging**: Track all administrative actions

## 🚀 Tech Stack

- **Backend**: Django 5.1.5
- **Database**: PostgreSQL
- **Smart Locks**: TTLock/Sciener API
- **SMS**: Twilio
- **Email**: Gmail SMTP
- **Storage**: Cloudinary
- **Deployment**: Heroku
- **Server**: Gunicorn

## 📋 Prerequisites

- Python 3.13+
- PostgreSQL
- Git
- Heroku CLI (for deployment)

## 🔧 Installation

### 1. Clone the repository

```bash
git clone https://github.com/easybulb/pickarooms.git
cd pickarooms
```

### 2. Create virtual environment

```bash
python -m venv venv

# Windows
.\venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up environment variables

```bash
# Copy the example file
cp env.py.example env.py

# Edit env.py with your actual credentials
# IMPORTANT: Never commit env.py to git!
```

### 5. Set up PostgreSQL database

Create a database and user in PostgreSQL:

```sql
CREATE DATABASE guest_checkin;
CREATE USER checkin_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE guest_checkin TO checkin_user;
GRANT ALL PRIVILEGES ON SCHEMA public TO checkin_user;
ALTER SCHEMA public OWNER TO checkin_user;
```

Update your `env.py` with the database credentials.

### 6. Run migrations

```bash
python manage.py migrate
```

### 7. Create superuser

```bash
python manage.py createsuperuser
```

### 8. Collect static files

```bash
python manage.py collectstatic
```

### 9. Run development server

```bash
python manage.py runserver
```

Visit `http://localhost:8000` to see your application!

## 🔑 API Keys Required

You'll need to obtain API keys for the following services:

### Essential Services:
- **TTLock/Sciener**: For smart lock integration
- **Cloudinary**: For image storage
- **PostgreSQL**: Database

### Optional Services (for full functionality):
- **Twilio**: SMS notifications
- **Gmail**: Email notifications
- **Ticketmaster**: Event tracking
- **Google reCAPTCHA**: Form security
- **IPGeolocation**: Location services
- **Google Maps**: Map integration

See `env.py.example` for all required environment variables.

## 🚢 Deployment to Heroku

### 1. Login to Heroku

```bash
heroku login
```

### 2. Create Heroku app

```bash
heroku create your-app-name
```

### 3. Add PostgreSQL

```bash
heroku addons:create heroku-postgresql:essential-0
```

### 4. Set environment variables

```bash
heroku config:set SECRET_KEY="your-secret-key"
heroku config:set DEBUG=False
# ... set all other variables from env.py
```

### 5. Deploy

```bash
git push heroku main
```

### 6. Run migrations

```bash
heroku run python manage.py migrate
```

### 7. Create superuser

```bash
heroku run python manage.py createsuperuser
```

## 📁 Project Structure

```
pickarooms/
├── main/                      # Main application
│   ├── migrations/           # Database migrations
│   ├── management/          # Custom management commands
│   ├── templates/           # App-specific templates
│   ├── models.py            # Database models
│   ├── views.py             # Views
│   ├── urls.py              # URL routing
│   ├── forms.py             # Forms
│   ├── ttlock_utils.py      # TTLock API integration
│   └── middleware.py        # Custom middleware
├── pickarooms/               # Project settings
│   ├── settings.py          # Django settings
│   ├── urls.py              # Main URL configuration
│   └── wsgi.py              # WSGI configuration
├── templates/                # Global templates
├── static/                   # Static files (CSS, JS, images)
├── staticfiles/             # Collected static files
├── locale/                   # Translation files
├── requirements.txt         # Python dependencies
├── Procfile                 # Heroku configuration
├── runtime.txt              # Python version
└── manage.py                # Django management script
```

## 🔒 Security Notes

- **NEVER commit `env.py`** - Contains all sensitive credentials
- **NEVER commit `main/tokens.json`** - Contains API tokens
- Keep your `SECRET_KEY` secret and unique
- Use strong passwords for database and admin accounts
- Enable HTTPS in production (automatic on Heroku)
- Review the `.gitignore` file to ensure sensitive files are excluded

## 📖 Documentation

- [TTLock Callback Setup](TTLOCK_CALLBACK_CHANGE.md)
- [TTLock Manual Instructions](ttlock_manual_instructions.md)
- [Deployment Success Guide](DEPLOYMENT_SUCCESS.md)

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📝 License

This project is private and proprietary.

## 👤 Author

**Henry (easybulb)**
- Email: easybulb@gmail.com
- GitHub: [@easybulb](https://github.com/easybulb)

## 🙏 Acknowledgments

- Django framework
- TTLock/Sciener for smart lock API
- Heroku for hosting
- All the open-source packages used in this project

---

**Note**: This is a production application. Please ensure all API keys and credentials are kept secure and never committed to version control.
