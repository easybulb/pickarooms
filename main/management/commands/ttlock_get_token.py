"""
Management command to authenticate with TTLock and store access token
Usage: python manage.py ttlock_get_token --username YOUR_USERNAME --password YOUR_PASSWORD
"""

from django.core.management.base import BaseCommand, CommandError
from main.services import TTLockService


class Command(BaseCommand):
    help = 'Authenticate with TTLock API and store access token'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            required=True,
            help='TTLock account username (email or phone)'
        )
        parser.add_argument(
            '--password',
            type=str,
            required=True,
            help='TTLock account password'
        )

    def handle(self, *args, **options):
        username = options['username']
        password = options['password']

        self.stdout.write('=' * 60)
        self.stdout.write('TTLock Token Retrieval')
        self.stdout.write('=' * 60)
        self.stdout.write('')

        try:
            service = TTLockService()
            
            self.stdout.write(f'Authenticating with username: {username}')
            self.stdout.write('Please wait...')
            self.stdout.write('')
            
            token = service.authenticate(username, password)
            
            self.stdout.write(self.style.SUCCESS('=' * 60))
            self.stdout.write(self.style.SUCCESS('SUCCESS! Token Retrieved and Stored'))
            self.stdout.write(self.style.SUCCESS('=' * 60))
            self.stdout.write('')
            self.stdout.write(f'Access Token: {token.access_token[:50]}...')
            self.stdout.write(f'Expires At: {token.expires_at}')
            self.stdout.write(f'Created At: {token.created_at}')
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('Token stored in database and ready to use!'))
            self.stdout.write('')
            
            # Also update env.py suggestion
            self.stdout.write(self.style.WARNING('Optional: Update your env.py with these values:'))
            self.stdout.write(f"os.environ.setdefault('SCIENER_ACCESS_TOKEN', '{token.access_token}')")
            self.stdout.write(f"os.environ.setdefault('SCIENER_REFRESH_TOKEN', '{token.refresh_token}')")
            self.stdout.write('')
            
            # Update Heroku suggestion
            self.stdout.write(self.style.WARNING('For Heroku, run:'))
            self.stdout.write(f'heroku config:set SCIENER_ACCESS_TOKEN="{token.access_token}" -a pickarooms')
            self.stdout.write(f'heroku config:set SCIENER_REFRESH_TOKEN="{token.refresh_token}" -a pickarooms')
            self.stdout.write('')
            self.stdout.write('=' * 60)
            
        except Exception as e:
            self.stdout.write(self.style.ERROR('=' * 60))
            self.stdout.write(self.style.ERROR('AUTHENTICATION FAILED'))
            self.stdout.write(self.style.ERROR('=' * 60))
            self.stdout.write('')
            self.stdout.write(self.style.ERROR(f'Error: {str(e)}'))
            self.stdout.write('')
            self.stdout.write('Please check:')
            self.stdout.write('1. Username and password are correct')
            self.stdout.write('2. Your TTLock account has API access')
            self.stdout.write('3. Client ID and Client Secret in env.py are correct')
            self.stdout.write('')
            raise CommandError(f'Authentication failed: {str(e)}')
