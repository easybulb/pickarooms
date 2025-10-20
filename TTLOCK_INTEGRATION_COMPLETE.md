# 🎉 TTLock Integration Complete!

## ✅ What Was Implemented

### 1. **TTLockToken Model**
- Stores access_token, refresh_token, expires_at
- Database: Both local (PostgreSQL) and Heroku
- Admin interface to view token status
- Auto-overwrites old tokens (keeps only latest)

### 2. **TTLockService**
- Location: `main/services/ttlock_service.py`
- Methods:
  - `authenticate(username, password)` - Get new token
  - `get_valid_token()` - Get token, auto-refresh if expired
  - `refresh_token()` - Manual refresh
  - `get_client_with_token()` - Get configured client

### 3. **Management Command**
- Command: `python manage.py ttlock_get_token`
- Flags: `--username` and `--password`
- Stores tokens in database
- Displays Heroku update commands

### 4. **Auto-Refresh Integration**
- TTLockClient updated to use service
- Backward compatible with old code
- Tokens refresh automatically when expired (within 1 hour buffer)

### 5. **Admin Interface**
- View tokens at `/admin/main/ttlocktoken/`
- Shows status (Valid/Expired)
- Displays expiry date
- Read-only (prevents manual editing)

---

## 📦 Files Created/Modified

### Created:
- `main/models.py` - Added `TTLockToken` model
- `main/services/__init__.py` - Service module init
- `main/services/ttlock_service.py` - Token management service
- `main/management/commands/ttlock_get_token.py` - CLI command
- `main/migrations/0024_ttlocktoken.py` - Database migration
- `TTLOCK_INTEGRATION_GUIDE.md` - Complete documentation

### Modified:
- `main/admin.py` - Added TTLockToken admin
- `main/ttlock_utils.py` - Integrated with service
- `requirements.txt` - Added ttlockio package

---

## 🚀 How to Use

### Initial Setup (One Time):

```bash
# 1. Make sure migrations are run
python manage.py migrate

# 2. Authenticate with your TTLock credentials
python manage.py ttlock_get_token --username YOUR_EMAIL --password YOUR_PASSWORD
```

### In Your Code (Always):

```python
from main.services import TTLockService

# Get a valid token (auto-refreshes if needed)
service = TTLockService()
token = service.get_valid_token()
```

Or use existing TTLockClient (now with auto-refresh):

```python
from main.ttlock_utils import TTLockClient

# Client automatically gets valid token from database
client = TTLockClient()
locks = client.list_locks()
```

---

## ✅ Testing Checklist

### Local Testing:

1. ✅ Run migrations
   ```bash
   python manage.py migrate
   ```

2. ✅ Get token
   ```bash
   python manage.py ttlock_get_token --username YOUR_EMAIL --password YOUR_PASSWORD
   ```

3. ✅ Check admin
   - Visit: http://localhost:8000/admin/main/ttlocktoken/
   - Verify token exists and status is "Valid"

4. ✅ Test in code
   ```python
   from main.services import TTLockService
   service = TTLockService()
   token = service.get_valid_token()
   print(f"Token: {token[:20]}...")
   ```

5. ✅ Test TTLockClient
   ```python
   from main.ttlock_utils import TTLockClient
   client = TTLockClient()
   locks = client.list_locks()
   print(f"Found {len(locks.get('list', []))} locks")
   ```

### Heroku Testing:

1. ✅ Push code
   ```bash
   git add .
   git commit -m "Integrate TTLock token management"
   git push heroku main
   ```

2. ✅ Run migrations
   ```bash
   heroku run python manage.py migrate -a pickarooms
   ```

3. ✅ Authenticate
   ```bash
   heroku run python manage.py ttlock_get_token --username YOUR_EMAIL --password YOUR_PASSWORD -a pickarooms
   ```

4. ✅ Verify
   - Visit: https://pickarooms-495ab160017c.herokuapp.com/admin/main/ttlocktoken/
   - Check token status

---

## 📊 Token Lifecycle Diagram

```
1. Initial Auth:
   └─> python manage.py ttlock_get_token
       └─> Authenticate with TTLock
           └─> Store in Database

2. Usage:
   └─> service.get_valid_token()
       └─> Check expiry
           ├─> Valid? Return token
           └─> Expired? Refresh → Return token

3. Auto-Refresh:
   └─> Token expires in < 1 hour
       └─> Call refresh_token()
           └─> Update database
               └─> Return new token
```

---

## 🔧 Configuration

### Required Settings (env.py):

```python
os.environ.setdefault('SCIENER_CLIENT_ID', 'your_client_id')
os.environ.setdefault('SCIENER_CLIENT_SECRET', 'your_client_secret')
os.environ.setdefault('TTLOCK_BASE_URL', 'https://euapi.sciener.com/v3')
```

### Optional (Now handled by service):

```python
# These are now optional - service manages tokens in DB
os.environ.setdefault('SCIENER_ACCESS_TOKEN', 'not_needed')
os.environ.setdefault('SCIENER_REFRESH_TOKEN', 'not_needed')
```

---

## 📝 Next Steps

### Ready to Test:

1. **Run the authentication command** with your TTLock credentials
2. **Check the admin panel** to see your token
3. **Test with existing code** - TTLockClient should now work!

### Example Test:

```python
python manage.py ttlock_get_token --username YOUR_EMAIL --password YOUR_PASSWORD
```

After successful authentication, your existing TTLock integration will automatically use the new token management system!

---

## 🎯 Benefits

✅ **No More Manual Tokens** - Postman not needed  
✅ **Automatic Refresh** - Never worry about expired tokens  
✅ **Database Storage** - Shared across app instances  
✅ **Simple Usage** - One line: `service.get_valid_token()`  
✅ **Backward Compatible** - Old code still works  
✅ **Admin Visibility** - View token status anytime  
✅ **Error Handling** - Clear messages when auth needed  

---

## 🐛 Troubleshooting

### "No token found in database"
- Run: `python manage.py ttlock_get_token --username EMAIL --password PASSWORD`

### "Authentication failed"
- Check credentials
- Verify Client ID/Secret in env.py
- Ensure TTLock account has API access

### "Token refresh failed"
- Re-run authentication command
- Check internet connection
- Verify TTLock API is operational

---

## 📚 Documentation

- **Full Guide**: `TTLOCK_INTEGRATION_GUIDE.md`
- **Service Code**: `main/services/ttlock_service.py`
- **Model**: `main/models.py` (TTLockToken)
- **Command**: `main/management/commands/ttlock_get_token.py`

---

**Integration Complete! Ready to authenticate and test.** 🚀
