# TTLock Token Refresh Guide

## Current Status:

✅ **Callback URL Test**: Successful at TTLock dashboard  
✅ **Callback URL Accessible**: https://pickarooms-495ab160017c.herokuapp.com/api/callback  
❌ **Access Tokens**: Expired (errcode: 10004)  
❌ **OAuth Refresh Endpoint**: Not working (404 error)  

---

## Why Tokens Are Expired:

The TTLock access tokens have a limited lifespan and need to be refreshed periodically. The current tokens in your `main/tokens.json` and `env.py` are no longer valid.

---

## Solutions to Get Fresh Tokens:

### **Option 1: Check TTLock Dashboard (Recommended)**

1. Go to: https://euopen.ttlock.com/manager/41442
2. Look for any of these sections:
   - "API Test"
   - "Get Access Token"
   - "Token Management"
   - "Test API"
3. Some dashboards have a button to generate fresh tokens directly
4. If you find it, copy the new `access_token` and `refresh_token`

### **Option 2: Use TTLock OAuth Flow (Manual)**

Since the automated OAuth isn't working, you can manually authorize:

1. **Build Authorization URL:**
   ```
   https://euapi.sciener.com/oauth/authorize?client_id=a599a704ba2c4d41969b2c75408ead2b&redirect_uri=https://pickarooms-495ab160017c.herokuapp.com/api/callback&response_type=code&state=refresh_tokens
   ```

2. **Open in Browser**: Paste the URL above
3. **Login**: Use your TTLock account credentials
4. **Authorize**: Click "Authorize" or "Allow"
5. **Get Code**: You'll be redirected to your callback URL with a `code` parameter:
   ```
   https://pickarooms-495ab160017c.herokuapp.com/api/callback?code=AUTHORIZATION_CODE&state=refresh_tokens
   ```
6. **Copy the code** from the URL

7. **Exchange Code for Tokens**: Use this curl command (replace `YOUR_CODE`):
   ```bash
   curl -X POST "https://euapi.sciener.com/oauth/token" \
     -d "client_id=a599a704ba2c4d41969b2c75408ead2b" \
     -d "client_secret=d1f5f0ab5576c708502b9f51f31babd0" \
     -d "code=YOUR_CODE" \
     -d "grant_type=authorization_code" \
     -d "redirect_uri=https://pickarooms-495ab160017c.herokuapp.com/api/callback"
   ```

   Or in PowerShell:
   ```powershell
   $body = @{
       client_id = "a599a704ba2c4d41969b2c75408ead2b"
       client_secret = "d1f5f0ab5576c708502b9f51f31babd0"
       code = "YOUR_CODE"
       grant_type = "authorization_code"
       redirect_uri = "https://pickarooms-495ab160017c.herokuapp.com/api/callback"
   }
   Invoke-RestMethod -Method Post -Uri "https://euapi.sciener.com/oauth/token" -Body $body
   ```

### **Option 3: Contact TTLock Support**

If the above methods don't work:

1. **Email**: support@ttlock.com or developer@sciener.com
2. **Subject**: "Request for New Access Tokens"
3. **Include**:
   - Your App ID: a599a704ba2c4d41969b2c75408ead2b
   - Your account email
   - Mention that refresh tokens are expired

---

## Once You Get New Tokens:

### **Update Local env.py:**
```python
os.environ.setdefault('SCIENER_ACCESS_TOKEN', 'your_new_access_token')
os.environ.setdefault('SCIENER_REFRESH_TOKEN', 'your_new_refresh_token')
```

### **Update Heroku:**
```bash
heroku config:set SCIENER_ACCESS_TOKEN="your_new_access_token" -a pickarooms
heroku config:set SCIENER_REFRESH_TOKEN="your_new_refresh_token" -a pickarooms
```

### **Update main/tokens.json:**
```json
{
  "access_token": "your_new_access_token",
  "refresh_token": "your_new_refresh_token"
}
```

---

## Test After Update:

Run the test script:
```bash
python test_ttlock_api.py
```

You should see:
- ✅ Locks listed successfully
- ✅ Token validation passes
- ✅ Lock status queries work

---

## Alternative: Check TTLock API Documentation

The TTLock/Sciener API documentation might have updated endpoints:
- Check: https://euopen.ttlock.com/
- Look for "API Documentation" or "Developer Guide"
- OAuth endpoints might have changed to `/v3/oauth/token` or similar

---

## Current Token Status:

```
Access Token: f998166fb628f555c29fb2a8eeb89f38 (EXPIRED)
Refresh Token: 196259dbe2977821578b3188bb75539a (EXPIRED)
Error Code: 10004 (invalid grant)
```

**Next Step**: Try Option 2 (OAuth Flow) - I can help you through each step!
