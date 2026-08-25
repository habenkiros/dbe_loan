"""Legal Administration desk — post-authorization legal clearance."""

from __future__ import annotations

from typing import Dict, Tuple

from django.db.models import Exists, OuterRef, Q, QuerySet

from loans.collateral_legal import legal_papers_required

QUEUE_CHOICES = (
    ('awaiting', 'Awaiting legal papers'),
    ('in_review', 'In review (uploaded)'),
    ('ready_to_clear', 'Ready to clear'),
    ('cleared', 'Cleared for disbursement'),
    ('returned', 'Returned to branch'),
)


def user_can_access_legal_desk(user) -> bool:
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) in (
        'legal_officer', 'admin', 'superadmin', 'ceo', 'credit_head', 'auditor',
    )


def user_can_manage_legal(user) -> bool:
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) in ('legal_officer', 'admin', 'superadmin')


def _post_approval_qs():
    from loans.models import LoanRequest

    return LoanRequest.objects.filter(
        committee_status=LoanRequest.COMMITTEE_APPROVED,
    ).exclude(
        disbursement_status=LoanRequest.DISBURSE_DISBURSED,
    ).select_related('branch', 'assigned_loan_officer', 'legal_cleared_by')


def legal_queue_queryset(user, queue: str) -> Tuple[QuerySet, str]:
    from loans.models import LoanCollateralLegalDocument, LoanRequest

    qs = _post_approval_qs()
    label = dict(QUEUE_CHOICES).get(queue, 'Legal queue')
    uploaded = LoanCollateralLegalDocument.objects.filter(
        loan_request_id=OuterRef('pk'),
        status=LoanCollateralLegalDocument.STATUS_UPLOADED,
    )
    any_doc = LoanCollateralLegalDocument.objects.filter(loan_request_id=OuterRef('pk'))

    if queue == 'cleared':
        qs = qs.filter(legal_cleared_at__isnull=False)
    elif queue == 'returned':
        qs = qs.filter(
            legal_cleared_at__isnull=True,
            legal_clearance_note__isnull=False,
        ).exclude(legal_clearance_note='')
        # Heuristic: note present, not cleared, and no pending uploads — returned
        qs = qs.annotate(_has_upload=Exists(uploaded)).filter(_has_upload=False)
    elif queue == 'in_review':
        qs = qs.filter(legal_cleared_at__isnull=True).annotate(
            _pending=Exists(uploaded),
        ).filter(_pending=True)
    elif queue == 'ready_to_clear':
        # Papers verified (no paper blockers) but not yet stamped by Legal
        from loans.collateral_legal import collateral_legal_blockers

        candidates = list(qs.filter(legal_cleared_at__isnull=True)[:200])
        ready_ids = [
            lr.pk for lr in candidates
            if legal_papers_required(lr) and not collateral_legal_blockers(lr)
        ]
        qs = LoanRequest.objects.filter(pk__in=ready_ids).select_related(
            'branch', 'assigned_loan_officer', 'legal_cleared_by',
        )
    else:
        # awaiting: post-approval, needs papers, not cleared, no pending upload yet
        qs = qs.filter(legal_cleared_at__isnull=True).annotate(
            _pending=Exists(uploaded),
            _any=Exists(any_doc),
        ).filter(_pending=False)
        # Prefer loans that require legal papers
        candidates = list(qs[:300])
        need_ids = [lr.pk for lr in candidates if legal_papers_required(lr)]
        qs = LoanRequest.objects.filter(pk__in=need_ids).select_related(
            'branch', 'assigned_loan_officer', 'legal_cleared_by',
        )

    return qs.order_by('-committee_decided_at', '-id'), label


def legal_desk_counts(user) -> Dict[str, int]:
    counts = {}
    for key, _ in QUEUE_CHOICES:
        qs, _ = legal_queue_queryset(user, key)
        counts[key] = qs.count()
    return counts


def clear_for_disbursement(loan_request, user, *, note: str = '') -> None:
    from django.utils import timezone
    from loans.collateral_legal import collateral_legal_blockers

    blockers = collateral_legal_blockers(loan_request)
    if blockers:
        raise ValueError('Cannot clear — legal papers still incomplete: ' + '; '.join(blockers[:3]))
    loan_request.legal_cleared_at = timezone.now()
    loan_request.legal_cleared_by = user
    if note:
        loan_request.legal_clearance_note = note.strip()[:4000]
    loan_request.save(update_fields=[
        'legal_cleared_at', 'legal_cleared_by', 'legal_clearance_note',
    ])


def return_to_branch(loan_request, user, *, note: str = '') -> None:
    note = (note or '').strip()
    if len(note) < 10:
        raise ValueError('Explain why the file is returned (at least 10 characters).')
    loan_request.legal_cleared_at = None
    loan_request.legal_cleared_by = None
    loan_request.legal_clearance_note = note[:4000]
    loan_request.save(update_fields=[
        'legal_cleared_at', 'legal_cleared_by', 'legal_clearance_note',
    ])
