"""Production email readiness for Digital Apply / staff notices."""

from __future__ import annotations

from typing import Any, Dict

from django.conf import settings


def email_delivery_status() -> Dict[str, Any]:
    """
    Report whether outbound email is console (dev) or SMTP (production-ready).
    Does not open a network connection — config check only.
    """
    backend = (getattr(settings, 'EMAIL_BACKEND', '') or '').strip()
    is_console = 'console' in backend.lower()
    host = (getattr(settings, 'EMAIL_HOST', '') or '').strip()
    user = (getattr(settings, 'EMAIL_HOST_USER', '') or '').strip()
    ready = (not is_console) and bool(host)
    return {
        'backend': backend,
        'is_console': is_console,
        'smtp_configured': bool(host and user),
        'production_ready': ready,
        'from_email': getattr(settings, 'DEFAULT_FROM_EMAIL', '') or '',
        'hint': (
            'Configure EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend '
            'and EMAIL_HOST / EMAIL_HOST_USER / EMAIL_HOST_PASSWORD for real delivery.'
            if not ready
            else 'SMTP backend configured.'
        ),
    }
