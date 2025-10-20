# TTLock Integration Guide

## Overview

TTLock API integration is now fully automated with token management built directly into the Django project. No more manual token fetching with Postman!

---

## Features

✅ **Automatic Token Management** - Tokens are fetched, stored, and refreshed automatically  
✅ **Database Storage** - Tokens stored in PostgreSQL (both local and Heroku)  
✅ **Auto Refresh** - Tokens refresh automatically when expired  
✅ **Simple Usage** - One line of code to get a valid token  
✅ **Management Command** - Easy CLI for initial authentication  
✅ **Admin Interface** - View token status in Django admin  

---

## Setup

### 1. Initial Authentication

Run this command with your TTLock credentials:

```bash
python manage.py ttlock_get_token --username YOUR_EMAIL --password YOUR_PASSWORD
```

**Example:**
```bash
python manage.py ttlock_get_token --username henry@example.com --password MyPassword123
```

This will:
- Authenticate with TTLock API
- Store access_token and refresh_token in database
- Display the token and expiry information
- Provide commands to update Heroku config vars

### 2. Verify Token in Admin

Visit: `http://localhost:8000/admin/main/ttlocktoken/`

You'll see:
- Token creation date
- Expiration date
- Status (Valid/Expired)
- Token preview

---

## Usage in Code

### Simple Token Access

```python
from main.services import TTLockService

# Get a valid token (auto-refreshes if expired)
service = TTLockService()
token = service.get_valid_token()

# Use the token
print(f"Access Token: {token}")
```

### Using TTLockClient (Recommended)

The existing `TTLockClient` now automatically uses the service:

```python
from main.ttlock_utils import TTLockClient

# Client automatically gets a valid token
client = TTLockClient()

# Use client methods
locks = client.list_locks()
status = client.query_lock_status(lock_id=12345)
client.unlock_lock(lock_id=12345)
```

### Manual Refresh (Rarely Needed)

```python
from main.services import TTLockService

service = TTLockService()
refreshed_token = service.refresh_token()
print(f"New token: {refreshed_token.access_token}")
```

---

## Token Lifecycle

1. **Initial Authentication**: `python manage.py ttlock_get_token`
2. **Storage**: Token saved in `TTLockToken` model
3. **Usage**: Any code calls `service.get_valid_token()`
4. **Check**: Service checks if token expires soon (within 1 hour)
5. **Auto-Refresh**: If expiring, service automatically refreshes
6. **Return**: Always returns a valid token

---

## Management Commands

### Get New Token

```bash
python manage.py ttlock_get_token --username EMAIL --password PASSWORD
```

### Test Token (Coming Soon)

```bash
python manage.py ttlock_test_token
```

---

## Heroku Deployment

After getting tokens locally, update Heroku:

```bash
# These commands are shown after running ttlock_get_token
heroku config:set SCIENER_ACCESS_TOKEN="your_token_here" -a pickarooms
heroku config:set SCIENER_REFRESH_TOKEN="your_refresh_token_here" -a pickarooms
```

Then run migrations on Heroku:

```bash
heroku run python manage.py migrate -a pickarooms
```

And authenticate on Heroku:

```bash
heroku run python manage.py ttlock_get_token --username YOUR_EMAIL --password YOUR_PASSWORD -a pickarooms
```

---

## Database Schema

### TTLockToken Model

| Field | Type | Description |
|-------|------|-------------|
| id | Integer | Primary key |
| access_token | TextField | TTLock access token |
| refresh_token | TextField | TTLock refresh token |
| expires_at | DateTimeField | When token expires |
| created_at | DateTimeField | When token was created |
| updated_at | DateTimeField | Last update timestamp |

**Note**: Only one token is stored at a time (latest overwrites previous).

---

## Error Handling

### No Token in Database

```
ValueError: No token found in database. Please run: 
python manage.py ttlock_get_token --username YOUR_USERNAME --password YOUR_PASSWORD
```

**Solution**: Run the authentication command.

### Token Refresh Failed

```
ValueError: Token refresh failed: No access token in response
```

**Solution**: Re-authenticate with the management command.

### Authentication Failed

```
CommandError: Authentication failed: Invalid credentials
```

**Solution**: 
- Check username/password
- Verify Client ID and Secret in env.py
- Ensure TTLock account has API access

---

## Integration Examples

### In Views

```python
from main.services import TTLockService

def unlock_room_view(request, guest_id):
    service = TTLockService()
    client = service.get_client_with_token()
    
    # Use client to unlock
    result = client.unlock_lock(lock_id=12345)
    
    return JsonResponse(result)
```

### In Management Commands

```python
from main.services import TTLockService

class Command(BaseCommand):
    def handle(self, *args, **options):
        service = TTLockService()
        token = service.get_valid_token()
        
        # Use token for API calls
        self.stdout.write(f"Using token: {token[:20]}...")
```

### In Scheduled Tasks

```python
from main.services import TTLockService

def nightly_lock_check():
    service = TTLockService()
    client = service.get_client_with_token()
    
    locks = client.list_locks()
    # Process locks...
```

---

## Monitoring

### Check Token Status

```python
from main.models import TTLockToken

token = TTLockToken.get_latest()
print(f"Expires: {token.expires_at}")
print(f"Is Expired: {token.is_expired()}")
```

### View in Admin

Navigate to: `/admin/main/ttlocktoken/`

See:
- Creation and expiry dates
- Token status (Valid/Expired)
- Token preview

---

## Best Practices

1. **Never commit tokens** - They're in the database, not in code
2. **Use the service** - Always use `TTLockService` for token access
3. **Monitor expiry** - Check admin panel periodically
4. **Re-auth on issues** - If problems persist, re-authenticate
5. **Test locally first** - Verify tokens work before deploying

---

## Troubleshooting

### Token Keeps Expiring

- TTLock tokens typically last 90 days
- Auto-refresh should handle this
- If issues persist, re-authenticate

### Can't Connect to API

- Check internet connection
- Verify Client ID/Secret are correct
- Ensure TTLock API is operational

### Database Migration Issues

```bash
python manage.py makemigrations
python manage.py migrate
```

---

## API Reference

### TTLockService Methods

#### `authenticate(username, password)`
- Authenticates with TTLock
- Returns `TTLockToken` object
- Stores token in database

#### `get_valid_token()`
- Returns valid access token string
- Auto-refreshes if expired
- Raises `ValueError` if no token exists

#### `refresh_token()`
- Manually refresh the token
- Returns updated `TTLockToken` object
- Updates database

#### `get_client_with_token()`
- Returns configured `TTLockClient` instance
- Token already set
- Ready to make API calls

---

## Migration Guide

### From Old System to New

**Old Way (Manual):**
```python
client = TTLockClient()
# Token from env.py or tokens.json
```

**New Way (Automatic):**
```python
# Same code, but now tokens are managed automatically!
client = TTLockClient()
# Tokens come from database, auto-refresh
```

**Backward Compatible**: Old code still works!

---

## Summary

✅ Run `python manage.py ttlock_get_token` once  
✅ Tokens stored in database  
✅ Auto-refresh when expired  
✅ Simple one-line usage: `service.get_valid_token()`  
✅ No more manual token management!  

---

**Questions?** Check logs or contact the development team.
