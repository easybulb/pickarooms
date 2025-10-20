import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickarooms.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

# Delete old admin user if exists
try:
    old_admin = User.objects.get(username='admin')
    old_admin.delete()
    print('Old admin user deleted successfully!')
except User.DoesNotExist:
    print('Old admin user does not exist.')
