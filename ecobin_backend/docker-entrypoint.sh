#!/bin/sh
set -e

if [ "$1" = "celery" ]; then
    shift
    exec celery -A ecobin_backend "$@"
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput 2>/dev/null || true

exec daphne -b 0.0.0.0 -p ${PORT:-8000} ecobin_backend.asgi:application
