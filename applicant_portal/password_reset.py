"""Forgot-password OTP helpers."""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from applicant_portal.models import ApplicantPasswordReset
from applicant_portal.notify import deliver_sms, notify_applicant


OTP_MINUTES = 15


def issue_password_reset(account, *, request=None) -> str:
    """Create OTP, deliver via SMS/outbox, return raw code (for tests only)."""
    from applicant_portal.security import client_ip

    # Invalidate prior open codes
    ApplicantPasswordReset.objects.filter(
        account=account, used_at__isnull=True,
    ).update(used_at=timezone.now())

    code = f'{secrets.randbelow(1_000_000):06d}'
    reset = ApplicantPasswordReset.objects.create(
        account=account,
        code_hash=make_password(code),
        expires_at=timezone.now() + timedelta(minutes=OTP_MINUTES),
        request_ip=client_ip(request) if request is not None else None,
    )
    body = (
        f'Your Digital Apply reset code is {code}. '
        f'Valid for {OTP_MINUTES} minutes. If you did not request this, ignore.'
    )
    deliver_sms(account.phone_number, body, subject='Password reset')
    notify_applicant(
        account,
        title='Password reset code sent',
        message=f'A 6-digit code was sent to {account.phone_number}. '
                f'It expires in {OTP_MINUTES} minutes.',
        kind='info',
    )
    return code  # only used in tests / secure debug when DEBUG


def verify_and_reset_password(account, code: str, new_password: str) -> bool:
    code = (code or '').strip()
    if not code:
        return False
    candidates = ApplicantPasswordReset.objects.filter(
        account=account, used_at__isnull=True, expires_at__gt=timezone.now(),
    ).order_by('-created_at')[:5]
    matched = None
    for row in candidates:
        if check_password(code, row.code_hash):
            matched = row
            break
    if not matched:
        return False
    account.set_password(new_password)
    account.failed_login_attempts = 0
    account.locked_until = None
    account.save(update_fields=[
        'password_hash', 'password_changed_at', 'failed_login_attempts',
        'locked_until', 'updated_at',
    ])
    matched.used_at = timezone.now()
    matched.save(update_fields=['used_at'])
    ApplicantPasswordReset.objects.filter(
        account=account, used_at__isnull=True,
    ).exclude(pk=matched.pk).update(used_at=timezone.now())
    return True
