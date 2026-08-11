"""Applicant-facing alerts + staff intake notifications."""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)


def notify_applicant(
    account,
    *,
    title: str,
    message: str,
    kind: str = 'info',
    application=None,
    also_sms: bool = False,
) -> None:
    from applicant_portal.models import ApplicantNotification, ApplicantMessageOutbox

    if not account:
        return
    ApplicantNotification.objects.create(
        account=account,
        application=application,
        kind=kind,
        title=title[:160],
        message=message,
    )
    # Best-effort email
    email = (getattr(account, 'email', None) or '').strip()
    if email:
        try:
            send_mail(
                subject=title[:120],
                message=message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@decsi.local'),
                recipient_list=[email],
                fail_silently=True,
            )
            ApplicantMessageOutbox.objects.create(
                channel=ApplicantMessageOutbox.CHANNEL_EMAIL,
                recipient=email,
                subject=title[:160],
                body=message,
                sent=True,
            )
        except Exception:
            logger.exception('Applicant email failed')

    if also_sms:
        deliver_sms(account.phone_number, message, subject=title)


def deliver_sms(phone: str, body: str, *, subject: str = '') -> bool:
    """
    SMS gateway hook. Without APPLICANT_SMS_URL we log to outbox only.
    Set APPLICANT_SMS_URL + APPLICANT_SMS_API_KEY for a simple POST form.
    """
    from applicant_portal.models import ApplicantMessageOutbox
    import requests

    phone = (phone or '').strip()
    if not phone:
        return False
    url = (getattr(settings, 'APPLICANT_SMS_URL', '') or '').strip()
    api_key = (getattr(settings, 'APPLICANT_SMS_API_KEY', '') or '').strip()
    if not url:
        ApplicantMessageOutbox.objects.create(
            channel=ApplicantMessageOutbox.CHANNEL_LOG,
            recipient=phone,
            subject=subject[:160],
            body=body,
            sent=False,
            detail={'reason': 'no_sms_gateway'},
        )
        logger.info('SMS outbox (no gateway) → %s: %s', phone, body[:120])
        return False
    try:
        headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
        resp = requests.post(
            url,
            json={'to': phone, 'message': body, 'subject': subject},
            headers=headers,
            timeout=15,
        )
        ok = resp.status_code < 400
        ApplicantMessageOutbox.objects.create(
            channel=ApplicantMessageOutbox.CHANNEL_SMS,
            recipient=phone,
            subject=subject[:160],
            body=body,
            sent=ok,
            detail={'status_code': resp.status_code, 'text': resp.text[:300]},
        )
        return ok
    except Exception as exc:
        logger.exception('SMS send failed')
        ApplicantMessageOutbox.objects.create(
            channel=ApplicantMessageOutbox.CHANNEL_SMS,
            recipient=phone,
            subject=subject[:160],
            body=body,
            sent=False,
            detail={'error': str(exc)[:200]},
        )
        return False


def branch_staff_qs(branch):
    from loans.models import CustomUser

    if not branch:
        return CustomUser.objects.none()
    return CustomUser.objects.filter(
        is_active=True,
        branch=branch,
        role__in=(
            'loan_officer',
            'branch_manager',
            'credit_loan_officer',
            'credit_head',
        ),
    )


def assign_default_officer(loan) -> Optional[object]:
    """Assign first active loan officer at the branch if none set."""
    from loans.models import CustomUser

    if loan.assigned_loan_officer_id:
        return loan.assigned_loan_officer
    officer = (
        CustomUser.objects
        .filter(is_active=True, branch_id=loan.branch_id, role='loan_officer')
        .order_by('id')
        .first()
    )
    if not officer:
        officer = (
            CustomUser.objects
            .filter(is_active=True, branch_id=loan.branch_id, role='branch_manager')
            .order_by('id')
            .first()
        )
    if officer:
        loan.assigned_loan_officer = officer
        loan.save(update_fields=['assigned_loan_officer'])
    return officer


def notify_staff_online_intake(loan) -> int:
    from loans.services.notifications import notify_users

    users = list(branch_staff_qs(loan.branch))
    # Superusers always see intake
    from loans.models import CustomUser
    supers = list(CustomUser.objects.filter(is_active=True, is_superuser=True)[:20])
    people = users + supers
    amt = loan.amount_requested
    title = f'LOAN REQUESTED · {loan.loan_request_id}'
    message = (
        f'CRITICAL: new online loan request from {loan.applicant_name}. '
        f'Requested amount: {amt} ETB · '
        f'{loan.category.name if loan.category_id else "loan"} · '
        f'branch {loan.branch.name}. Queue ID {loan.loan_request_id}.'
    )
    try:
        url = reverse('loan_request_detail', args=[loan.pk])
    except Exception:
        url = reverse('view_loan_requests')
    return notify_users(
        people,
        loan_request=loan,
        kind='online_intake',
        title=title,
        message=message,
        url=url,
        email_subject=title,
    )


def linked_online_application(loan):
    """Return OnlineApplication for a LoanRequest when originating from Digital Apply."""
    if not loan:
        return None
    try:
        return loan.online_application
    except Exception:
        return None


def notify_applicant_loan_event(loan, *, event: str) -> None:
    """
    Critical customer notices for loan requested / approved.
    event: requested | approved | declined | intake
    """
    app = linked_online_application(loan)
    if not app or not app.applicant_id:
        return
    account = app.applicant
    qid = loan.loan_request_id
    requested = loan.amount_requested

    if event == 'requested':
        notify_applicant(
            account,
            title='LOAN REQUESTED',
            message=(
                f'Your loan request is recorded. Amount requested: {requested} ETB. '
                f'Queue ID: {qid}. Keep this ID for all branch enquiries.'
            ),
            kind='success',
            application=app,
            also_sms=True,
        )
        return

    if event == 'intake':
        notify_applicant(
            account,
            title='Loan request accepted for processing',
            message=(
                f'Branch intake accepted your loan request {qid} '
                f'(requested {requested} ETB). Processing continues toward credit decision.'
            ),
            kind='info',
            application=app,
            also_sms=True,
        )
        return

    if event == 'approved':
        final = loan.committee_final_amount or requested
        notify_applicant(
            account,
            title='LOAN APPROVED',
            message=(
                f'Credit decision: LOAN APPROVED. Approved amount: {final} ETB '
                f'(you requested {requested} ETB). Queue ID: {qid}. '
                f'Sign in to Digital Apply to view your repayment schedule when ready.'
            ),
            kind='success',
            application=app,
            also_sms=True,
        )
        return

    if event == 'declined':
        notify_applicant(
            account,
            title='Loan not approved',
            message=(
                f'Credit decision: not approved for queue {qid} '
                f'(requested {requested} ETB). Contact your branch for details.'
            ),
            kind='warn',
            application=app,
            also_sms=True,
        )


def cancel_submitted_application(application, *, reason: str = '') -> None:
    """Applicant withdraw: cancel draft or early-stage online loan."""
    from django.db import transaction
    from loans.models import LoanRequest

    with transaction.atomic():
        application = type(application).objects.select_for_update().get(pk=application.pk)
        if application.status == application.STATUS_CANCELLED:
            return
        application.status = application.STATUS_CANCELLED
        application.withdrawn_at = timezone.now()
        application.withdraw_reason = (reason or 'Withdrawn by applicant')[:255]
        application.save(update_fields=[
            'status', 'withdrawn_at', 'withdraw_reason', 'updated_at',
        ])
        loan = application.loan_request
        if loan and loan.source_channel == LoanRequest.SOURCE_ONLINE:
            # Only soft-close while still early (not collateral/appraisal advanced).
            advanced = bool(
                loan.queue_approved
                or loan.appraisal_completed_at
                or loan.collateral_submitted_at
                or loan.disbursed_at
            )
            if not advanced and (loan.status or '').lower() in ('pending', 'rejected', ''):
                loan.status = 'Rejected'
                loan.save(update_fields=['status'])
