# main/ttlock_utils.py
import requests
import os
from django.utils import timezone
from django.conf import settings
import logging

# Set up logging
logger = logging.getLogger(__name__)

class TTLockClient:
    def __init__(self):
        self.base_url = settings.TTLOCK_BASE_URL  # For API calls (e.g., https://euapi.sciener.com/v3)
        self.oauth_base_url = settings.TTLOCK_OAUTH_BASE_URL  # For OAuth calls (e.g., https://euapi.sciener.com)
        self.client_id = os.environ.get("SCIENER_CLIENT_ID")
        self.client_secret = os.environ.get("SCIENER_CLIENT_SECRET")
        self.access_token = os.environ.get("SCIENER_ACCESS_TOKEN")
        self.refresh_token = os.environ.get("SCIENER_REFRESH_TOKEN")
        logger.info(f"Initialized TTLockClient with base_url: {self.base_url}, oauth_base_url: {self.oauth_base_url}")

    def _make_request(self, method, endpoint, data=None, use_oauth_url=False):
        """Helper method to make API requests to TTLock."""
        base_url = self.oauth_base_url if use_oauth_url else self.base_url
        url = f"{base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
        }
        # Only include Content-Type for POST requests
        if method == "POST":
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        params = {
            "clientId": self.client_id,  # Use clientId to match working format
            "accessToken": self.access_token,  # Include accessToken in query params
            "date": str(int(timezone.now().timestamp() * 1000)),  # Ensure date is a string
        }

        if data:
            # Convert numeric values to strings to match API expectations
            for key, value in data.items():
                params[key] = str(value)

        logger.info(f"Making {method} request to {url} with headers: {headers}, params: {params}")
        response = requests.request(method, url, headers=headers, params=params if method == "GET" else None, data=params if method == "POST" else None)
        logger.info(f"Request URL: {response.request.url}")
        logger.info(f"Request Headers: {response.request.headers}")
        response.raise_for_status()
        result = response.json()
        logger.info(f"Received response: {result}")

        # Check for TTLock-specific errors
        if "errcode" in result and result["errcode"] != 0:
            error_msg = result.get("errmsg", "Unknown error")
            logger.error(f"TTLock API error: {error_msg} (errcode: {result['errcode']})")
            raise Exception(f"TTLock API error: {error_msg} (errcode: {result['errcode']})")

        return result

    def refresh_access_token(self):
        """Refresh the access token using the refresh token."""
        endpoint = "/v3/refresh_token"  # OAuth endpoint
        data = {
            "clientId": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }
        return self._make_request("POST", endpoint, data=data, use_oauth_url=True)

    def list_locks(self):
        """List all locks associated with the account."""
        return self._make_request("GET", "/lock/list", {"pageNo": 1, "pageSize": 20})

    def query_lock_status(self, lock_id):
        """Query the status of a lock (locked/unlocked, frozen state)."""
        data = {
            "lockId": lock_id,
        }
        return self._make_request("GET", "/lock/queryStatus", data)

    def unlock_lock(self, lock_id):
        """Unlock a lock remotely."""
        data = {
            "lockId": lock_id,
        }
        return self._make_request("POST", "/lock/unlock", data)

    def lock_lock(self, lock_id):
        """Lock a lock remotely."""
        data = {
            "lockId": lock_id,
        }
        return self._make_request("POST", "/lock/lock", data)

    def generate_temporary_pin(self, lock_id, pin, start_time, end_time, name=None, add_type=2):
        """Generate a PIN for a lock (using type 2, which maps to Permanent in the app)."""
        data = {
            "lockId": lock_id,
            "keyboardPwd": pin,
            "keyboardPwdType": 2,  # Permanent PIN (based on experiment: type 2 is Permanent in the app)
            "startDate": start_time,
            "endDate": end_time,
            "isCustom": 1,  # Mark as custom, consistent with previous tests
            "addType": add_type,  # Use gateway (2) instead of default Bluetooth (1)
        }
        if name:
            data["keyboardPwdName"] = name  # Use keyboardPwdName instead of name
        logger.debug(f"Generating permanent PIN with parameters: {data}")
        return self._make_request("POST", "/keyboardPwd/add", data)  # Removed /v3 prefix

    def delete_pin(self, lock_id, keyboard_pwd_id):
        """Delete a PIN from a lock."""
        data = {
            "lockId": lock_id,
            "keyboardPwdId": keyboard_pwd_id,
        }
        return self._make_request("POST", "/keyboardPwd/delete", data)  # Removed /v3 prefix

    def list_keyboard_passwords(self, lock_id, page_no=1, page_size=20):
        """List all keyboard passwords for a lock."""
        data = {
            "lockId": lock_id,
            "pageNo": page_no,
            "pageSize": page_size,
        }
        return self._make_request("GET", "/lock/listKeyboardPwd", data)