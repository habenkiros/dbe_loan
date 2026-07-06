"""In-app notifications for collateral workflow."""

from __future__ import annotations

from django.urls import reverse

from loans.models import LoanNotification


def _collateral_summary_url(loan_request) -> str:
    return reverse('collateral:summary', args=[loan_request.pk])


def notify_collateral_assigned(loan_request, engineer) -> int:
    from loans.services.notifications import notify_users

    return notify_users(
        [engineer],
        loan_request=loan_request,
        kind=LoanNotification.KIND_COLLATERAL_ASSIGNED,
        title=f'Collateral assigned — {loan_request.loan_request_id}',
        message=(
            f'You are assigned to collateral estimation for {loan_request.applicant_name} '
            f'({loan_request.loan_request_id}).'
        ),
        url=_collateral_summary_url(loan_request),
    )


def notify_collateral_submitted(loan_request, *, recipients) -> int:
    from loans.services.notifications import notify_users

    return notify_users(
        recipients,
        loan_request=loan_request,
        kind=LoanNotification.KIND_COLLATERAL_SUBMITTED,
        title=f'Collateral submitted — {loan_request.loan_request_id}',
        message=(
            f'Collateral estimation submitted for {loan_request.applicant_name}. '
            f'Review from the collateral summary or engineering QA queue.'
        ),
        url=_collateral_summary_url(loan_request),
    )


def notify_engineering_returned(loan_request, officer, note: str = '') -> int:
    from loans.services.notifications import notify_users

    msg = f'Engineering returned collateral for {loan_request.loan_request_id} for correction.'
    if note:
        msg += f' Note: {note[:300]}'
    return notify_users(
        [officer] if officer else [],
        loan_request=loan_request,
        kind=LoanNotification.KIND_COLLATERAL_ENGINEERING_RETURN,
        title=f'Collateral returned — {loan_request.loan_request_id}',
        message=msg,
        url=_collateral_summary_url(loan_request),
    )


def notify_engineering_approved(loan_request, officer) -> int:
    from loans.services.notifications import notify_users

    return notify_users(
        [officer] if officer else [],
        loan_request=loan_request,
        kind=LoanNotification.KIND_COLLATERAL_ENGINEERING_APPROVED,
        title=f'Collateral approved — {loan_request.loan_request_id}',
        message=(
            f'Engineering approved collateral for {loan_request.applicant_name}. '
            f'Proceed with appraisal when ready.'
        ),
        url=_collateral_summary_url(loan_request),
    )


def engineering_review_recipients(loan_request):
    """Users to notify when collateral is submitted pending engineering QA."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    recipients = []
    if loan_request.assigned_engineer_id:
        recipients.append(loan_request.assigned_engineer)
    heads = User.objects.filter(role='engineering_head', is_active=True)
    recipients.extend(list(heads))
    return recipients
