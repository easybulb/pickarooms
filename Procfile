web: gunicorn pickarooms.wsgi
worker: celery -A pickarooms worker --loglevel=info
beat: celery -A pickarooms beat --loglevel=info
