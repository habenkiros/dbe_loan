"""Phase 3 — Collateral Intelligence aggregates."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from loans.credit_intelligence import _money, scoped_loans


def build_collateral_intelligence(user, limit_flags: int = 15) -> Dict[str, Any]:
    """Portfolio collateral value, coverage, and below-policy flags."""
    from collateral.policy import get_collateral_policy

    qs, scope_label = scoped_loans(user)
    qs = qs.select_related('appraisal', 'branch')
    policy = get_collateral_policy()
    min_ratio = float(policy.min_coverage_ratio or Decimal('1'))

    with_value = qs.filter(appraisal__collateral_total_value__isnull=False)
    totals = with_value.aggregate(
        grand=Sum('appraisal__collateral_total_value'),
        immovable=Sum('appraisal__collateral_immovable_value'),
        moveable=Sum('appraisal__collateral_moveable_value'),
        avg_coverage=Avg('appraisal__collateral_coverage_ratio'),
        n=Count('id'),
    )

    below = list(
        qs.filter(
            appraisal__collateral_coverage_ratio__isnull=False,
            appraisal__collateral_coverage_ratio__lt=Decimal(str(min_ratio)),
        )
        .select_related('appraisal', 'branch')
        .order_by('appraisal__collateral_coverage_ratio')[:limit_flags]
    )

    high_risk = []
    for lr in below:
        appr = lr.appraisal
        ratio = float(appr.collateral_coverage_ratio) if appr.collateral_coverage_ratio is not None else None
        high_risk.append({
            'id': lr.id,
            'loan_request_id': lr.loan_request_id,
            'applicant_name': lr.applicant_name,
            'branch': lr.branch.name if lr.branch_id else '',
            'coverage_ratio': ratio,
            'coverage_pct': round(ratio * 100, 1) if ratio is not None else None,
            'collateral_total': _money(appr.collateral_total_value),
            'amount_requested': _money(lr.amount_requested),
            'flag': 'below_policy_min',
        })

    # Evidence / GPS confidence proxy: loans with declared address but no appraisal coverage yet
    missing_value = qs.filter(
        Q(appraisal__isnull=True) | Q(appraisal__collateral_total_value__isnull=True)
        | Q(appraisal__collateral_total_value=0),
    ).exclude(status__iexact='Rejected').count()

    by_type = [
        {
            'name': r['collateral__name'] or 'Unspecified',
            'count': r['c'],
            'value': _money(r['v']),
        }
        for r in qs.values('collateral__name').annotate(
            c=Count('id'),
            v=Sum('appraisal__collateral_total_value'),
        ).order_by('-v')[:12]
    ]

    return {
        'scope_label': scope_label,
        'kpis': {
            'total_collateral_value': _money(totals['grand']),
            'immovable_value': _money(totals['immovable']),
            'moveable_value': _money(totals['moveable']),
            'apps_with_value': totals['n'] or 0,
            'avg_coverage_ratio': round(float(totals['avg_coverage']), 2) if totals['avg_coverage'] is not None else None,
            'below_policy_count': len(high_risk),
            'missing_value_count': missing_value,
            'policy_min_ratio': min_ratio,
        },
        'high_risk': high_risk,
        'by_type': by_type,
        'generated_at': timezone.now().isoformat(),
        'disclaimer': (
            'Collateral values from engineering valuations / appraisal Sheet 5. '
            'Not an external AVM. Confidence = coverage vs policy + evidence completeness proxies.'
        ),
    }
