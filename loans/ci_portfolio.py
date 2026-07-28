"""Phase 3 — Filtered portfolio analytics."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from loans.credit_intelligence import WEAK_BANDS, _money, scoped_loans
from loans.reporting import apply_report_filters, filter_choices_for_user


def build_portfolio_analytics(user, params=None) -> Dict[str, Any]:
    """Role-scoped portfolio breakdowns with optional report filters."""
    from loans.models import LoanCategory, LoanRequest

    params = params or {}
    qs, scope_label = scoped_loans(user)
    qs = apply_report_filters(qs, params, user=user)

    category_id = (params.get('category_id') or '').strip()
    if category_id:
        qs = qs.filter(category_id=category_id)

    score_band = (params.get('score_band') or '').strip()
    if score_band:
        qs = qs.filter(appraisal__credit_score_band=score_band)

    total = qs.count()
    approved = qs.filter(
        Q(status__iexact='Approved') | Q(committee_status=LoanRequest.COMMITTEE_APPROVED)
    ).count()
    pending = qs.filter(status__iexact='Pending').count()
    rejected = qs.filter(status__iexact='Rejected').count()

    band_rows = list(
        qs.filter(appraisal__credit_score_total__isnull=False)
        .values('appraisal__credit_score_band')
        .annotate(c=Count('id'))
    )
    band_dist = {(r['appraisal__credit_score_band'] or 'unscored'): r['c'] for r in band_rows}
    score_bands = [
        {'band': 'strong', 'label': 'Strong', 'count': band_dist.get('strong', 0)},
        {'band': 'acceptable', 'label': 'Acceptable', 'count': band_dist.get('acceptable', 0)},
        {'band': 'weak', 'label': 'Weak', 'count': band_dist.get('weak', 0)},
        {'band': 'unacceptable', 'label': 'Unacceptable', 'count': band_dist.get('unacceptable', 0)},
    ]

    by_branch = [
        {
            'name': r['branch__name'] or 'Unassigned',
            'district': r['branch__district__name'] or '',
            'count': r['total'],
            'amount': _money(r['amount']),
            'approved': r['approved'],
            'rejected': r['rejected'],
            'weak': r['weak'],
        }
        for r in qs.values('branch__name', 'branch__district__name').annotate(
            total=Count('id'),
            amount=Sum('amount_requested'),
            approved=Count(
                'id',
                filter=Q(status__iexact='Approved') | Q(committee_status=LoanRequest.COMMITTEE_APPROVED),
            ),
            rejected=Count('id', filter=Q(status__iexact='Rejected')),
            weak=Count('id', filter=Q(appraisal__credit_score_band__in=WEAK_BANDS)),
        ).order_by('-total')[:25]
    ]

    by_category = [
        {
            'name': r['category__name'] or 'Uncategorized',
            'count': r['total'],
            'amount': _money(r['amount']),
            'avg_score': round(float(r['avg_score']), 1) if r['avg_score'] is not None else None,
        }
        for r in qs.values('category__name').annotate(
            total=Count('id'),
            amount=Sum('amount_requested'),
            avg_score=Avg('appraisal__credit_score_total'),
        ).order_by('-total')[:20]
    ]

    by_collateral = [
        {
            'name': r['collateral__name'] or 'Unspecified',
            'count': r['total'],
            'amount': _money(r['amount']),
        }
        for r in qs.values('collateral__name').annotate(
            total=Count('id'),
            amount=Sum('amount_requested'),
        ).order_by('-total')[:15]
    ]

    dscr_stats = qs.filter(appraisal__dscr_annual__isnull=False).aggregate(
        avg_dscr=Avg('appraisal__dscr_annual'),
        low_dscr=Count('id', filter=Q(appraisal__dscr_annual__lt=Decimal('1.0'))),
        with_dscr=Count('id'),
    )
    with_dscr = dscr_stats['with_dscr'] or 0
    low_dscr = dscr_stats['low_dscr'] or 0

    avg_coverage = qs.filter(
        appraisal__collateral_coverage_ratio__isnull=False,
    ).aggregate(a=Avg('appraisal__collateral_coverage_ratio'))['a']

    choices = filter_choices_for_user(user)
    categories = LoanCategory.objects.order_by('name')

    return {
        'scope_label': scope_label,
        'filters': {
            'status': params.get('status', ''),
            'committee_status': params.get('committee_status', ''),
            'disbursement_status': params.get('disbursement_status', ''),
            'branch_id': params.get('branch_id', ''),
            'district_id': params.get('district_id', ''),
            'date_from': params.get('date_from', ''),
            'date_to': params.get('date_to', ''),
            'category_id': category_id,
            'score_band': score_band,
        },
        'summary': {
            'total': total,
            'approved': approved,
            'pending': pending,
            'rejected': rejected,
            'approval_rate': round((approved / total) * 100.0, 1) if total else 0.0,
            'reject_rate': round((rejected / total) * 100.0, 1) if total else 0.0,
            'requested_book': _money(qs.aggregate(t=Sum('amount_requested'))['t']),
            'avg_dscr_annual': round(float(dscr_stats['avg_dscr']), 2) if dscr_stats['avg_dscr'] is not None else None,
            'low_dscr_count': low_dscr,
            'low_dscr_share': round((low_dscr / with_dscr) * 100.0, 1) if with_dscr else 0.0,
            'avg_coverage_ratio': round(float(avg_coverage), 2) if avg_coverage is not None else None,
        },
        'score_bands': score_bands,
        'by_branch': by_branch,
        'by_category': by_category,
        'by_collateral': by_collateral,
        'status_mix': [
            {'label': 'Approved', 'count': approved},
            {'label': 'Pending', 'count': pending},
            {'label': 'Rejected', 'count': rejected},
        ],
        'filter_choices': choices,
        'categories': list(categories.values('id', 'name')),
        'generated_at': timezone.now().isoformat(),
        'disclaimer': (
            'Origination portfolio analytics — DSCR/coverage from appraisal sheets, '
            'not repayment ledger performance.'
        ),
    }
