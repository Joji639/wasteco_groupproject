#!/bin/sh
set -e

echo "Waiting for database..."
python -c "
import time, os, sys
import socket
host = os.environ.get('DB_HOST', 'db')
port = int(os.environ.get('DB_PORT', 5432))
for i in range(30):
    try:
        s = socket.create_connection((host, port), timeout=2)
        s.close()
        print('Database is ready!')
        sys.exit(0)
    except (ConnectionRefusedError, OSError):
        time.sleep(1)
print('Database not ready, proceeding anyway...')
"
echo "Waiting for Redis..."
python -c "
import time, os, sys
import socket
host = os.environ.get('REDIS_HOST', 'redis')
port = int(os.environ.get('REDIS_PORT', 6379))
for i in range(30):
    try:
        s = socket.create_connection((host, port), timeout=2)
        s.close()
        print('Redis is ready!')
        sys.exit(0)
    except (ConnectionRefusedError, OSError):
        time.sleep(1)
print('Redis not ready, proceeding anyway...')
"

if [ "$1" = "celery" ]; then
    shift
    echo "Starting Celery worker..."
    exec celery -A ecobin_backend worker --loglevel=info "$@"
fi

if [ "$1" = "celery-beat" ]; then
    shift
    echo "Starting Celery beat..."
    exec celery -A ecobin_backend beat --loglevel=info "$@"
fi

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput 2>/dev/null || true

echo "Starting Daphne ASGI server..."
exec daphne -b 0.0.0.0 -p ${PORT:-8000} ecobin_backend.asgi:application
