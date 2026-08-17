"""Branch Cooperative — branch performance / intake aging KPIs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from django.db.models import Avg, Count, Q, QuerySet, Sum
from django.utils import timezone

from loans.credit_intelligence import WEAK_BANDS
from loans.reporting import branch_dashboard_stats


def user_can_access_cooperative_performance(user) -> bool:
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    role = getattr(user, 'role', None)
    return role in (
        'cooperative_manager', 'operation_manager',
        'admin', 'superadmin', 'ceo', 'district_manager', 'auditor',
    )


def _days_open(dt) -> Optional[int]:
    if not dt:
        return None
    now = timezone.now()
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return max(0, (now.date() - dt.date()).days)


def annotate_intake_aging(loan_requests: List) -> List:
    """Attach .intake_age_days and .intake_overdue on each loan (pending Cooperative)."""
    for lr in loan_requests:
        pending = not bool(getattr(lr, 'operation_manager_approval', False))
        age = _days_open(getattr(lr, 'date_requested', None)) if pending else None
        lr.intake_age_days = age
        lr.intake_overdue = bool(age is not None and age >= 3)
    return loan_requests


def cooperative_performance_stats(qs: QuerySet) -> Dict[str, Any]:
    """
    Performance view for Branch Cooperative.
    qs should already be reporting-scoped; we focus on branch-originated files.
    """
    from loans.models import LoanRequest

    branch_qs = qs.filter(origin_level=LoanRequest.ORIGIN_BRANCH)
    base = branch_dashboard_stats(branch_qs)

    intake_pending_qs = branch_qs.filter(operation_manager_approval=False).exclude(
        status__iexact='Rejected',
    )
    intake_pending = intake_pending_qs.count()
    intake_approved = branch_qs.filter(operation_manager_approval=True).count()
    intake_rejected = branch_qs.filter(
        operation_manager_approval=False,
        status__iexact='Rejected',
    ).count()

    now = timezone.now()
    ages: List[int] = []
    aging_buckets = {'0_2': 0, '3_7': 0, '8_plus': 0}
    for dt in intake_pending_qs.values_list('date_requested', flat=True):
        if not dt:
            continue
        days = max(0, (now.date() - dt.date()).days)
        ages.append(days)
        if days <= 2:
            aging_buckets['0_2'] += 1
        elif days <= 7:
            aging_buckets['3_7'] += 1
        else:
            aging_buckets['8_plus'] += 1

    ages_sorted = sorted(ages)
    median_pending_days = None
    if ages_sorted:
        mid = len(ages_sorted) // 2
        if len(ages_sorted) % 2:
            median_pending_days = ages_sorted[mid]
        else:
            median_pending_days = (ages_sorted[mid - 1] + ages_sorted[mid]) / 2

    decided = branch_qs.filter(
        Q(operation_manager_approval=True) | Q(status__iexact='Rejected'),
    )
    decided_n = decided.count()
    intake_approval_rate = (
        round((intake_approved / decided_n) * 100, 1) if decided_n else 0
    )

    by_branch = list(
        branch_qs.values('branch_id', 'branch__name', 'branch__district__name')
        .annotate(
            total=Count('id'),
            amount=Sum('amount_requested'),
            intake_pending=Count(
                'id',
                filter=Q(operation_manager_approval=False) & ~Q(status__iexact='Rejected'),
            ),
            intake_approved=Count('id', filter=Q(operation_manager_approval=True)),
            committee_pending=Count('id', filter=Q(committee_status='pending_committee')),
            disbursed=Count('id', filter=Q(disbursement_status='disbursed')),
            weak_band=Count(
                'id',
                filter=Q(appraisal__credit_score_band__in=WEAK_BANDS),
            ),
            avg_score=Avg('appraisal__credit_score_total'),
        )
        .order_by('-intake_pending', '-total')[:40]
    )

    overdue_pending = sum(1 for a in ages if a >= 3)

    return {
        **base,
        'intake_pending': intake_pending,
        'intake_approved': intake_approved,
        'intake_rejected': intake_rejected,
        'intake_approval_rate': intake_approval_rate,
        'median_pending_days': median_pending_days,
        'overdue_pending': overdue_pending,
        'aging_buckets': aging_buckets,
        'by_branch_performance': by_branch,
        'branch_origin_total': branch_qs.count(),
    }
