from main.services.gmail_client import GmailClient
from main.services.email_parser import parse_booking_com_email_subject

gmail = GmailClient()
emails = gmail.get_recent_booking_emails(max_results=10, lookback_days=1)

print(f"Found {len(emails)} recent emails from last 24 hours:\n")

for i, email in enumerate(emails[:10], 1):
    subject = email['subject']
    parsed = parse_booking_com_email_subject(subject)
    
    print(f"{i}. Subject: {subject}")
    print(f"   Parsed: {parsed}")
    print(f"   Read: {'Yes' if not email.get('is_unread', False) else 'No'}")
    print()
