import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

username = 'admin'
email = 'admin@pickarooms.com'
password = 'admin123'

if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username, email, password)
    print(f'Superuser created successfully!')
    print(f'Username: {username}')
    print(f'Password: {password}')
    print(f'Email: {email}')
else:
    print(f'Superuser "{username}" already exists!')
