"""Post-disbursement monitoring, collections, workout, and write-off (hub case file)."""

from __future__ import annotations

from typing import List

from django.utils import timezone

from loans.credit_intelligence import scoped_loans
from loans.process_policy import book_ops_roles, workout_decide_roles


def user_can_access_book_ops(user) -> bool:
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) in book_ops_roles()


def user_can_decide_workout(user) -> bool:
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) in workout_decide_roles()


def disbursed_loans_qs(user):
    from loans.models import LoanRequest

    qs, _label = scoped_loans(user)
    return qs.filter(
        disbursement_status__in=(
            LoanRequest.DISBURSE_DISBURSED,
            LoanRequest.DISBURSE_PARTIAL,
        ),
    ).select_related('branch', 'assigned_loan_officer', 'appraisal', 'category')


def overdue_covenants(loan_request) -> List:
    from loans.models import AppraisalCondition

    appraisal = getattr(loan_request, 'appraisal', None)
    if appraisal is None:
        return []
    today = timezone.localdate()
    rows = []
    for c in appraisal.conditions.filter(condition_type=AppraisalCondition.TYPE_COVENANT):
        if c.fulfilled:
            continue
        if c.due_date and c.due_date < today:
            rows.append(c)
        elif not c.due_date:
            rows.append(c)
    return rows


def set_watchlist(loan_request, user, *, flagged: bool, reason: str = '') -> None:
    loan_request.watchlist = flagged
    loan_request.watchlist_reason = (reason or '').strip()
    loan_request.watchlist_at = timezone.now() if flagged else None
    loan_request.watchlist_by = user if flagged else None
    loan_request.save(update_fields=[
        'watchlist', 'watchlist_reason', 'watchlist_at', 'watchlist_by',
    ])
    if flagged:
        from loans.models import RehabCase
        from loans.rehab import ensure_rehab_stage
        ensure_rehab_stage(
            loan_request, RehabCase.STAGE_WATCHLIST, user,
            note=reason or 'Watchlist',
        )
