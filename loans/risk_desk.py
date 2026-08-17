"""Risk & Compliance desk — queues for loan-related risk review."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Tuple

from django.db.models import Q, QuerySet

from loans.ci_workspaces import build_risk_alerts
from loans.credit_intelligence import WEAK_BANDS, scoped_loans

QUEUE_CHOICES = (
    ('alerts', 'Risk alerts'),
    ('weak_score', 'Weak / unacceptable score'),
    ('es_flagged', 'E&S high or reject'),
    ('thin_coverage', 'Thin collateral coverage'),
    ('low_dscr', 'Low DSCR'),
    ('unreviewed', 'Flagged & not risk-reviewed'),
)


def user_can_access_risk_desk(user) -> bool:
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) in (
        'risk_compliance', 'auditor', 'admin', 'superadmin',
        'ceo', 'credit_head',
    )


def risk_queue_queryset(user, queue: str) -> Tuple[QuerySet, str]:
    """Return (queryset, human label) for a risk desk queue filter."""
    from loans.models import LoanAppraisal, LoanRequest

    qs, scope_label = scoped_loans(user)
    qs = qs.select_related('appraisal', 'branch', 'branch__district', 'assigned_loan_officer')
    label = dict(QUEUE_CHOICES).get(queue, 'Risk queue')

    if queue == 'weak_score':
        qs = qs.filter(appraisal__credit_score_band__in=WEAK_BANDS)
    elif queue == 'es_flagged':
        qs = qs.filter(
            Q(appraisal__es_risk_category=LoanAppraisal.ES_RISK_HIGH)
            | Q(appraisal__es_eligibility_decision=LoanAppraisal.ES_ELIGIBILITY_REJECT)
            | Q(appraisal__es_eligibility_decision=LoanAppraisal.ES_ELIGIBILITY_PASS_ACTION)
        )
    elif queue == 'thin_coverage':
        qs = qs.filter(
            appraisal__collateral_coverage_ratio__isnull=False,
            appraisal__collateral_coverage_ratio__lt=Decimal('1.0'),
        )
    elif queue == 'low_dscr':
        qs = qs.filter(
            appraisal__dscr_annual__isnull=False,
            appraisal__dscr_annual__lt=Decimal('1.0'),
        )
    elif queue == 'unreviewed':
        flagged = (
            Q(appraisal__credit_score_band__in=WEAK_BANDS)
            | Q(appraisal__es_risk_category=LoanAppraisal.ES_RISK_HIGH)
            | Q(appraisal__es_eligibility_decision=LoanAppraisal.ES_ELIGIBILITY_REJECT)
            | Q(appraisal__collateral_coverage_ratio__lt=Decimal('1.0'))
            | Q(appraisal__dscr_annual__lt=Decimal('1.0'))
        )
        qs = qs.filter(flagged, risk_reviewed_at__isnull=True).exclude(
            status__iexact='Rejected',
        )
    else:
        # alerts feed uses build_risk_alerts; keep a broad "attention" list
        qs = qs.filter(
            Q(appraisal__credit_score_band__in=WEAK_BANDS)
            | Q(appraisal__es_risk_category=LoanAppraisal.ES_RISK_HIGH)
            | Q(appraisal__es_eligibility_decision__in=(
                LoanAppraisal.ES_ELIGIBILITY_REJECT,
                LoanAppraisal.ES_ELIGIBILITY_PASS_ACTION,
            ))
            | Q(appraisal__collateral_coverage_ratio__lt=Decimal('1.0'))
            | Q(appraisal__dscr_annual__lt=Decimal('1.0'))
        ).exclude(status__iexact='Rejected')
        label = 'Needs attention'

    return qs.order_by('-date_requested', '-id'), scope_label if queue == 'alerts' else f'{label} · {scope_label}'


def risk_desk_counts(user) -> Dict[str, int]:
    counts = {}
    for key, _ in QUEUE_CHOICES:
        if key == 'alerts':
            counts[key] = len(build_risk_alerts(user, limit=50))
            continue
        qs, _ = risk_queue_queryset(user, key)
        counts[key] = qs.count()
    return counts


def loan_risk_summary(loan_request) -> Dict[str, Any]:
    """Compact risk strip payload for loan detail."""
    from loans.models import LoanAppraisal

    appraisal = None
    try:
        appraisal = loan_request.appraisal
    except LoanAppraisal.DoesNotExist:
        appraisal = None

    flags: List[str] = []
    band = getattr(appraisal, 'credit_score_band', None) if appraisal else None
    score = getattr(appraisal, 'credit_score_total', None) if appraisal else None
    es_cat = getattr(appraisal, 'es_risk_category', None) if appraisal else None
    es_elig = getattr(appraisal, 'es_eligibility_decision', None) if appraisal else None
    coverage = getattr(appraisal, 'collateral_coverage_ratio', None) if appraisal else None
    dscr = getattr(appraisal, 'dscr_annual', None) if appraisal else None

    if band in WEAK_BANDS:
        flags.append(f'Score band: {band}')
    if es_cat == 'high':
        flags.append('E&S risk: high')
    if es_elig in ('reject', 'pass_action'):
        flags.append(f'E&S eligibility: {es_elig}')
    if coverage is not None and coverage < Decimal('1.0'):
        flags.append(f'Coverage {float(coverage):.2f}×')
    if dscr is not None and dscr < Decimal('1.0'):
        flags.append(f'DSCR {float(dscr):.2f}')

    return {
        'band': band,
        'score': score,
        'es_risk_category': es_cat,
        'es_eligibility': es_elig,
        'coverage_ratio': coverage,
        'dscr_annual': dscr,
        'flags': flags,
        'has_flags': bool(flags),
        'reviewed_at': loan_request.risk_reviewed_at,
        'reviewed_by': loan_request.risk_reviewed_by,
        'review_note': loan_request.risk_review_note or '',
    }
