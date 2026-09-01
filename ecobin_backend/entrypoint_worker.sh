#!/bin/sh
set -e

echo "Starting Celery worker..."
exec celery -A ecobin_backend worker \
    --loglevel=info \
    --concurrency=2
