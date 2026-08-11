"""Applicant portal security: settings, password policy, lockout, throttles."""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal
from typing import List, Optional, Tuple

from django.core.exceptions import ValidationError
from django.utils import timezone

# Sequences / common weak passwords refused by policy
_COMMON_PASSWORDS = frozenset({
    'password', 'password1', 'password123', 'passw0rd', '12345678', '123456789',
    '1234567890', 'qwerty123', 'abc12345', 'iloveyou', 'admin123', 'welcome1',
    'letmein1', 'changeme', 'decsi123', 'decsi1234', 'ethiopia', 'tigray12',
    'loan1234', 'applicant', 'secret12', 'secret123',
})


def client_ip(request) -> Optional[str]:
    forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    return forwarded or request.META.get('REMOTE_ADDR') or None


def client_user_agent(request) -> str:
    return (request.META.get('HTTP_USER_AGENT') or '')[:512]


def assert_no_letters(raw: str, field_label: str = 'This field') -> None:
    if re.search(r'[A-Za-z]', raw or ''):
        raise ValidationError(f'{field_label} must not contain letters.')


def assert_phone_raw_chars(raw: str) -> None:
    """Phone may only use digits, optional +, spaces, dashes, parentheses."""
    s = raw or ''
    if re.search(r'[A-Za-z]', s):
        raise ValidationError('Mobile number must not contain letters.')
    if re.search(r'[^\d+\s\-().]', s.strip()):
        raise ValidationError(
            'Mobile number may only include digits and an optional + (e.g. 0911… or +2519…).',
        )


def normalize_phone(raw: str) -> str:
    """Normalize Ethiopian Ethio Telecom / Safaricom-style mobiles for login keys.

    Accepts and stores as local 09xxxxxxxx or 07xxxxxxxx:
      09… / 9… / +2519… / 2519…
      07… / 7… / +2517… / 2517…
    """
    assert_phone_raw_chars(raw)
    s = (raw or '').strip()
    if not s:
        return ''
    if s.startswith('+'):
        digits = re.sub(r'\D', '', s[1:])
    else:
        digits = re.sub(r'\D', '', s)

    # International Ethiopia: 251 + 9/7 + 8 digits
    if digits.startswith('251') and len(digits) >= 12:
        digits = digits[3:]

    # Local without trunk 0: 9xxxxxxxx or 7xxxxxxxx
    if len(digits) == 9 and digits[0] in ('9', '7'):
        digits = '0' + digits

    # Already local 09 / 07
    if len(digits) == 10 and digits[0] == '0' and digits[1] in ('9', '7'):
        return digits

    return digits


def validate_phone_format(phone: str) -> None:
    if not phone:
        raise ValidationError('Mobile number is required.')
    # Ethio Telecom 09… and Safaricom 07… (after normalize)
    if not re.fullmatch(r'0[97]\d{8}', phone):
        raise ValidationError(
            'Enter a valid Ethiopian mobile number '
            '(e.g. 0911222333, 911222333, 07…, 7…, or +2519… / +2517…).',
        )


def normalize_customer_number(raw: str) -> str:
    """Customer numbers are numeric only (no letters)."""
    s = (raw or '').strip()
    assert_no_letters(s, 'Customer number')
    # Digits only after stripping spaces/dashes that CBS UIs often insert
    if re.search(r'[^\d\s\-]', s):
        raise ValidationError('Customer number may only contain digits (spaces or dashes optional).')
    digits = re.sub(r'\D', '', s)
    return digits


def validate_customer_number_format(cn: str) -> None:
    if not cn:
        raise ValidationError('Customer number is required.')
    if not re.fullmatch(r'\d{3,40}', cn):
        raise ValidationError('Customer number must be 3–40 digits (letters not allowed).')

def get_portal_settings():
    from applicant_portal.models import ApplicantPortalSettings

    obj = ApplicantPortalSettings.objects.order_by('pk').first()
    if obj:
        return obj
    obj = ApplicantPortalSettings.objects.create()
    return obj


def portal_enabled() -> bool:
    return bool(get_portal_settings().enabled)


def processing_fee_amount() -> Decimal:
    return Decimal(get_portal_settings().processing_fee_etb).quantize(Decimal('0.01'))


def password_policy_hints(policy=None) -> List[str]:
    policy = policy or get_portal_settings()
    hints = [f'At least {policy.min_password_length} characters']
    if policy.require_uppercase:
        hints.append('one uppercase letter')
    if policy.require_lowercase:
        hints.append('one lowercase letter')
    if policy.require_digit:
        hints.append('one number')
    if policy.require_special:
        hints.append('one special character (!@#$%…)')
    hints.append('not a common password or your phone number')
    return hints


def validate_applicant_password(
    password: str,
    *,
    phone: str = '',
    full_name: str = '',
    policy=None,
) -> None:
    policy = policy or get_portal_settings()
    password = password or ''
    errors: List[str] = []

    min_len = int(policy.min_password_length or 10)
    if len(password) < min_len:
        errors.append(f'Password must be at least {min_len} characters.')
    if policy.require_uppercase and not re.search(r'[A-Z]', password):
        errors.append('Include at least one uppercase letter.')
    if policy.require_lowercase and not re.search(r'[a-z]', password):
        errors.append('Include at least one lowercase letter.')
    if policy.require_digit and not re.search(r'\d', password):
        errors.append('Include at least one number.')
    if policy.require_special and not re.search(r'[^A-Za-z0-9]', password):
        errors.append('Include at least one special character (e.g. !@#$%).')

    lower = password.lower()
    if lower in _COMMON_PASSWORDS or lower.replace(' ', '') in _COMMON_PASSWORDS:
        errors.append('This password is too common. Choose a stronger one.')

    phone_digits = re.sub(r'\D', '', phone or '')
    if phone_digits and len(phone_digits) >= 6 and phone_digits in re.sub(r'\D', '', password):
        errors.append('Password must not contain your phone number.')

    # Block full name token if long enough
    for part in re.split(r'[\s\-_\.]+', (full_name or '').lower()):
        if len(part) >= 4 and part in lower:
            errors.append('Password must not contain your name.')
            break

    if re.search(r'(.)\1{3,}', password):
        errors.append('Avoid long runs of the same character (e.g. aaaa).')

    if errors:
        raise ValidationError(errors)


def log_auth_event(
    event_type: str,
    *,
    request=None,
    account=None,
    phone: str = '',
    detail: Optional[dict] = None,
) -> None:
    from applicant_portal.models import ApplicantAuthEvent

    ApplicantAuthEvent.objects.create(
        event_type=event_type,
        account=account if getattr(account, 'pk', None) else None,
        phone_number=phone or (getattr(account, 'phone_number', '') if account else ''),
        ip_address=client_ip(request) if request is not None else None,
        user_agent=client_user_agent(request) if request is not None else '',
        detail=detail or {},
    )


def _get_ip_throttle(ip: str):
    from applicant_portal.models import ApplicantIpThrottle

    row, _ = ApplicantIpThrottle.objects.get_or_create(ip_address=ip)
    return row


def is_ip_locked(request) -> bool:
    ip = client_ip(request)
    if not ip:
        return False
    row = _get_ip_throttle(ip)
    return bool(row.is_locked())


def check_register_rate(request) -> Tuple[bool, str]:
    """Return (ok, message)."""
    policy = get_portal_settings()
    ip = client_ip(request)
    if not ip:
        return True, ''
    row = _get_ip_throttle(ip)
    if row.is_locked():
        return False, lockout_message(policy)
    limit = int(policy.register_rate_limit_per_hour or 10)
    now = timezone.now()
    if not row.register_window_start or (now - row.register_window_start) > timedelta(hours=1):
        row.register_window_start = now
        row.register_count = 0
        row.save(update_fields=['register_window_start', 'register_count', 'updated_at'])
    if int(row.register_count or 0) >= limit:
        return False, (
            f'Too many registration attempts from this network. '
            f'Try again in up to one hour.'
        )
    return True, ''


def note_register_attempt(request) -> None:
    ip = client_ip(request)
    if not ip:
        return
    row = _get_ip_throttle(ip)
    now = timezone.now()
    if not row.register_window_start or (now - row.register_window_start) > timedelta(hours=1):
        row.register_window_start = now
        row.register_count = 1
    else:
        row.register_count = int(row.register_count or 0) + 1
    row.save(update_fields=['register_window_start', 'register_count', 'updated_at'])


def lockout_message(policy=None) -> str:
    policy = policy or get_portal_settings()
    mins = int(policy.lockout_minutes or 15)
    return (
        f'Too many failed attempts. Try again in about {mins} minutes, '
        f'or contact a DECSI branch for help.'
    )


def register_failed_login(account, request, phone: str) -> bool:
    from applicant_portal.models import ApplicantAuthEvent

    policy = get_portal_settings()
    locked = False
    detail = {'phone': phone}

    if account is not None:
        account.failed_login_attempts = int(account.failed_login_attempts or 0) + 1
        if account.failed_login_attempts >= int(policy.max_failed_logins or 5):
            account.locked_until = timezone.now() + timedelta(
                minutes=int(policy.lockout_minutes or 15),
            )
            locked = True
            detail['locked_until'] = account.locked_until.isoformat()
        account.save(update_fields=['failed_login_attempts', 'locked_until', 'updated_at'])

    ip = client_ip(request)
    if ip:
        row = _get_ip_throttle(ip)
        row.failed_login_attempts = int(row.failed_login_attempts or 0) + 1
        if row.failed_login_attempts >= int(policy.max_failed_logins or 5):
            row.lockout_until = timezone.now() + timedelta(
                minutes=int(policy.lockout_minutes or 15),
            )
            locked = True
            detail['ip_lockout_until'] = row.lockout_until.isoformat()
        row.save(update_fields=['failed_login_attempts', 'lockout_until', 'updated_at'])

    log_auth_event(
        ApplicantAuthEvent.EVT_LOGIN_FAILED,
        request=request,
        account=account,
        phone=phone,
        detail=detail,
    )
    if locked:
        log_auth_event(
            ApplicantAuthEvent.EVT_LOGIN_LOCKED,
            request=request,
            account=account,
            phone=phone,
            detail=detail,
        )
    return locked


def register_successful_login(account, request) -> None:
    from applicant_portal.models import ApplicantAuthEvent

    account.failed_login_attempts = 0
    account.locked_until = None
    account.last_login_ip = client_ip(request)
    account.last_login_at = timezone.now()
    account.save(update_fields=[
        'failed_login_attempts', 'locked_until', 'last_login_ip',
        'last_login_at', 'updated_at',
    ])
    ip = client_ip(request)
    if ip:
        row = _get_ip_throttle(ip)
        row.failed_login_attempts = 0
        row.lockout_until = None
        row.save(update_fields=['failed_login_attempts', 'lockout_until', 'updated_at'])
    log_auth_event(
        ApplicantAuthEvent.EVT_LOGIN_SUCCESS,
        request=request,
        account=account,
        phone=account.phone_number,
    )


def session_idle_seconds(policy=None) -> int:
    policy = policy or get_portal_settings()
    return max(5, int(policy.session_idle_minutes or 30)) * 60
