# loans/services/notifications.py
"""In-app and email notifications for the approval committee workflow."""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

logger = logging.getLogger(__name__)


def _loan_detail_url(loan_request) -> str:
    path = reverse('loan_request_detail_manager', args=[loan_request.pk])
    site = getattr(settings, 'SITE_URL', '').rstrip('/')
    return f'{site}{path}' if site else path


def notify_users(
    users: Iterable,
    *,
    loan_request,
    kind: str,
    title: str,
    message: str,
    url: str = '',
    email_subject: Optional[str] = None,
) -> int:
    from loans.models import LoanNotification

    if not url:
        url = _loan_detail_url(loan_request)

    created = 0
    seen_ids = set()
    for user in users:
        if not user or not getattr(user, 'is_active', True):
            continue
        if user.pk in seen_ids:
            continue
        seen_ids.add(user.pk)

        LoanNotification.objects.create(
            user=user,
            loan_request=loan_request,
            kind=kind,
            title=title,
            message=message,
            url=url,
        )
        created += 1

        if getattr(user, 'email', None):
            try:
                send_mail(
                    subject=email_subject or title,
                    message=f'{message}\n\nView loan: {url}',
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@decsi.local'),
                    recipient_list=[user.email],
                    fail_silently=True,
                )
            except Exception:
                logger.exception('Failed to send committee email to %s', user.email)

    return created


def notify_eligible_voters(loan_request, level, *, title: str, message: str, kind: str) -> int:
    from loans.committee import get_eligible_voters
    from loans.delegation import SCOPE_COMMITTEE, expand_users_with_delegates

    voters = expand_users_with_delegates(get_eligible_voters(loan_request, level), SCOPE_COMMITTEE)
    return notify_users(
        voters,
        loan_request=loan_request,
        kind=kind,
        title=title,
        message=message,
    )


def notify_assigned_officer(loan_request, *, title: str, message: str, kind: str, url: str = '') -> int:
    officer = getattr(loan_request, 'assigned_loan_officer', None)
    if not officer:
        return 0
    if not url:
        url = reverse('loan_request_detail', args=[loan_request.pk])
    from loans.delegation import SCOPE_APPRAISAL, expand_users_with_delegates

    people = expand_users_with_delegates([officer], SCOPE_APPRAISAL)
    return notify_users(
        people,
        loan_request=loan_request,
        kind=kind,
        title=title,
        message=message,
        url=url,
    )
