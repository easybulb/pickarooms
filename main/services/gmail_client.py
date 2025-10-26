"""
Gmail API Client for Email Enrichment System
Handles reading emails from Gmail using the Gmail API
"""

import os
import base64
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger('main')

# Gmail API scopes - readonly access to Gmail
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly',
          'https://www.googleapis.com/auth/gmail.modify']


class GmailClient:
    """
    Gmail API client for reading Booking.com confirmation emails
    """

    def __init__(self):
        """Initialize Gmail API client with credentials"""
        self.service = None
        self.creds = None
        self._authenticate()

    def _authenticate(self):
        """
        Authenticate with Gmail API using OAuth2

        Credentials flow:
        1. Check if GMAIL_TOKEN_BASE64 env variable exists (Heroku deployment)
        2. Check if token.json exists (local development)
        3. If token expired, refresh it
        4. If no token, initiate OAuth flow (first-time setup)
        """
        token_path = os.path.join(os.getcwd(), 'gmail_token.json')
        credentials_path = os.path.join(os.getcwd(), 'gmail_credentials.json')

        # HEROKU: Check for base64-encoded token in environment variable
        token_base64 = os.environ.get('GMAIL_TOKEN_BASE64')
        if token_base64 and not os.path.exists(token_path):
            try:
                import base64
                token_data = base64.b64decode(token_base64)
                with open(token_path, 'wb') as f:
                    f.write(token_data)
                logger.info("Decoded Gmail token from GMAIL_TOKEN_BASE64 environment variable")
            except Exception as e:
                logger.error(f"Error decoding GMAIL_TOKEN_BASE64: {str(e)}")
        
        # HEROKU: Check for base64-encoded credentials in environment variable
        creds_base64 = os.environ.get('GMAIL_CREDENTIALS_BASE64')
        if creds_base64 and not os.path.exists(credentials_path):
            try:
                import base64
                creds_data = base64.b64decode(creds_base64)
                with open(credentials_path, 'wb') as f:
                    f.write(creds_data)
                logger.info("Decoded Gmail credentials from GMAIL_CREDENTIALS_BASE64 environment variable")
            except Exception as e:
                logger.error(f"Error decoding GMAIL_CREDENTIALS_BASE64: {str(e)}")

        # Load existing credentials
        if os.path.exists(token_path):
            try:
                self.creds = Credentials.from_authorized_user_file(token_path, SCOPES)
                logger.info("Loaded Gmail credentials from gmail_token.json")
            except Exception as e:
                logger.error(f"Error loading credentials: {str(e)}")
                self.creds = None

        # Refresh or get new credentials
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    self.creds.refresh(Request())
                    logger.info("Refreshed Gmail credentials")
                except Exception as e:
                    logger.error(f"Error refreshing credentials: {str(e)}")
                    raise Exception(
                        "Gmail credentials expired and could not be refreshed. "
                        "Please delete gmail_token.json and re-authenticate."
                    )
            else:
                # First-time authentication required
                if not os.path.exists(credentials_path):
                    raise FileNotFoundError(
                        f"Gmail credentials file not found at {credentials_path}. "
                        "Please download OAuth2 credentials from Google Cloud Console."
                    )

                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        credentials_path, SCOPES
                    )
                    self.creds = flow.run_local_server(port=0)
                    logger.info("Completed first-time Gmail OAuth authentication")
                except Exception as e:
                    logger.error(f"Error during OAuth flow: {str(e)}")
                    raise

            # Save credentials for future use
            try:
                with open(token_path, 'w') as token:
                    token.write(self.creds.to_json())
                logger.info(f"Saved Gmail credentials to {token_path}")
            except Exception as e:
                logger.error(f"Error saving credentials: {str(e)}")

        # Build Gmail service
        try:
            self.service = build('gmail', 'v1', credentials=self.creds)
            logger.info("Gmail API service initialized successfully")
        except Exception as e:
            logger.error(f"Error building Gmail service: {str(e)}")
            raise

    def get_unread_booking_emails(self, max_results=50):
        """
        Get unread emails from Booking.com

        Optionally filters by Gmail label if GMAIL_LABEL_FILTER is set in settings.
        This prevents processing old unread emails and reduces Redis usage.

        Returns:
            list: List of email dictionaries with keys:
                - id: Gmail message ID
                - subject: Email subject line
                - received_at: Datetime when email was received
        """
        try:
            from django.conf import settings

            # Search query: unread emails from Booking.com
            query = 'from:noreply@booking.com is:unread'

            # Add label filter if configured (prevents processing old emails)
            label_filter = getattr(settings, 'GMAIL_LABEL_FILTER', '').strip()
            if label_filter:
                # Gmail label syntax: label:LabelName or label:"Label With Spaces"
                if ' ' in label_filter:
                    query += f' label:"{label_filter}"'
                else:
                    query += f' label:{label_filter}'
                logger.info(f"Using Gmail label filter: '{label_filter}' - Query: {query}")
            else:
                logger.info("No Gmail label filter configured - processing all unread Booking.com emails")

            # Call Gmail API
            results = self.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()

            messages = results.get('messages', [])

            if not messages:
                return []

            logger.info(f"Found {len(messages)} unread Booking.com email(s)")

            # Fetch full details for each message
            emails = []
            for msg in messages:
                try:
                    message = self.service.users().messages().get(
                        userId='me',
                        id=msg['id'],
                        format='full'
                    ).execute()

                    # Extract headers
                    headers = message['payload']['headers']
                    subject = None
                    date_str = None

                    for header in headers:
                        if header['name'].lower() == 'subject':
                            subject = header['value']
                        elif header['name'].lower() == 'date':
                            date_str = header['value']

                    if not subject:
                        logger.warning(f"Email {msg['id']} has no subject, skipping")
                        continue

                    # Parse date
                    received_at = None
                    if date_str:
                        try:
                            received_at = parsedate_to_datetime(date_str)
                        except Exception as e:
                            logger.warning(f"Could not parse date '{date_str}': {str(e)}")
                            received_at = datetime.now(timezone.utc)
                    else:
                        received_at = datetime.now(timezone.utc)

                    emails.append({
                        'id': msg['id'],
                        'subject': subject,
                        'received_at': received_at,
                    })

                except HttpError as e:
                    logger.error(f"Error fetching message {msg['id']}: {str(e)}")
                    continue

            return emails

        except HttpError as e:
            logger.error(f"Gmail API error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Error getting unread Booking.com emails: {str(e)}")
            raise

    def get_recent_booking_emails(self, max_results=10, lookback_days=30):
        """
        Get recent Booking.com emails (read OR unread)
        
        This is more bulletproof than get_unread_booking_emails() because:
        - Forgives human error (accidentally marking email as read)
        - Only searches recent emails (faster, more relevant)
        - Prevents matching ancient emails
        
        Args:
            max_results: Number of recent emails to fetch (default: 10)
            lookback_days: Only search emails from last N days (default: 30)
        
        Returns:
            list: Recent emails sorted by date (newest first) with keys:
                - id: Gmail message ID
                - subject: Email subject line
                - received_at: Datetime when email was received
        """
        try:
            from datetime import timedelta
            
            # Calculate date filter (last N days)
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)
            date_filter = cutoff_date.strftime('%Y/%m/%d')
            
            # Search query: all Booking.com emails from last N days (read + unread)
            query = f'from:noreply@booking.com after:{date_filter}'
            
            logger.info(f"Searching recent Booking.com emails: last {max_results} emails from last {lookback_days} days")
            
            # Call Gmail API
            results = self.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()
            
            messages = results.get('messages', [])
            
            if not messages:
                logger.info("No recent Booking.com emails found")
                return []
            
            logger.info(f"Found {len(messages)} recent Booking.com email(s)")
            
            # Fetch full details for each message
            emails = []
            for msg in messages:
                try:
                    message = self.service.users().messages().get(
                        userId='me',
                        id=msg['id'],
                        format='full'
                    ).execute()
                    
                    # Extract headers and check if unread
                    headers = message['payload']['headers']
                    label_ids = message.get('labelIds', [])
                    is_unread = 'UNREAD' in label_ids
                    
                    subject = None
                    date_str = None
                    
                    for header in headers:
                        if header['name'].lower() == 'subject':
                            subject = header['value']
                        elif header['name'].lower() == 'date':
                            date_str = header['value']
                    
                    if not subject:
                        logger.warning(f"Email {msg['id']} has no subject, skipping")
                        continue
                    
                    # Parse date
                    received_at = None
                    if date_str:
                        try:
                            received_at = parsedate_to_datetime(date_str)
                        except Exception as e:
                            logger.warning(f"Could not parse date '{date_str}': {str(e)}")
                            received_at = datetime.now(timezone.utc)
                    else:
                        received_at = datetime.now(timezone.utc)
                    
                    emails.append({
                        'id': msg['id'],
                        'subject': subject,
                        'received_at': received_at,
                        'is_unread': is_unread,
                    })
                
                except HttpError as e:
                    logger.error(f"Error fetching message {msg['id']}: {str(e)}")
                    continue
            
            # Sort by unread first, then by date descending (newest first)
            # This prioritizes unread emails when there are multiple matches
            emails.sort(key=lambda x: (not x['is_unread'], -x['received_at'].timestamp()))
            
            logger.info(f"Returning {len(emails)} recent Booking.com email(s) sorted by date")
            return emails
        
        except HttpError as e:
            logger.error(f"Gmail API error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Error getting recent Booking.com emails: {str(e)}")
            raise
    
    def mark_as_read(self, message_id):
        """
        Mark an email as read

        Args:
            message_id: Gmail message ID
        """
        try:
            self.service.users().messages().modify(
                userId='me',
                id=message_id,
                body={'removeLabelIds': ['UNREAD']}
            ).execute()

            logger.info(f"Marked email {message_id} as read")

        except HttpError as e:
            logger.error(f"Error marking email {message_id} as read: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Error marking email as read: {str(e)}")
            raise

    def get_email_body(self, message_id):
        """
        Get email body content (for debugging/logging)

        Args:
            message_id: Gmail message ID

        Returns:
            str: Email body text
        """
        try:
            message = self.service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()

            payload = message['payload']
            body_data = None

            # Try to get body from different locations
            if 'body' in payload and 'data' in payload['body']:
                body_data = payload['body']['data']
            elif 'parts' in payload:
                for part in payload['parts']:
                    if part['mimeType'] == 'text/plain':
                        body_data = part['body']['data']
                        break
                    elif part['mimeType'] == 'text/html':
                        body_data = part['body']['data']

            if body_data:
                # Decode base64
                body = base64.urlsafe_b64decode(body_data).decode('utf-8')
                return body

            return ""

        except Exception as e:
            logger.error(f"Error getting email body: {str(e)}")
            return ""
