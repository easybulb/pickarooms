"""
Refresh TTLock Tokens
Simple script to refresh expired TTLock access tokens
"""

import os
import requests

# Import env.py to load environment variables
if os.path.isfile("env.py"):
    import env

CLIENT_ID = os.environ.get('SCIENER_CLIENT_ID')
CLIENT_SECRET = os.environ.get('SCIENER_CLIENT_SECRET')
REFRESH_TOKEN = os.environ.get('SCIENER_REFRESH_TOKEN')
OAUTH_BASE_URL = os.environ.get('TTLOCK_OAUTH_BASE_URL', 'https://euapi.sciener.com')

print("=" * 60)
print("TTLock Token Refresh")
print("=" * 60)
print()

if not CLIENT_ID or not CLIENT_SECRET or not REFRESH_TOKEN:
    print("[ERROR] Missing credentials. Please check your env.py file.")
    exit(1)

print(f"Client ID: {CLIENT_ID}")
print(f"Refresh Token: {REFRESH_TOKEN[:20]}...")
print()

# Method 1: Try refresh token
print("Attempting to refresh token...")
print()

token_url = f"{OAUTH_BASE_URL}/oauth/token"
data = {
    'client_id': CLIENT_ID,
    'client_secret': CLIENT_SECRET,
    'refresh_token': REFRESH_TOKEN,
    'grant_type': 'refresh_token'
}

try:
    response = requests.post(token_url, data=data)
    print(f"Response Status: {response.status_code}")
    print(f"Response: {response.text}")
    print()
    
    if response.status_code == 200:
        tokens = response.json()
        
        if 'access_token' in tokens:
            print("=" * 60)
            print("[SUCCESS] Tokens Refreshed!")
            print("=" * 60)
            print()
            print(f"ACCESS_TOKEN: {tokens.get('access_token')}")
            print(f"REFRESH_TOKEN: {tokens.get('refresh_token')}")
            print()
            print("=" * 60)
            print("Update your env.py with these new values:")
            print("=" * 60)
            print()
            print(f"os.environ.setdefault('SCIENER_ACCESS_TOKEN', '{tokens.get('access_token')}')")
            print(f"os.environ.setdefault('SCIENER_REFRESH_TOKEN', '{tokens.get('refresh_token')}')")
            print()
            print("Also update on Heroku:")
            print(f"heroku config:set SCIENER_ACCESS_TOKEN=\"{tokens.get('access_token')}\" -a pickarooms")
            print(f"heroku config:set SCIENER_REFRESH_TOKEN=\"{tokens.get('refresh_token')}\" -a pickarooms")
            print()
        else:
            print("[ERROR] No access_token in response")
    else:
        print("[ERROR] Failed to refresh token")
        print()
        print("The refresh token might be expired or invalid.")
        print("You may need to:")
        print("1. Re-authenticate through TTLock OAuth flow")
        print("2. Or contact TTLock support for new tokens")
        
except Exception as e:
    print(f"[ERROR] Exception occurred: {str(e)}")

print()
print("=" * 60)
