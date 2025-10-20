# TTLock Token Setup - Manual Instructions

## Current Situation
- Your TTLock Open Platform app is **approved** ✓
- Client ID: `a599a704ba2c4d41969b2c75408ead2b`
- Client Secret: Available (click "View")
- **Issue**: Callback URL is paused due to failed requests

## Method 1: Reset Callback URL (Recommended for Production)

1. **Go to TTLock Open Platform**: https://euopen.ttlock.com/manager/41442

2. **Click "Test" button** next to your callback URL
   - This will test if the callback URL is working
   - If it fails, you need to implement the callback endpoint properly

3. **Or Use Local Callback for Testing**:
   - Change callback URL to: `http://localhost:8000/api/callback`
   - Click "Edit" next to the callback URL
   - Save the changes

## Method 2: Use TTLock App to Get Tokens (Easiest)

Since OAuth is having issues, TTLock provides an alternative for developers:

### Step 1: Go to Open Platform Dashboard
https://euopen.ttlock.com/manager/41442

### Step 2: Look for "Get Access Token" or "Test" Section
- Some Open Platform dashboards have a "Generate Token" button
- Or a "Test Access" section

### Step 3: Manual Token Generation via API Test Tool

If available, try using Postman or curl:

```bash
curl -X POST "https://euapi.sciener.com/oauth/token" \
  -d "client_id=a599a704ba2c4d41969b2c75408ead2b" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "username=YOUR_TTLOCK_USERNAME" \
  -d "password=YOUR_TTLOCK_PASSWORD" \
  -d "grant_type=password"
```

## Method 3: Contact TTLock Support

If the above methods don't work:

1. **Email**: support@ttlock.com or developer@sciener.com
2. **Ask for**: Development access tokens or help with OAuth flow
3. **Mention**: You're a developer with an approved app (ID: a599a704ba2c4d41969b2c75408ead2b)

## Method 4: Use Existing Tokens (If You Have Them)

If you've successfully connected before, check:

1. **In your production environment** (Heroku):
   - Check Config Vars for existing tokens
   
2. **In local files**:
   - Check `main/tokens.json` (if it exists)
   - This file stores tokens locally

## Temporary Workaround: Use Local Callback

1. **Start your Django server locally**:
   ```bash
   python manage.py runserver
   ```

2. **Update callback URL in TTLock dashboard to**:
   ```
   http://localhost:8000/api/callback
   ```

3. **Then use the OAuth flow**:
   ```
   https://euapi.sciener.com/oauth/authorize?client_id=a599a704ba2c4d41969b2c75408ead2b&redirect_uri=http://localhost:8000/api/callback&response_type=code
   ```

4. **After authorization**, you'll be redirected to your local server with the code

## Next Steps

Let me know which method you'd like to try, or if you have:
- Access to your Heroku config vars (existing tokens)
- The client_secret from TTLock dashboard
- Your TTLock account username/password

I can help you proceed with any of these methods!
