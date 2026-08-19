"""Singleton process policy: risk-before-committee, closing gates, book-ops access."""

from __future__ import annotations

from typing import Dict, List, Set

from loans.models import LoanAnalysisPolicyConfig, LoanProcessPolicyConfig


DEFAULT_BOOK_OPS_ROLES: List[str] = [
    'branch_manager', 'loan_officer', 'credit_loan_officer', 'credit_head',
    'district_manager', 'accountant', 'cooperative_manager', 'operation_manager',
    'finance_manager', 'risk_compliance', 'ceo', 'admin', 'superadmin',
]

DEFAULT_WORKOUT_DECIDE_ROLES: List[str] = [
    'credit_head', 'finance_manager', 'ceo', 'admin', 'superadmin',
]

# LoanRequest field → LoanProcessPolicyConfig field
LOAN_TO_POLICY_FLAG = {
    'require_collateral_restriction': 'require_collateral_restriction',
    'require_agreement_signatures': 'require_agreement_signatures',
    'require_title_search': 'require_title_search',
    'require_mortgage_registration': 'require_mortgage_registration',
    'require_notary_stamp': 'require_notary_stamp',
    'own_contribution_required': 'require_own_contribution',
}


def default_book_ops_roles() -> List[str]:
    return list(DEFAULT_BOOK_OPS_ROLES)


def default_workout_decide_roles() -> List[str]:
    return list(DEFAULT_WORKOUT_DECIDE_ROLES)


def get_or_create_analysis_policy() -> LoanAnalysisPolicyConfig:
    obj = LoanAnalysisPolicyConfig.objects.first()
    if obj:
        return obj
    return LoanAnalysisPolicyConfig.objects.create()


def get_or_create_process_policy() -> LoanProcessPolicyConfig:
    obj = LoanProcessPolicyConfig.objects.first()
    if obj:
        return obj
    return LoanProcessPolicyConfig.objects.create(
        book_ops_roles=default_book_ops_roles(),
        workout_decide_roles=default_workout_decide_roles(),
    )


def get_process_policy() -> LoanProcessPolicyConfig:
    obj = LoanProcessPolicyConfig.objects.first()
    if obj:
        return obj
    return LoanProcessPolicyConfig(
        book_ops_roles=default_book_ops_roles(),
        workout_decide_roles=default_workout_decide_roles(),
    )


def _roles_or_default(raw, fallback: List[str]) -> Set[str]:
    if isinstance(raw, str):
        values = [p.strip() for p in raw.split(',') if p.strip()]
    elif isinstance(raw, (list, tuple, set)):
        values = [str(p).strip() for p in raw if str(p).strip()]
    else:
        values = []
    return set(values) if values else set(fallback)


def book_ops_roles() -> Set[str]:
    return _roles_or_default(get_process_policy().book_ops_roles, DEFAULT_BOOK_OPS_ROLES)


def workout_decide_roles() -> Set[str]:
    return _roles_or_default(
        get_process_policy().workout_decide_roles, DEFAULT_WORKOUT_DECIDE_ROLES,
    )


def policy_forces(loan_attr: str) -> bool:
    """True when Settings → Process policy requires this closing gate for every loan."""
    policy_attr = LOAN_TO_POLICY_FLAG.get(loan_attr, loan_attr)
    return bool(getattr(get_process_policy(), policy_attr, False))


def requirement_on(loan_request, loan_attr: str) -> bool:
    """Bank policy OR per-loan tick. Officers cannot waive a policy-on gate."""
    return policy_forces(loan_attr) or bool(getattr(loan_request, loan_attr, False))


def tranches_enabled() -> bool:
    return bool(getattr(get_process_policy(), 'enable_disbursement_tranches', True))


def closing_locks() -> Dict[str, bool]:
    return {attr: policy_forces(attr) for attr in LOAN_TO_POLICY_FLAG}
