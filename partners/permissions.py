"""Who may use market-actor collection and how rows are scoped."""

from __future__ import annotations

from typing import Optional

READ_ROLES = (
    'loan_officer',
    'branch_manager',
    'credit_loan_officer',
    'credit_head',
    'district_manager',
    'admin',
    'superadmin',
    'cooperative_manager',
    'operation_manager',
    'ceo',
    'vp',
    'vp_operations',
    'vp_customer_service',
    'risk_compliance',
    'auditor',
    'engineer',
    'engineering_head',
)

WRITE_ROLES = (
    'loan_officer',
    'branch_manager',
    'credit_loan_officer',
    'cooperative_manager',
    'admin',
    'superadmin',
    'engineer',
    'engineering_head',
)


def user_can_use_market(user) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) in READ_ROLES


def user_can_write_market(user) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) in WRITE_ROLES


def resolve_write_branch(user) -> Optional[object]:
    """Branch used when field staff create actors/observations."""
    if not user:
        return None
    if getattr(user, 'branch_id', None):
        return user.branch
    return None


def scope_actors_qs(user, qs):
    if not user:
        return qs.none()
    if getattr(user, 'is_superuser', False):
        return qs
    role = getattr(user, 'role', None)
    if role in ('admin', 'superadmin', 'ceo', 'vp', 'vp_operations', 'vp_customer_service',
                'credit_head', 'risk_compliance', 'auditor', 'credit_loan_officer'):
        return qs
    if role == 'district_manager' and getattr(user, 'district_id', None):
        return qs.filter(branch__district_id=user.district_id)
    if getattr(user, 'branch_id', None):
        return qs.filter(branch_id=user.branch_id)
    return qs.none()


def scope_observations_qs(user, qs):
    if not user:
        return qs.none()
    if getattr(user, 'is_superuser', False):
        return qs
    role = getattr(user, 'role', None)
    if role in ('admin', 'superadmin', 'ceo', 'vp', 'vp_operations', 'vp_customer_service',
                'credit_head', 'risk_compliance', 'auditor', 'credit_loan_officer'):
        return qs
    if role == 'district_manager' and getattr(user, 'district_id', None):
        return qs.filter(branch__district_id=user.district_id)
    if getattr(user, 'branch_id', None):
        return qs.filter(branch_id=user.branch_id)
    return qs.none()


def user_may_access_actor(user, actor) -> bool:
    if not user or not actor:
        return False
    return scope_actors_qs(user, actor.__class__.objects.filter(pk=actor.pk)).exists()
