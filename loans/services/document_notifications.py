# loans/services/document_notifications.py
"""In-app notifications for loan application document workflow."""

from __future__ import annotations

from django.urls import reverse

from .notifications import notify_assigned_officer, notify_users


def _loan_detail_url(loan_request) -> str:
    return reverse('loan_request_detail', args=[loan_request.pk])


def _document_reviewers(loan_request):
    from loans.models import CustomUser, LoanRequestDocument

    users = []
    if loan_request.assigned_loan_officer_id:
        users.append(loan_request.assigned_loan_officer)
    if loan_request.assigned_engineer_id:
        users.append(loan_request.assigned_engineer)
    if not users:
        users = list(
            CustomUser.objects.filter(
                is_active=True,
                role='branch_manager',
                branch_id=loan_request.branch_id,
            )
        )
    return users


def _branch_managers(loan_request):
    from loans.models import CustomUser

    return list(
        CustomUser.objects.filter(
            is_active=True,
            role='branch_manager',
            branch_id=loan_request.branch_id,
        )
    )


def notify_document_uploaded(document) -> int:
    from loans.models import LoanNotification, LoanRequestDocument

    lr = document.loan_request
    lr_id = lr.loan_request_id
    doc_name = document.document_type.name
    status = document.get_auth_status_display()
    url = _loan_detail_url(lr)

    count = notify_users(
        _document_reviewers(lr),
        loan_request=lr,
        kind=LoanNotification.KIND_DOCUMENT_UPLOADED,
        title=f'Document uploaded: {lr_id} — {doc_name}',
        message=f'"{doc_name}" was uploaded. Automated check status: {status}.',
        url=url,
    )

    if document.auth_status == LoanRequestDocument.AUTH_NEEDS_REVIEW:
        count += notify_document_needs_review(document)
    return count


def notify_document_needs_review(document) -> int:
    from loans.models import LoanNotification

    lr = document.loan_request
    doc_name = document.document_type.name
    hints = (document.automated_checks or {}).get('messages') or []
    hint_text = '\n'.join(f'• {m}' for m in hints[:5]) if hints else 'Please verify or reject this document.'

    return notify_users(
        _document_reviewers(lr),
        loan_request=lr,
        kind=LoanNotification.KIND_DOCUMENT_NEEDS_REVIEW,
        title=f'Document review needed: {lr.loan_request_id} — {doc_name}',
        message=f'"{doc_name}" requires manual review.\n\n{hint_text}',
        url=_loan_detail_url(lr),
    )


def notify_document_verified(document, by_user) -> int:
    from loans.models import LoanNotification

    lr = document.loan_request
    return notify_users(
        _branch_managers(lr),
        loan_request=lr,
        kind=LoanNotification.KIND_DOCUMENT_VERIFIED,
        title=f'Document verified: {lr.loan_request_id}',
        message=(
            f'"{document.document_type.name}" was verified by {by_user.username}.'
            f'{(" Notes: " + document.auth_notes) if document.auth_notes else ""}'
        ),
        url=_loan_detail_url(lr),
    )


def notify_document_rejected(document, by_user) -> int:
    from loans.models import LoanNotification

    lr = document.loan_request
    count = notify_users(
        _branch_managers(lr),
        loan_request=lr,
        kind=LoanNotification.KIND_DOCUMENT_REJECTED,
        title=f'Document rejected: {lr.loan_request_id}',
        message=(
            f'"{document.document_type.name}" was rejected by {by_user.username}.'
            f'{(" Reason: " + document.auth_notes) if document.auth_notes else " Please upload a replacement."}'
        ),
        url=_loan_detail_url(lr),
    )
    notify_assigned_officer(
        lr,
        kind=LoanNotification.KIND_DOCUMENT_REJECTED,
        title=f'Document rejected on {lr.loan_request_id}',
        message=f'"{document.document_type.name}" was rejected. Coordinate with the branch for a new upload.',
    )
    return count


def notify_document_requested(loan_request, doc_type, requested_by=None) -> int:
    from loans.models import LoanNotification

    types = doc_type if isinstance(doc_type, (list, tuple)) else [doc_type]
    types = [dt for dt in types if dt is not None]
    if not types:
        return 0
    actor = requested_by
    who = getattr(actor, 'username', None) or 'Staff'
    if len(types) == 1:
        message = f'{who} requested "{types[0].name}". Please upload when available.'
    else:
        names = ', '.join(dt.name for dt in types)
        message = f'{who} requested {len(types)} documents: {names}. Please upload when available.'
    return notify_users(
        _branch_managers(loan_request),
        loan_request=loan_request,
        kind=LoanNotification.KIND_DOCUMENT_REQUESTED,
        title=f'Document requested: {loan_request.loan_request_id}',
        message=message,
        url=reverse('upload_loan_request_documents', args=[loan_request.pk]),
    )
