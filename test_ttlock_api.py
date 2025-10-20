"""
TTLock API Integration Test
Tests the complete TTLock API integration including callback URL
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.ttlock_utils import TTLockClient
import requests

print("=" * 60)
print("TTLock API Integration Test")
print("=" * 60)
print()

# Initialize client
try:
    client = TTLockClient()
    print("[OK] TTLock client initialized")
    print(f"     Client ID: {client.client_id}")
    print(f"     Access Token: {client.access_token[:20] if client.access_token else 'None'}...")
    print(f"     Base URL: {client.base_url}")
    print()
except Exception as e:
    print(f"[ERROR] Failed to initialize client: {str(e)}")
    exit(1)

# Test 1: List Locks
print("-" * 60)
print("TEST 1: Listing All Locks")
print("-" * 60)
try:
    locks_response = client.list_locks()
    
    if 'list' in locks_response:
        locks = locks_response['list']
        print(f"[OK] Found {len(locks)} lock(s)")
        print()
        
        for i, lock in enumerate(locks, 1):
            print(f"Lock {i}:")
            print(f"  Lock ID: {lock.get('lockId')}")
            print(f"  Name: {lock.get('lockName')}")
            print(f"  MAC Address: {lock.get('lockMac')}")
            print(f"  Battery: {lock.get('electricQuantity')}%")
            print(f"  Has Gateway: {'Yes' if lock.get('hasGateway') else 'No'}")
            print(f"  Lock Status: {lock.get('lockData', 'N/A')}")
            print()
    else:
        print(f"[WARNING] Unexpected response format: {locks_response}")
        
except Exception as e:
    print(f"[ERROR] Failed to list locks: {str(e)}")
    print()

# Test 2: Test Callback URL
print("-" * 60)
print("TEST 2: Testing Callback URL Accessibility")
print("-" * 60)
callback_url = os.environ.get('TTLOCK_CALLBACK_URL', 'Not set')
print(f"Callback URL: {callback_url}")

if callback_url and callback_url != 'Not set':
    try:
        # Try to ping the callback endpoint
        response = requests.get(callback_url, timeout=10)
        print(f"[OK] Callback URL is accessible (Status: {response.status_code})")
    except requests.exceptions.RequestException as e:
        print(f"[WARNING] Callback URL test: {str(e)}")
        print("         This is expected if the app is not deployed yet")
else:
    print("[ERROR] Callback URL not configured")

print()

# Test 3: Query Lock Status (if locks exist)
if 'locks' in locals() and locks:
    print("-" * 60)
    print("TEST 3: Querying Lock Status")
    print("-" * 60)
    
    first_lock_id = locks[0].get('lockId')
    print(f"Testing with Lock ID: {first_lock_id}")
    
    try:
        status = client.query_lock_status(first_lock_id)
        print(f"[OK] Lock status retrieved")
        print(f"     State: {status.get('state', 'N/A')}")
        print(f"     Response: {status}")
    except Exception as e:
        print(f"[ERROR] Failed to query lock status: {str(e)}")
    
    print()

# Test 4: Check Token Validity
print("-" * 60)
print("TEST 4: Token Validity Check")
print("-" * 60)

if client.access_token and client.refresh_token:
    print("[OK] Both access and refresh tokens are present")
    
    # Try to make an API call to verify token works
    try:
        test_response = client.list_locks()
        if 'errcode' in test_response and test_response['errcode'] == 0:
            print("[OK] Access token is valid and working")
        elif 'list' in test_response:
            print("[OK] Access token is valid and working")
        else:
            print(f"[WARNING] Unexpected response: {test_response}")
    except Exception as e:
        if "10003" in str(e):
            print("[WARNING] Access token expired, attempting refresh...")
            try:
                new_token = client.refresh_access_token()
                print(f"[OK] Token refreshed successfully")
                print(f"     New token: {new_token[:20]}...")
            except Exception as refresh_error:
                print(f"[ERROR] Failed to refresh token: {str(refresh_error)}")
        else:
            print(f"[ERROR] Token validation failed: {str(e)}")
else:
    print("[ERROR] Tokens are missing")

print()

# Summary
print("=" * 60)
print("TEST SUMMARY")
print("=" * 60)
print()
print("✓ Check if all tests passed above")
print("✓ Verify locks are listed correctly")
print("✓ Ensure tokens are valid")
print()
print("If all tests passed, your TTLock integration is working!")
print()
print("=" * 60)
