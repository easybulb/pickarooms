# TTLock Callback URL Change Summary

## Changes Made to Code

I've updated the callback URL to use your NEW Heroku app in the following files:

### 1. **env.py**
```python
# CHANGED FROM:
os.environ.setdefault('TTLOCK_CALLBACK_URL', 'https://pickarooms-3203aa136ccc.herokuapp.com/api/callback')

# CHANGED TO:
os.environ.setdefault('TTLOCK_CALLBACK_URL', 'https://pickarooms-495ab160017c.herokuapp.com/api/callback')
```

### 2. **pickarooms/settings.py**
```python
# CHANGED FROM:
TTLOCK_CALLBACK_URL = os.environ.get("TTLOCK_CALLBACK_URL", "https://pickarooms-3203aa136ccc.herokuapp.com/api/callback")

# CHANGED TO:
TTLOCK_CALLBACK_URL = os.environ.get("TTLOCK_CALLBACK_URL", "https://pickarooms-495ab160017c.herokuapp.com/api/callback")
```

### 3. **get_ttlock_tokens.py**
```python
# CHANGED FROM:
REDIRECT_URI = os.environ.get('TTLOCK_CALLBACK_URL', 'https://pickarooms-3203aa136ccc.herokuapp.com/api/callback')

# CHANGED TO:
REDIRECT_URI = os.environ.get('TTLOCK_CALLBACK_URL', 'https://pickarooms-495ab160017c.herokuapp.com/api/callback')
```

### 4. **ALLOWED_HOSTS Updated**
Also added your new Heroku domain to ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS

---

## What You Need to Do in TTLock Dashboard

### Go to: https://euopen.ttlock.com/manager/41442

### Steps:

1. **Find the Callback URL field** (currently shows: `https://pickarooms-3203aa136ccc.herokuapp.com/api/callback`)

2. **Click the "Edit" button** next to the callback URL

3. **Replace it with:**
   ```
   https://pickarooms-495ab160017c.herokuapp.com/api/callback
   ```

4. **Click "Save" or "Update"**

5. **Wait for the status to change from "Paused"** (it should become active once saved)

---

## Important Notes:

✅ **This will work for PRODUCTION (Heroku)**
- The callback URL now points to your NEW Heroku app: `https://pickarooms-495ab160017c.herokuapp.com`
- This will work once your app is deployed to Heroku

⚠️ **Before Testing:**
- Your app must be deployed to Heroku first
- The `/api/callback` endpoint must be accessible at that URL

🔄 **Already Set Up:**
- ALLOWED_HOSTS includes your new Heroku domain
- CSRF_TRUSTED_ORIGINS includes your new Heroku domain
- The callback URL is configured for your new Heroku app

---

## After Updating the Callback URL

Once you've updated it in the TTLock dashboard, run:

```bash
python get_ttlock_tokens.py
```

This will help you get fresh access tokens for TTLock.
