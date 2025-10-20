"""
TTLock Service
Handles authentication, token refresh, and provides valid tokens for TTLock API operations
"""

import logging
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from ttlockwrapper import TTLock as TTLockIOClient
from main.models import TTLockToken

logger = logging.getLogger('main')


class TTLockService:
    """Service for managing TTLock API tokens and operations"""

    def __init__(self):
        self.client_id = settings.SCIENER_CLIENT_ID
        self.client_secret = settings.SCIENER_CLIENT_SECRET
        self.base_url = settings.TTLOCK_BASE_URL

    def authenticate(self, username: str, password: str) -> TTLockToken:
        """
        Authenticate with TTLock API using username/password
        Returns and stores the token in the database
        """
        try:
            logger.info(f"Authenticating with TTLock API for user: {username}")
            
            # Authenticate using get_token static method
            redirect_uri = settings.TTLOCK_CALLBACK_URL
            response = TTLockIOClient.get_token(
                self.client_id,
                self.client_secret,
                username,
                password,
                redirect_uri
            )
            
            if not response or 'access_token' not in response:
                raise ValueError("Authentication failed: No access token in response")
            
            # Extract token data
            access_token = response['access_token']
            refresh_token = response.get('refresh_token', access_token)  # Some APIs return same token
            
            # Calculate expiry (TTLock tokens typically expire in 7776000 seconds = 90 days)
            expires_in_seconds = response.get('expires_in', 7776000)  # Default 90 days
            expires_at = timezone.now() + timedelta(seconds=expires_in_seconds)
            
            # Delete old tokens (keep only latest)
            TTLockToken.objects.all().delete()
            
            # Store new token
            token = TTLockToken.objects.create(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at
            )
            
            logger.info(f"Successfully authenticated and stored token (expires: {expires_at})")
            return token
            
        except Exception as e:
            logger.error(f"Authentication failed: {str(e)}")
            raise

    def refresh_token(self) -> TTLockToken:
        """
        Refresh the access token using the refresh token
        Returns updated token from database
        """
        try:
            # Get current token
            token = TTLockToken.get_latest()
            
            if not token:
                raise ValueError("No token found in database. Please authenticate first.")
            
            if not token.refresh_token:
                raise ValueError("No refresh token available. Please re-authenticate.")
            
            logger.info("Refreshing TTLock access token...")
            
            # Initialize client
            client = TTLockIOClient(self.client_id, self.client_secret)
            
            # Refresh token
            response = client.refresh_token(token.refresh_token)
            
            if not response or 'access_token' not in response:
                raise ValueError("Token refresh failed: No access token in response")
            
            # Update token data
            token.access_token = response['access_token']
            token.refresh_token = response.get('refresh_token', token.refresh_token)
            
            # Update expiry
            expires_in_seconds = response.get('expires_in', 7776000)
            token.expires_at = timezone.now() + timedelta(seconds=expires_in_seconds)
            
            token.save()
            
            logger.info(f"Token refreshed successfully (new expiry: {token.expires_at})")
            return token
            
        except Exception as e:
            logger.error(f"Token refresh failed: {str(e)}")
            raise

    def get_valid_token(self) -> str:
        """
        Get a valid access token, automatically refreshing if expired
        Returns the access token string
        """
        try:
            token = TTLockToken.get_latest()
            
            if not token:
                raise ValueError(
                    "No token found in database. Please run: "
                    "python manage.py ttlock_get_token --username YOUR_USERNAME --password YOUR_PASSWORD"
                )
            
            # Check if token is expired or expires soon (within 1 hour)
            buffer_time = timezone.now() + timedelta(hours=1)
            
            if token.expires_at <= buffer_time:
                logger.info("Token expired or expiring soon, refreshing...")
                token = self.refresh_token()
            
            return token.access_token
            
        except Exception as e:
            logger.error(f"Failed to get valid token: {str(e)}")
            raise

    def get_client_with_token(self):
        """
        Get a TTLockIOClient instance with a valid token
        Useful for making API calls directly
        """
        token = self.get_valid_token()
        client = TTLockIOClient(self.client_id, self.client_secret)
        client.access_token = token
        return client
