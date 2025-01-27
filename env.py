import os

# Secret Key and Debug Mode
os.environ['SECRET_KEY'] = 'bxiy%(=aw*_9cb-hpdve+06p4jk-(toj^f2$h1tcvyv8qlg(y)'
os.environ['DEBUG'] = 'True'

# Allowed Hosts
os.environ['ALLOWED_HOSTS'] = '127.0.0.1,localhost,.herokuapp.com'

# Local Database Configuration
os.environ['DATABASE_NAME'] = 'guest_checkin'
os.environ['DATABASE_USER'] = 'checkin_user'
os.environ['DATABASE_PASSWORD'] = 'Ifeoma123'
os.environ['DATABASE_HOST'] = '127.0.0.1'
os.environ['DATABASE_PORT'] = '5432'
