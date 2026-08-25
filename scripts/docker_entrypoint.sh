#!/bin/sh
set -eu

mkdir -p /app/media /app/staticfiles

echo "[entrypoint] Applying migrations..."
python manage.py migrate --noinput

echo "[entrypoint] Collecting static files..."
python manage.py collectstatic --noinput

echo "[entrypoint] Starting gunicorn..."
exec gunicorn decsi_loan.wsgi:application -c gunicorn.conf.py
