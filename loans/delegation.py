"""Staff authority delegation — act with another user's scopes while they are covered.

Scopes:
  committee_vote        — cast committee votes as the principal
  cooperative_intake     — Branch Cooperative intake approve/reject
  appraisal             — work appraisal / docs as assigned loan officer
  finance_disbursement  — finance disbursement approval
  assign_officer        — assign loan officer (BM / DM / Credit Head powers)
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional, Sequence, Tuple

from django.db.models import Q
from django.utils import timezone


SCOPE_COMMITTEE = 'committee_vote'
SCOPE_COOPERATIVE = 'cooperative_intake'
SCOPE_APPRAISAL = 'appraisal'
SCOPE_FINANCE = 'finance_disbursement'
SCOPE_ASSIGN_OFFICER = 'assign_officer'

SCOPE_CHOICES = [
    (SCOPE_COMMITTEE, 'Committee voting'),
    (SCOPE_COOPERATIVE, 'Cooperative intake approval'),
    (SCOPE_APPRAISAL, 'Loan officer appraisal / documents'),
    (SCOPE_FINANCE, 'Finance disbursement approval'),
    (SCOPE_ASSIGN_OFFICER, 'Assign loan officer'),
]

ALL_SCOPES = [c[0] for c in SCOPE_CHOICES]


def _now():
    return timezone.now()


def active_delegation_qs(at: Optional[datetime] = None):
    """Only admin-approved delegations inside their date window grant authority."""
    from loans.models import StaffDelegation

    when = at or _now()
    return StaffDelegation.objects.filter(
        status=StaffDelegation.STATUS_APPROVED,
        is_active=True,
        revoked_at__isnull=True,
        starts_at__lte=when,
        ends_at__gte=when,
    ).select_related('principal', 'delegate')


def pending_delegation_qs():
    from loans.models import StaffDelegation

    return StaffDelegation.objects.filter(
        status=StaffDelegation.STATUS_PENDING,
    ).select_related('principal', 'delegate', 'created_by').order_by('created_at')


def user_can_approve_delegations(user) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) in ('superadmin', 'admin')


def principals_for(delegate, scope: str, *, at: Optional[datetime] = None) -> List:
    """Principals who granted `scope` to this delegate (active window)."""
    if not delegate or not getattr(delegate, 'is_authenticated', False):
        return []
    out = []
    for d in active_delegation_qs(at).filter(delegate=delegate):
        scopes = d.scopes or []
        if scope in scopes or scope == '*':
            if d.principal_id and d.principal.is_active:
                out.append(d.principal)
    return out


def delegates_for(principal, scope: str, *, at: Optional[datetime] = None) -> List:
    if not principal:
        return []
    out = []
    for d in active_delegation_qs(at).filter(principal=principal):
        scopes = d.scopes or []
        if scope in scopes:
            if d.delegate_id and d.delegate.is_active:
                out.append(d.delegate)
    return out


def received_delegations(delegate, *, at: Optional[datetime] = None) -> List:
    if not delegate or not getattr(delegate, 'is_authenticated', False):
        return []
    return list(active_delegation_qs(at).filter(delegate=delegate))


def given_delegations(principal, *, at: Optional[datetime] = None) -> List:
    if not principal or not getattr(principal, 'is_authenticated', False):
        return []
    return list(active_delegation_qs(at).filter(principal=principal))


def can_act_as(actor, principal, scope: str) -> bool:
    if not actor or not principal:
        return False
    if actor.id == principal.id:
        return True
    return any(p.id == principal.id for p in principals_for(actor, scope))


def resolve_vote_principal(actor, loan_request, level):
    """
    Who the vote should be recorded for.
    Returns (principal_user, cast_by_or_None).
    Prefer own eligibility; else first principal with committee scope who can vote.
    """
    from loans.committee import _user_can_vote_as_member

    if _user_can_vote_as_member(actor, loan_request, level):
        return actor, None
    for principal in principals_for(actor, SCOPE_COMMITTEE):
        if _user_can_vote_as_member(principal, loan_request, level):
            return principal, actor
    return None, None


def user_has_cooperative_authority(user) -> bool:
    role = getattr(user, 'role', None)
    if role in ('cooperative_manager', 'operation_manager'):
        return True
    if getattr(user, 'is_superuser', False):
        return True
    for p in principals_for(user, SCOPE_COOPERATIVE):
        if getattr(p, 'role', None) in ('cooperative_manager', 'operation_manager'):
            return True
    return False


def user_has_finance_authority(user) -> bool:
    role = getattr(user, 'role', None)
    if role in ('finance_manager', 'admin', 'superadmin') or getattr(user, 'is_superuser', False):
        return True
    for p in principals_for(user, SCOPE_FINANCE):
        if getattr(p, 'role', None) in ('finance_manager', 'admin', 'superadmin') or getattr(p, 'is_superuser', False):
            return True
    return False


def user_has_assign_officer_authority(user) -> bool:
    role = getattr(user, 'role', None)
    if role in ('branch_manager', 'district_manager', 'credit_head', 'admin', 'superadmin'):
        return True
    if getattr(user, 'is_superuser', False):
        return True
    for p in principals_for(user, SCOPE_ASSIGN_OFFICER):
        if getattr(p, 'role', None) in (
            'branch_manager', 'district_manager', 'credit_head', 'admin', 'superadmin',
        ) or getattr(p, 'is_superuser', False):
            return True
    return False


def assign_officer_scope_user(actor):
    """
    Effective user for branch/district scope checks when assigning officers.
    Prefer actor's own assign role; else first principal with assign_officer scope.
    """
    role = getattr(actor, 'role', None)
    if role in ('branch_manager', 'district_manager', 'credit_head', 'admin', 'superadmin'):
        return actor
    if getattr(actor, 'is_superuser', False):
        return actor
    for p in principals_for(actor, SCOPE_ASSIGN_OFFICER):
        if getattr(p, 'role', None) in (
            'branch_manager', 'district_manager', 'credit_head', 'admin', 'superadmin',
        ):
            return p
    return actor


def loan_visibility_q_for_assign_principals(user) -> Optional[Q]:
    """ORM Q for loans a delegate may see/manage via assign_officer cover."""
    parts = []
    for p in principals_for(user, SCOPE_ASSIGN_OFFICER):
        role = getattr(p, 'role', None)
        if role == 'branch_manager' and p.branch_id:
            parts.append(Q(branch_id=p.branch_id))
        elif role == 'district_manager' and p.district_id:
            parts.append(Q(branch__district_id=p.district_id))
        elif role == 'credit_head':
            from loans.models import LoanRequest
            parts.append(Q(origin_level=LoanRequest.ORIGIN_HEAD_OFFICE))
        elif role in ('admin', 'superadmin') or getattr(p, 'is_superuser', False):
            return Q(pk__isnull=False)  # all loans
    if not parts:
        return None
    q = parts[0]
    for part in parts[1:]:
        q |= part
    return q


def user_can_access_loan_for_assign(user, loan_request) -> bool:
    """True if user may assign officer on this loan (own role or via delegation)."""
    if not user or not loan_request:
        return False
    if not user_has_assign_officer_authority(user):
        return False
    scope_user = assign_officer_scope_user(user)
    role = getattr(scope_user, 'role', None)
    if role in ('admin', 'superadmin') or getattr(scope_user, 'is_superuser', False):
        return True
    if role == 'branch_manager':
        return loan_request.branch_id == scope_user.branch_id
    if role == 'district_manager':
        loan_district = loan_request.district_id or getattr(loan_request.branch, 'district_id', None)
        return loan_district == scope_user.district_id
    if role == 'credit_head':
        from loans.models import LoanRequest
        return loan_request.origin_level == LoanRequest.ORIGIN_HEAD_OFFICE
    return False


def can_access_loan_as_officer(user, loan_request) -> Tuple[bool, Optional[object]]:
    """
    True if user is the assigned LO or holds appraisal delegation from them.
    Returns (ok, principal_or_self).
    """
    if not user or not loan_request:
        return False, None
    assigned_id = loan_request.assigned_loan_officer_id
    if not assigned_id:
        return False, None
    if assigned_id == user.id:
        return True, user
    for p in principals_for(user, SCOPE_APPRAISAL):
        if p.id == assigned_id:
            return True, p
    return False, None


def officer_loan_filter_q(user) -> Q:
    """ORM filter: loans this user may work as loan officer (own + delegated)."""
    ids = [user.id]
    for p in principals_for(user, SCOPE_APPRAISAL):
        ids.append(p.id)
    return Q(assigned_loan_officer_id__in=ids)


def expand_users_with_delegates(users: Iterable, scope: str) -> List:
    """Include active delegates when notifying principals."""
    by_id = {}
    for u in users:
        if u and getattr(u, 'is_active', True):
            by_id[u.id] = u
        for d in delegates_for(u, scope):
            by_id[d.id] = d
    return list(by_id.values())


def log_delegation_action(
    *,
    actor,
    principal,
    action: str,
    loan_request=None,
    delegation=None,
    detail: Optional[dict] = None,
) -> None:
    from loans.models import DelegationActionLog

    DelegationActionLog.objects.create(
        delegation=delegation,
        actor=actor,
        principal=principal,
        action=(action or '')[:64],
        loan_request=loan_request,
        detail=detail or {},
    )


def find_delegation(actor, principal, scope: str):
    for d in active_delegation_qs().filter(delegate=actor, principal=principal):
        if scope in (d.scopes or []):
            return d
    return None


def user_can_manage_delegations(user) -> bool:
    """Any authenticated hub staff user may open Delegations and request cover."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if not getattr(user, 'is_active', True):
        return False
    # Hub users are CustomUser with a staff role; exclude anonymous / inactive.
    return bool(getattr(user, 'role', None) or getattr(user, 'is_superuser', False))


def native_scopes_for(user) -> List[str]:
    """
    Scopes this user holds themselves (role / committee membership) — not via delegation.
    Only these may appear on a cover request.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return []
    role = getattr(user, 'role', None)
    held: List[str] = []

    if role in ('loan_officer', 'credit_loan_officer'):
        held.append(SCOPE_APPRAISAL)

    if role in ('cooperative_manager', 'operation_manager'):
        held.append(SCOPE_COOPERATIVE)

    if role in ('finance_manager', 'admin', 'superadmin') or getattr(user, 'is_superuser', False):
        held.append(SCOPE_FINANCE)

    if role in (
        'branch_manager', 'district_manager', 'credit_head', 'admin', 'superadmin',
    ) or getattr(user, 'is_superuser', False):
        held.append(SCOPE_ASSIGN_OFFICER)

    # Committee: only if configured as a participant (or admin)
    try:
        from loans.committee import user_is_approval_participant
        if user_is_approval_participant(user):
            held.append(SCOPE_COMMITTEE)
    except Exception:
        if role in ('admin', 'superadmin') or getattr(user, 'is_superuser', False):
            held.append(SCOPE_COMMITTEE)

    # Preserve SCOPE_CHOICES order
    order = {k: i for i, k in enumerate(ALL_SCOPES)}
    return sorted(set(held), key=lambda s: order.get(s, 99))


def scope_choices_for(user) -> List[Tuple[str, str]]:
    labels = dict(SCOPE_CHOICES)
    return [(s, labels[s]) for s in native_scopes_for(user) if s in labels]


def eligible_delegates_queryset(principal):
    """
    Colleagues the principal may propose as cover — limited to their org sphere.
    Branch staff → same branch; district staff → same district; HO/admin → org-wide.
    """
    from loans.models import CustomUser

    qs = CustomUser.objects.filter(is_active=True)
    if not principal:
        return qs.none()
    qs = qs.exclude(pk=principal.pk)
    role = getattr(principal, 'role', None)

    if getattr(principal, 'is_superuser', False) or role in ('superadmin', 'admin'):
        return qs.order_by('username')

    # Head-office / enterprise roles may pick any active staff
    if role in (
        'credit_head', 'credit_loan_officer', 'ceo', 'board_member',
        'vp', 'vp_operations', 'vp_it', 'vp_customer_service',
        'risk_compliance', 'auditor',
    ):
        return qs.order_by('username')

    # Engineering: never org-wide — engineers / eng heads only (same branch when set)
    if role == 'engineering_head':
        eng = qs.filter(role__in=('engineer', 'engineering_head'))
        if getattr(principal, 'branch_id', None):
            eng = eng.filter(
                Q(branch_id=principal.branch_id) | Q(branch_id__isnull=True)
            )
        return eng.order_by('username')
    if role == 'engineer':
        if getattr(principal, 'branch_id', None):
            return qs.filter(branch_id=principal.branch_id).order_by('username')
        return qs.filter(role__in=('engineer', 'engineering_head')).order_by('username')

    if role == 'district_manager' or (
        role == 'loan_officer' and principal.district_id and not principal.branch_id
    ):
        district_id = principal.district_id
        if not district_id:
            return qs.none()
        return qs.filter(
            Q(district_id=district_id) | Q(branch__district_id=district_id)
        ).order_by('username')

    # Branch sphere (BM, LO, coop, finance, accountant, engineer at that branch)
    branch_id = getattr(principal, 'branch_id', None)
    if branch_id:
        return qs.filter(branch_id=branch_id).order_by('username')

    # Department-only HO users without branch: colleagues in same department
    dept_id = getattr(principal, 'department_id', None)
    if dept_id:
        return qs.filter(department_id=dept_id).order_by('username')

    return qs.none()


def eligible_principals_queryset(actor):
    """Users the actor may receive authority from / create delegation for (self as principal)."""
    return eligible_delegates_queryset(actor)
