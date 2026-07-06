"""Engineering QA workflow after collateral submit."""

from __future__ import annotations

from loans.collateral_config import allows_engineering_team


def engineering_review_required() -> bool:
    return allows_engineering_team()


def initial_engineering_status(submitter) -> str:
    """Status set on collateral submit when engineering mode is enabled."""
    from loans.models import LoanRequest

    if not engineering_review_required():
        return LoanRequest.ENG_COLLATERAL_NA
    role = getattr(submitter, 'role', None)
    if role == 'engineering_head':
        return LoanRequest.ENG_COLLATERAL_APPROVED
    return LoanRequest.ENG_COLLATERAL_PENDING


def can_review_engineering(user, loan_request) -> bool:
    if not engineering_review_required():
        return False
    from loans.models import LoanRequest

    if loan_request.collateral_engineering_status != LoanRequest.ENG_COLLATERAL_PENDING:
        return False
    if not loan_request.collateral_submitted_at:
        return False
    role = getattr(user, 'role', None)
    if role in ('engineering_head', 'admin', 'superadmin'):
        return True
    if role == 'engineer' and loan_request.assigned_engineer_id == user.id:
        return True
    return False


def engineering_pending_loans(user=None):
    from django.db.models import Q
    from loans.models import LoanRequest

    qs = LoanRequest.objects.filter(
        collateral_submitted_at__isnull=False,
        collateral_engineering_status=LoanRequest.ENG_COLLATERAL_PENDING,
    ).select_related('branch', 'collateral', 'assigned_engineer', 'collateral_submitted_by')
    if user:
        role = getattr(user, 'role', None)
        if role == 'engineer':
            qs = qs.filter(assigned_engineer=user)
        elif role == 'branch_manager' and getattr(user, 'branch_id', None):
            qs = qs.filter(branch_id=user.branch_id)
    return qs.order_by('-collateral_submitted_at')
