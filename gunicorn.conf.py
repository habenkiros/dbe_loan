# Gunicorn production config — used by Docker CMD / entrypoint.
import os

bind = os.getenv('GUNICORN_BIND', '0.0.0.0:8000')
workers = int(os.getenv('GUNICORN_WORKERS', '3') or '3')
threads = int(os.getenv('GUNICORN_THREADS', '2') or '2')
timeout = int(os.getenv('GUNICORN_TIMEOUT', '120') or '120')
graceful_timeout = int(os.getenv('GUNICORN_GRACEFUL_TIMEOUT', '30') or '30')
keepalive = int(os.getenv('GUNICORN_KEEPALIVE', '5') or '5')
accesslog = '-'
errorlog = '-'
loglevel = os.getenv('GUNICORN_LOG_LEVEL', 'info')
capture_output = True
# Avoid running as root inside the worker if the image later drops privileges.
forwarded_allow_ips = os.getenv('FORWARDED_ALLOW_IPS', '*')
