web: gunicorn pickarooms.wsgi
worker: celery -A pickarooms worker --loglevel=info --concurrency=2 --max-tasks-per-child=100
beat: celery -A pickarooms beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
