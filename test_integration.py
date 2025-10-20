"""Test TTLock Integration"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from main.ttlock_utils import TTLockClient
from main.services import TTLockService

print("=" * 60)
print("Testing TTLock Integration")
print("=" * 60)
print()

# Test 1: Get valid token from service
print("Test 1: Get valid token from service")
try:
    service = TTLockService()
    token = service.get_valid_token()
    print(f"[OK] Token retrieved: {token[:30]}...")
except Exception as e:
    print(f"[ERROR] {str(e)}")

print()

# Test 2: Use TTLockClient to list locks
print("Test 2: List locks using TTLockClient")
try:
    client = TTLockClient()
    locks_response = client.list_locks()
    
    if 'list' in locks_response:
        locks = locks_response['list']
        print(f"[OK] Found {len(locks)} lock(s)")
        for lock in locks:
            print(f"  - {lock.get('lockName')} (ID: {lock.get('lockId')})")
    else:
        print(f"[WARNING] Unexpected response: {locks_response}")
except Exception as e:
    print(f"[ERROR] {str(e)}")

print()
print("=" * 60)
print("Integration test complete!")
print("=" * 60)
