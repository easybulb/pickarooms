# Docker Setup for PickARooms

This document explains how to use Docker for local development with Redis and Celery.

## Prerequisites

1. Docker Desktop installed and running
2. Docker Compose installed (comes with Docker Desktop)

## Quick Start

### 1. Start all services (Redis + Celery workers)

```powershell
docker-compose up -d
```

This starts:
- **Redis** on port 6379
- **Celery Worker** for processing tasks
- **Celery Beat** for scheduled tasks

### 2. View logs

```powershell
# View all logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f celery-worker
docker-compose logs -f celery-beat
docker-compose logs -f redis
```

### 3. Stop all services

```powershell
docker-compose down
```

### 4. Restart services

```powershell
docker-compose restart
```

### 5. Rebuild after code changes

```powershell
docker-compose down
docker-compose up -d --build
```

## Running Django Development Server

The Django dev server still runs on your local machine (not in Docker):

```powershell
python manage.py runserver
```

Only Redis and Celery workers run in Docker containers.

## Checking Service Health

```powershell
# Check if containers are running
docker-compose ps

# Check Redis connection
docker exec -it pickarooms-redis redis-cli ping
# Should return: PONG
```

## Environment Variables

The `docker-compose.yml` file automatically:
- Sets `REDIS_URL=redis://redis:6379/0` for containers
- Mounts your code directory so changes are reflected immediately
- Uses your local database (PostgreSQL via DATABASE_URL in env.py)

## Troubleshooting

### Port 6379 already in use
If you have Redis installed locally, stop it first:
```powershell
# Stop local Redis service if running
Get-Service -Name Redis* | Stop-Service
```

### Containers won't start
```powershell
# Remove old containers and volumes
docker-compose down -v

# Rebuild and start fresh
docker-compose up -d --build
```

### Check Docker Desktop is running
Ensure Docker Desktop is running (check system tray for whale icon).

## Production (Heroku)

For Heroku deployment:
1. Add Heroku Redis add-on: `heroku addons:create heroku-redis:mini -a pickarooms`
2. The `REDIS_URL` config var is automatically set
3. Deploy as usual with `git push heroku main`
