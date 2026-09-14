"""Role-based staff hub navigation flags."""

from __future__ import annotations

from typing import Any, Dict, Set

from loans.book_ops import user_can_access_book_ops

# Fallback list used only when committee membership cannot be read from the DB.
COMMITTEE_VOTER_ROLES: Set[str] = {
    'branch_manager',
    'district_manager',
    'accountant',
    'cooperative_manager',
    'operation_manager',
    'finance_manager',
    'credit_head',
    'credit_loan_officer',
    'loan_officer',
    'ceo',
    'board_member',
    'vp',
    'vp_operations',
    'vp_it',
    'vp_customer_service',
}

# Never show committee / approval queues by policy, whatever the committee config says
# (risk reviews files via the Risk desk; engineering values collateral; auditors read only).
NO_COMMITTEE_ROLES: Set[str] = {
    'risk_compliance',
    'engineer',
    'engineering_head',
    'auditor',
}

POST_APPROVAL_ROLES: Set[str] = {
    'branch_manager',
    'loan_officer',
    'credit_loan_officer',
    'credit_head',
    'district_manager',
    'accountant',
    'cooperative_manager',
    'operation_manager',
    'finance_manager',
    'legal_officer',
    'admin',
    'superadmin',
}

REPORTS_ROLES: Set[str] = {
    'branch_manager',
    'loan_officer',
    'credit_loan_officer',
    'credit_head',
    'cooperative_manager',
    'operation_manager',
    'finance_manager',
    'risk_compliance',
    'accountant',
    'district_manager',
    'ceo',
    'vp',
    'vp_operations',
    'vp_it',
    'vp_customer_service',
    'board_member',
    'auditor',
    'engineering_head',
    'engineer',
    'admin',
    'superadmin',
}


def _is_configured_committee_member(user) -> bool:
    """Committee membership as configured in settings (role rules or named user)."""
    try:
        from loans.committee import user_is_approval_participant

        return user_is_approval_participant(user)
    except Exception:
        return getattr(user, 'role', None) in COMMITTEE_VOTER_ROLES


def user_can_access_committee_queues(user) -> bool:
    """Server-side gate for approval / committee loan lists."""
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    role = getattr(user, 'role', None)
    if role in ('admin', 'superadmin'):
        return True
    if role in NO_COMMITTEE_ROLES:
        return False
    if _is_configured_committee_member(user):
        return True
    # Covering someone who votes (delegated committee scope)
    try:
        from loans.delegation import SCOPE_COMMITTEE, principals_for

        return bool(principals_for(user, SCOPE_COMMITTEE))
    except Exception:
        return False


def nav_flags_for(user) -> Dict[str, Any]:
    empty = {
        'nav_show_approval_votes': False,
        'nav_show_post_approval': False,
        'nav_show_book_ops': False,
        'nav_show_reports': False,
        'nav_show_portfolio_dashboard': False,
        'nav_show_unlock_queue': False,
        'nav_role': '',
    }
    if user is None or not getattr(user, 'is_authenticated', False):
        return empty

    role = getattr(user, 'role', None) or ''
    is_admin = getattr(user, 'is_superuser', False) or role in ('admin', 'superadmin')

    show_votes = user_can_access_committee_queues(user)
    # Portfolio MIS dashboard: admins only in checkup — everyone else uses Home/CI/Risk/Coop product.
    show_portfolio_dash = is_admin

    show_unlock_queue = False
    try:
        from collateral.engineering_qa import user_can_see_unlock_queue
        show_unlock_queue = user_can_see_unlock_queue(user)
    except Exception:
        show_unlock_queue = role == 'engineering_head'

    return {
        'nav_show_approval_votes': show_votes,
        'nav_show_post_approval': is_admin or role in POST_APPROVAL_ROLES,
        'nav_show_book_ops': user_can_access_book_ops(user),
        'nav_show_reports': is_admin or role in REPORTS_ROLES,
        'nav_show_portfolio_dashboard': show_portfolio_dash,
        'nav_show_unlock_queue': show_unlock_queue,
        'nav_role': role,
    }
