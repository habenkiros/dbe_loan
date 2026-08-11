#!/bin/sh
set -eu

# Named volumes often mount as root; ensure appuser can write media/static.
if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/media /app/staticfiles
  chown -R appuser:appuser /app/media /app/staticfiles
  exec gosu appuser "$0" "$@"
fi

echo "[entrypoint] Applying migrations..."
python manage.py migrate --noinput

echo "[entrypoint] Collecting static files..."
python manage.py collectstatic --noinput

echo "[entrypoint] Starting gunicorn..."
exec gunicorn decsi_loan.wsgi:application -c gunicorn.conf.py
