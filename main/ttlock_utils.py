import requests
import os
import json
from django.utils import timezone
from django.conf import settings
import logging

# Set up logging
logger = logging.getLogger(__name__)

class TTLockClient:
    def __init__(self, use_service=True):
        self.base_url = settings.TTLOCK_BASE_URL  # For API calls (e.g., https://euapi.sciener.com/v3)
        self.oauth_base_url = settings.TTLOCK_OAUTH_BASE_URL  # For OAuth calls (e.g., https://euapi.sciener.com)
        self.client_id = os.environ.get("SCIENER_CLIENT_ID")
        self.client_secret = os.environ.get("SCIENER_CLIENT_SECRET")
        
        # Try to use TTLockService for automatic token management
        if use_service:
            try:
                from main.services import TTLockService
                service = TTLockService()
                self.access_token = service.get_valid_token()
                self.refresh_token = None  # Handled by service
                logger.info("Using TTLockService for token management")
                return
            except Exception as e:
                logger.warning(f"TTLockService unavailable, falling back to legacy method: {str(e)}")
        
        # Fallback: Load tokens from a file if it exists, otherwise use env.py
        self.token_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tokens.json")
        self._load_tokens()
        
        if not hasattr(self, 'access_token') or not self.access_token:
            self.access_token = os.environ.get("SCIENER_ACCESS_TOKEN")
            self.refresh_token = os.environ.get("SCIENER_REFRESH_TOKEN")
            self._save_tokens()  # Save initial tokens to file

    def _load_tokens(self):
        """Load tokens from the token file."""
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, 'r') as f:
                    tokens = json.load(f)
                    self.access_token = tokens.get("access_token")
                    self.refresh_token = tokens.get("refresh_token")
            else:
                pass  # No logging needed
        except Exception as e:
            logger.error(f"Failed to load tokens from file: {str(e)}")

    def _save_tokens(self):
        """Save tokens to the token file."""
        try:
            tokens = {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token
            }
            with open(self.token_file, 'w') as f:
                json.dump(tokens, f)
        except Exception as e:
            logger.error(f"Failed to save tokens to file: {str(e)}")

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
            "clientId": self.client_id,
            "accessToken": self.access_token,
            "date": str(int(timezone.now().timestamp() * 1000)),
        }

        if data:
            # Convert numeric values to strings to match API expectations
            for key, value in data.items():
                params[key] = str(value)

        response = requests.request(method, url, headers=headers, params=params if method == "GET" else None, data=params if method == "POST" else None)
        response.raise_for_status()
        result = response.json()

        # Check for TTLock-specific errors
        if "errcode" in result and result["errcode"] != 0:
            error_msg = result.get("errmsg", "Unknown error")
            logger.error(f"TTLock API error: {error_msg} (errcode: {result['errcode']})")
            if result["errcode"] == 10003:  # Token expired
                self.refresh_access_token()
                # Update headers and params with new token
                headers["Authorization"] = f"Bearer {self.access_token}"
                params["accessToken"] = self.access_token
                # Retry the request
                response = requests.request(method, url, headers=headers, params=params if method == "GET" else None, data=params if method == "POST" else None)
                response.raise_for_status()
                result = response.json()
                if "errcode" in result and result["errcode"] != 0:
                    error_msg = result.get("errmsg", "Unknown error")
                    logger.error(f"TTLock API error after retry: {error_msg} (errcode: {result['errcode']})")
                    raise Exception(f"TTLock API error after retry: {error_msg} (errcode: {result['errcode']})")
            else:
                raise Exception(f"TTLock API error: {error_msg} (errcode: {result['errcode']})")

        return result

    def refresh_access_token(self):
        """Refresh the access token using the refresh token."""
        url = f"{self.oauth_base_url}/oauth/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }
        
        # Make direct request without using _make_request to avoid recursion
        response = requests.post(url, data=data)
        response.raise_for_status()
        result = response.json()

        # Update tokens in the instance
        self.access_token = result.get("access_token")
        self.refresh_token = result.get("refresh_token")
        self._save_tokens()  # Persist the new tokens
        logger.info("Access token refreshed successfully")
        return self.access_token

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
        # Validate PIN length (must be 4 digits)
        if not (len(pin) == 4 and pin.isdigit()):
            raise ValueError("PIN must be exactly 4 digits.")
        
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
        return self._make_request("POST", "/keyboardPwd/add", data)

    def delete_pin(self, lock_id, keyboard_pwd_id):
        """Delete a PIN from a lock."""
        data = {
            "lockId": lock_id,
            "keyboardPwdId": keyboard_pwd_id,
        }
        return self._make_request("POST", "/keyboardPwd/delete", data)

    def list_keyboard_passwords(self, lock_id, page_no=1, page_size=20):
        """List all keyboard passwords for a lock."""
        data = {
            "lockId": lock_id,
            "pageNo": page_no,
            "pageSize": page_size,
        }
        return self._make_request("GET", "/lock/listKeyboardPwd", data)