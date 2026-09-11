"""Staff auth hardening: lockout, TOTP MFA, security audit helpers."""
from __future__ import annotations

import base64
import hashlib
from datetime import timedelta
from typing import Any, Optional

import pyotp
from django.conf import settings
from django.utils import timezone

from .models import CustomUser, IpLoginThrottle, SecurityAuditLog

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover
    Fernet = None
    InvalidToken = Exception


SESSION_MFA_USER_ID = 'mfa_pending_user_id'
SESSION_MFA_BACKEND = 'mfa_pending_backend'
SESSION_MFA_SETUP_SECRET = 'mfa_setup_secret_plain'


def client_ip(request) -> Optional[str]:
    forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    return forwarded or request.META.get('REMOTE_ADDR') or None


def client_user_agent(request) -> str:
    return (request.META.get('HTTP_USER_AGENT') or '')[:512]


def log_security_event(
    event_type: str,
    *,
    request=None,
    user: Optional[CustomUser] = None,
    username: str = '',
    detail: Optional[dict] = None,
) -> SecurityAuditLog:
    ip = client_ip(request) if request is not None else None
    ua = client_user_agent(request) if request is not None else ''
    uname = username or (getattr(user, 'username', '') if user else '')
    return SecurityAuditLog.objects.create(
        event_type=event_type,
        username=uname or '',
        user=user if getattr(user, 'pk', None) else None,
        ip_address=ip,
        user_agent=ua,
        detail=detail or {},
    )


def max_failed_attempts() -> int:
    return int(getattr(settings, 'LOGIN_MAX_FAILED_ATTEMPTS', 5) or 5)


def lockout_minutes() -> int:
    return int(getattr(settings, 'LOGIN_LOCKOUT_MINUTES', 15) or 15)


def mfa_required() -> bool:
    return bool(getattr(settings, 'MFA_REQUIRED', False))


def mfa_issuer() -> str:
    from loans.branding import mfa_issuer_default
    return getattr(settings, 'MFA_TOTP_ISSUER', None) or mfa_issuer_default()


def _fernet() -> Optional[Any]:
    if Fernet is None:
        return None
    digest = hashlib.sha256(settings.SECRET_KEY.encode('utf-8')).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_mfa_secret(plain: str) -> str:
    f = _fernet()
    if f is None:
        # Fallback: still store; infra should encrypt DB at rest.
        return plain
    return f.encrypt(plain.encode('utf-8')).decode('utf-8')


def decrypt_mfa_secret(blob: str) -> str:
    if not blob:
        return ''
    f = _fernet()
    if f is None:
        return blob
    try:
        return f.decrypt(blob.encode('utf-8')).decode('utf-8')
    except InvalidToken:
        # Allow reading legacy plaintext during migration window.
        return blob


def generate_mfa_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(user: CustomUser, secret: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(
        name=user.username,
        issuer_name=mfa_issuer(),
    )


def verify_totp(secret: str, code: str) -> bool:
    code = (code or '').strip().replace(' ', '')
    if not secret or not code.isdigit() or len(code) not in (6, 8):
        return False
    totp = pyotp.TOTP(secret)
    # valid_window=1 tolerates ±30s clock skew
    return bool(totp.verify(code, valid_window=1))


def user_mfa_secret(user: CustomUser) -> str:
    return decrypt_mfa_secret(user.mfa_secret_encrypted or '')


def clear_user_lockout(user: CustomUser) -> None:
    user.failed_login_attempts = 0
    user.lockout_until = None
    user.save(update_fields=['failed_login_attempts', 'lockout_until'])


def register_failed_login(user: Optional[CustomUser], request, username: str) -> bool:
    """
    Increment failure counters. Returns True if the account (or IP) is now locked.
    """
    locked = False
    detail = {'username': username}

    if user is not None:
        user.failed_login_attempts = int(user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= max_failed_attempts():
            user.lockout_until = timezone.now() + timedelta(minutes=lockout_minutes())
            locked = True
            detail['lockout_until'] = user.lockout_until.isoformat()
        user.save(update_fields=['failed_login_attempts', 'lockout_until'])

    ip = client_ip(request)
    if ip:
        throttle, _ = IpLoginThrottle.objects.get_or_create(ip_address=ip)
        throttle.failed_attempts = int(throttle.failed_attempts or 0) + 1
        if throttle.failed_attempts >= max_failed_attempts():
            throttle.lockout_until = timezone.now() + timedelta(minutes=lockout_minutes())
            locked = True
            detail['ip_lockout_until'] = throttle.lockout_until.isoformat()
        throttle.save(update_fields=['failed_attempts', 'lockout_until', 'updated_at'])

    log_security_event(
        SecurityAuditLog.EVT_LOGIN_FAILED,
        request=request,
        user=user,
        username=username,
        detail=detail,
    )
    if locked:
        log_security_event(
            SecurityAuditLog.EVT_LOGIN_LOCKED,
            request=request,
            user=user,
            username=username,
            detail=detail,
        )
    return locked


def register_successful_password(user: CustomUser, request) -> None:
    user.failed_login_attempts = 0
    user.lockout_until = None
    user.save(update_fields=['failed_login_attempts', 'lockout_until'])
    ip = client_ip(request)
    if ip:
        IpLoginThrottle.objects.filter(ip_address=ip).update(
            failed_attempts=0,
            lockout_until=None,
        )


def is_ip_locked(request) -> bool:
    ip = client_ip(request)
    if not ip:
        return False
    row = IpLoginThrottle.objects.filter(ip_address=ip).first()
    return bool(row and row.is_locked())


def lockout_message() -> str:
    return (
        f'Too many failed login attempts. Try again in about '
        f'{lockout_minutes()} minutes, or contact an administrator.'
    )


def user_has_mfa_enrolled(user) -> bool:
    return bool(getattr(user, 'mfa_enabled', False) and (getattr(user, 'mfa_secret_encrypted', '') or ''))


def committee_stepup_required() -> bool:
    return bool(getattr(settings, 'COMMITTEE_STEPUP_REQUIRED', True))


def verify_committee_stepup(user, *, password: str, mfa_code: str = '') -> tuple:
    """
    Re-auth before irreversible committee actions.
    Always requires password; TOTP also required when MFA is enrolled.
    Returns (ok, error_message).
    """
    if not committee_stepup_required():
        return True, ''
    if not user or not user.check_password(password or ''):
        return False, 'Confirm your password to continue.'
    if user_has_mfa_enrolled(user):
        secret = user_mfa_secret(user)
        if not verify_totp(secret, mfa_code or ''):
            return False, 'Enter a valid authenticator code to continue.'
    return True, ''
