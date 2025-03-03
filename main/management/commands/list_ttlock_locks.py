# main/management/commands/list_ttlock_locks.py
from django.core.management.base import BaseCommand
from main.ttlock_utils import TTLockClient
import logging

# Set up logging
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Lists all TTLock locks associated with the account."

    def handle(self, *args, **kwargs):
        client = TTLockClient()
        try:
            response = client.list_locks()
        except Exception as e:
            self.stdout.write(f"Error: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_body = e.response.json()
                    self.stdout.write(f"Error response body: {error_body}")
                    logger.error(f"Error listing locks: {str(e)} - Response: {error_body}")
                except ValueError:
                    self.stdout.write(f"Error response body (raw): {e.response.text}")
                    logger.error(f"Error listing locks: {str(e)} - Raw Response: {e.response.text}")
            if "400 Client Error" in str(e):
                self.stdout.write("Token might be invalid. Attempting to refresh token...")
                try:
                    refresh_response = client.refresh_access_token()
                    self.stdout.write(f"Token refreshed successfully: {refresh_response}")
                    logger.info(f"Token refreshed: {refresh_response}")
                    # Retry the request with the new token
                    response = client.list_locks()
                except Exception as refresh_error:
                    self.stdout.write(f"Failed to refresh token: {str(refresh_error)}")
                    if hasattr(refresh_error, 'response') and refresh_error.response is not None:
                        try:
                            refresh_error_body = refresh_error.response.json()
                            self.stdout.write(f"Refresh error response body: {refresh_error_body}")
                            logger.error(f"Failed to refresh token: {str(refresh_error)} - Response: {refresh_error_body}")
                        except ValueError:
                            self.stdout.write(f"Refresh error response body (raw): {refresh_error.response.text}")
                            logger.error(f"Failed to refresh token: {str(refresh_error)} - Raw Response: {refresh_error.response.text}")
                    return
            else:
                logger.error(f"Error listing locks: {str(e)}")
                return

        if response.get("list"):
            self.stdout.write("Found locks:")
            for lock in response["list"]:
                self.stdout.write(f"Lock ID: {lock['lockId']}, Name: {lock['lockName']}")
            logger.info(f"Successfully listed locks: {response['list']}")
        else:
            self.stdout.write("No locks found or error occurred.")
            self.stdout.write(str(response))
            logger.warning(f"No locks found or error occurred: {response}")