"""Origination Credit Intelligence — portfolio KPIs and AI insight aggregates.

Phase 1 focuses on metrics derivable from LoanRequest / LoanAppraisal /
committee / disbursement fields. True NPL/outstanding from CBS is out of scope
(adapter stub later).
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from django.db.models import Avg, Count, Q, QuerySet, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from loans.reporting import reporting_base_queryset


WEAK_BANDS = ('weak', 'unacceptable')


def scoped_loans(user) -> Tuple[QuerySet, str]:
    """Role-scoped loan queryset + human scope label (same rules as Reports)."""
    from loans.reporting import report_scope_label

    return reporting_base_queryset(user), report_scope_label(user)


def _money(v) -> float:
    if v is None:
        return 0.0
    try:
        return float(Decimal(str(v)))
    except Exception:
        return 0.0


def _with_book_amount(qs: QuerySet) -> QuerySet:
    """Annotate preferred book amount: committee → appraisal approved → requested."""
    return qs.annotate(
        _book_amt=Coalesce(
            'committee_final_amount',
            'appraisal__amount_approved',
            'amount_requested',
            Value(Decimal('0')),
        )
    )


def _sum_book(qs: QuerySet) -> float:
    return _money(_with_book_amount(qs).aggregate(t=Sum('_book_amt'))['t'])


def _period_bounds(ref: Optional[date] = None) -> Tuple[date, date, date, date]:
    """Return (cur_start, cur_end, prev_start, prev_end) for MoM windows."""
    today = ref or timezone.localdate()
    cur_start = today.replace(day=1)
    # previous month
    if cur_start.month == 1:
        prev_start = date(cur_start.year - 1, 12, 1)
    else:
        prev_start = date(cur_start.year, cur_start.month - 1, 1)
    prev_last_day = monthrange(prev_start.year, prev_start.month)[1]
    prev_end = date(prev_start.year, prev_start.month, prev_last_day)
    return cur_start, today, prev_start, prev_end


def _pct_delta(current: float, previous: float) -> Optional[float]:
    if previous == 0:
        return None if current == 0 else 100.0
    return round(((current - previous) / previous) * 100.0, 1)


def _risk_level(flag_share: float, high_exposure_share: float) -> str:
    if flag_share >= 25 or high_exposure_share >= 30:
        return 'high'
    if flag_share >= 12 or high_exposure_share >= 15:
        return 'medium'
    return 'low'


def build_overview(user) -> Dict[str, Any]:
    """Executive / officer Credit Intelligence overview payload."""
    from loans.models import LoanRequest

    qs, scope_label = scoped_loans(user)
    qs = qs.select_related('appraisal', 'branch', 'category', 'collateral')

    total = qs.count()
    approved_qs = qs.filter(
        Q(status__iexact='Approved') | Q(committee_status=LoanRequest.COMMITTEE_APPROVED)
    )
    approved_count = approved_qs.count()
    pending_count = qs.filter(status__iexact='Pending').count()
    rejected_count = qs.filter(status__iexact='Rejected').count()
    queue_approved = qs.filter(queue_approved=True).count()
    in_appraisal = qs.filter(
        appraisal_completed_at__isnull=True,
        assigned_loan_officer__isnull=False,
    ).exclude(status__iexact='Rejected').count()
    pending_committee = qs.filter(committee_status=LoanRequest.COMMITTEE_PENDING).count()
    disbursed = qs.filter(disbursement_status=LoanRequest.DISBURSE_DISBURSED).count()
    awaiting_disburse = qs.filter(
        disbursement_status__in=[
            LoanRequest.DISBURSE_AWAITING_CONDITIONS,
            LoanRequest.DISBURSE_SCHEDULE_CONFIRMED,
            LoanRequest.DISBURSE_READY,
        ]
    ).count()

    approved_book = _sum_book(approved_qs)
    requested_book = _money(qs.aggregate(t=Sum('amount_requested'))['t'])

    scored = qs.filter(appraisal__credit_score_total__isnull=False)
    scored_count = scored.count()
    avg_score = scored.aggregate(a=Avg('appraisal__credit_score_total'))['a']
    avg_score_f = round(float(avg_score), 1) if avg_score is not None else None

    band_rows = list(
        scored.values('appraisal__credit_score_band').annotate(c=Count('id')).order_by()
    )
    band_dist = {
        (r['appraisal__credit_score_band'] or 'unscored'): r['c']
        for r in band_rows
    }
    weak_count = sum(band_dist.get(b, 0) for b in WEAK_BANDS)
    risk_flagged_share = round((weak_count / scored_count) * 100.0, 1) if scored_count else 0.0

    high_risk_qs = scored.filter(appraisal__credit_score_band__in=WEAK_BANDS)
    high_risk_exposure = _sum_book(high_risk_qs)
    high_exposure_share = (
        round((high_risk_exposure / approved_book) * 100.0, 1) if approved_book else 0.0
    )

    # Bureau outstanding where known (coverage of apps with data)
    bureau_qs = qs.filter(appraisal__bureau_total_outstanding__isnull=False)
    bureau_outstanding = _money(
        bureau_qs.aggregate(t=Sum('appraisal__bureau_total_outstanding'))['t']
    )
    bureau_coverage = round((bureau_qs.count() / total) * 100.0, 1) if total else 0.0

    # MoM growth on approved book by decision/request date
    cur_start, cur_end, prev_start, prev_end = _period_bounds()
    cur_approved = approved_qs.filter(
        Q(committee_decided_at__date__gte=cur_start, committee_decided_at__date__lte=cur_end)
        | Q(
            committee_decided_at__isnull=True,
            date_requested__date__gte=cur_start,
            date_requested__date__lte=cur_end,
        )
    )
    prev_approved = approved_qs.filter(
        Q(committee_decided_at__date__gte=prev_start, committee_decided_at__date__lte=prev_end)
        | Q(
            committee_decided_at__isnull=True,
            date_requested__date__gte=prev_start,
            date_requested__date__lte=prev_end,
        )
    )
    cur_amt = _sum_book(cur_approved)
    prev_amt = _sum_book(prev_approved)
    growth_pct = _pct_delta(cur_amt, prev_amt)

    approval_rate = round((approved_count / total) * 100.0, 1) if total else 0.0
    risk_level = _risk_level(risk_flagged_share, high_exposure_share)

    # Active applicants proxy
    active_applicants = (
        qs.exclude(status__iexact='Rejected')
        .values('applicant_name')
        .distinct()
        .count()
    )

    kpis = [
        _kpi(
            'approved_book',
            'Approved book (ETB)',
            approved_book,
            'currency',
            growth_pct,
            _explain_book(approved_book, growth_pct, approved_count),
            'low' if growth_pct is None or growth_pct >= 0 else 'medium',
            'Origination — committee/approved amounts (not CBS outstanding)',
        ),
        _kpi(
            'pipeline',
            'Pipeline applications',
            float(total),
            'count',
            None,
            f'{pending_count} pending · {in_appraisal} in appraisal · {pending_committee} in committee',
            'low',
            'All loans in your scope',
        ),
        _kpi(
            'approval_rate',
            'Approval rate',
            approval_rate,
            'percent',
            None,
            f'{approved_count} approved of {total} in scope',
            'low' if approval_rate >= 40 else 'medium',
            'Status=Approved or committee-approved',
        ),
        _kpi(
            'avg_score',
            'Avg credit score',
            avg_score_f if avg_score_f is not None else 0.0,
            'score',
            None,
            (
                f'{scored_count} scored apps · UI scale {int((avg_score_f or 0) * 10)}/1000'
                if scored_count
                else 'No scorecards yet — complete Sheet 6'
            ),
            'low' if (avg_score_f or 0) >= 70 else ('medium' if (avg_score_f or 0) >= 55 else 'high'),
            'Explainable 0–100 scorecard (shown ×10 as 0–1000)',
        ),
        _kpi(
            'risk_flagged',
            'Risk-flagged share',
            risk_flagged_share,
            'percent',
            None,
            f'{weak_count} Weak/Unacceptable of {scored_count} scored',
            'high' if risk_flagged_share >= 25 else ('medium' if risk_flagged_share >= 12 else 'low'),
            'Proxy — not true NPL (no repayment ledger)',
        ),
        _kpi(
            'high_risk_exposure',
            'High-risk exposure (ETB)',
            high_risk_exposure,
            'currency',
            None,
            f'{high_exposure_share}% of approved book in Weak/Unacceptable bands',
            'high' if high_exposure_share >= 30 else ('medium' if high_exposure_share >= 15 else 'low'),
            'Approved amounts on weak score bands',
        ),
        _kpi(
            'bureau_outstanding',
            'Bureau outstanding (ETB)',
            bureau_outstanding,
            'currency',
            None,
            f'Known on {bureau_coverage}% of apps (Sheet 3 bureau fields)',
            'medium' if bureau_coverage < 40 else 'low',
            'Where bureau_total_outstanding is captured',
        ),
        _kpi(
            'disbursement',
            'Post-approval track',
            float(disbursed),
            'count',
            None,
            f'{disbursed} disbursed · {awaiting_disburse} in post-approval',
            'low',
            'Disbursement status on committee-approved loans',
        ),
    ]

    from loans.portfolio_ledger import get_ledger_adapter
    ledger = get_ledger_adapter()
    ledger_meta = {
        'connected': ledger.is_connected(),
        'label': ledger.connection_label(),
    }
    if ledger.is_connected():
        cbs_out = ledger.total_outstanding(user)
        cbs_npl = ledger.npl_ratio(user)
        cbs_borrowers = ledger.active_borrowers(user)
        kpis.insert(1, _kpi(
            'cbs_outstanding',
            'CBS outstanding (ETB)',
            float(cbs_out) if cbs_out is not None else 0.0,
            'currency',
            None,
            (
                f'{cbs_borrowers or 0} active borrowers in scope · '
                + (f'NPL {(cbs_npl * 100):.1f}%' if cbs_npl is not None else 'No NPL data')
            ),
            'medium' if (cbs_npl or 0) >= 0.05 else 'low',
            ledger.connection_label(),
        ))
        if cbs_npl is not None:
            kpis.insert(2, _kpi(
                'cbs_npl',
                'CBS NPL ratio',
                round(cbs_npl * 100.0, 2),
                'percent',
                None,
                'From core-banking outstanding / NPL amounts by customer number',
                'high' if cbs_npl >= 0.1 else ('medium' if cbs_npl >= 0.05 else 'low'),
                ledger.connection_label(),
            ))
    else:
        ledger_meta['note'] = 'Set DECSI_BASE_URL or DECSI_CBS_USE_MOCK_LEDGER for CBS KPIs'

    # Branch breakdown (top 10)
    branch_rows = list(
        qs.values('branch__name')
        .annotate(total=Count('id'), amount=Sum('amount_requested'))
        .order_by('-total')[:10]
    )
    branches = [
        {
            'name': r['branch__name'] or 'Unassigned',
            'count': r['total'],
            'amount': _money(r['amount']),
        }
        for r in branch_rows
    ]

    # Score band chart
    score_bands = [
        {'band': 'strong', 'label': 'Strong', 'count': band_dist.get('strong', 0)},
        {'band': 'acceptable', 'label': 'Acceptable', 'count': band_dist.get('acceptable', 0)},
        {'band': 'weak', 'label': 'Weak', 'count': band_dist.get('weak', 0)},
        {'band': 'unacceptable', 'label': 'Unacceptable', 'count': band_dist.get('unacceptable', 0)},
    ]

    insights = build_insights(qs, {
        'risk_flagged_share': risk_flagged_share,
        'high_risk_exposure': high_risk_exposure,
        'avg_score': avg_score_f,
        'pending_committee': pending_committee,
        'awaiting_disburse': awaiting_disburse,
        'in_appraisal': in_appraisal,
        'growth_pct': growth_pct,
    })

    watchlist = _watchlist(qs)

    funnel = [
        {'label': 'In appraisal', 'count': in_appraisal},
        {'label': 'Committee', 'count': pending_committee},
        {'label': 'Awaiting disbursement', 'count': awaiting_disburse},
        {'label': 'Disbursed', 'count': disbursed},
    ]
    trend = {
        'labels': [prev_start.strftime('%b %Y'), cur_start.strftime('%b %Y')],
        'approved_count': [prev_approved.count(), cur_approved.count()],
        'approved_book': [round(prev_amt, 2), round(cur_amt, 2)],
    }
    book_compare = {
        'labels': ['Requested', 'Approved'],
        'values': [round(requested_book, 2), round(approved_book, 2)],
    }

    return {
        'scope_label': scope_label,
        'generated_at': timezone.now().isoformat(),
        'portfolio_risk_level': risk_level,
        'kpis': kpis,
        'pipeline': {
            'total': total,
            'pending': pending_count,
            'approved': approved_count,
            'rejected': rejected_count,
            'queue_approved': queue_approved,
            'in_appraisal': in_appraisal,
            'pending_committee': pending_committee,
            'disbursed': disbursed,
            'awaiting_disburse': awaiting_disburse,
            'active_applicants': active_applicants,
            'requested_book': requested_book,
            'approved_book': approved_book,
        },
        'funnel': funnel,
        'trend': trend,
        'book_compare': book_compare,
        'score_bands': score_bands,
        'branches': branches,
        'insights': insights,
        'watchlist': watchlist,
        'ledger': ledger_meta,
        'disclaimer': (
            'Origination KPIs from applications, appraisals, committee and disbursement. '
            + (
                f'CBS ledger connected ({ledger_meta["label"]}).'
                if ledger_meta.get('connected')
                else 'CBS outstanding/NPL unavailable — using origination proxies.'
            )
        ),
    }


def _kpi(key, label, value, fmt, delta_pct, explanation, risk, note) -> Dict[str, Any]:
    return {
        'key': key,
        'label': label,
        'value': value,
        'format': fmt,
        'delta_pct': delta_pct,
        'explanation': explanation,
        'risk': risk,
        'note': note,
    }


def _explain_book(book: float, growth: Optional[float], count: int) -> str:
    if growth is None:
        return f'{count} approved loans · ETB {book:,.0f} book'
    direction = 'up' if growth >= 0 else 'down'
    return (
        f'Approved book {direction} {abs(growth)}% MoM across {count} loans '
        f'(ETB {book:,.0f}).'
    )


def build_insights(qs: QuerySet, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rule-generated portfolio insights (Phase 1 — no LLM)."""
    insights: List[Dict[str, Any]] = []

    if ctx.get('risk_flagged_share', 0) >= 20:
        insights.append({
            'severity': 'high',
            'confidence': 0.82,
            'title': 'Elevated weak-band concentration',
            'body': (
                f"{ctx['risk_flagged_share']}% of scored applications sit in Weak/Unacceptable. "
                'Review collateral coverage and DSCR before more approvals.'
            ),
            'action_label': 'Open pipeline',
            'action_url_name': 'view_report',
        })

    if ctx.get('high_risk_exposure', 0) >= 1:
        insights.append({
            'severity': 'medium',
            'confidence': 0.75,
            'title': 'High-risk approved exposure',
            'body': (
                f"ETB {ctx['high_risk_exposure']:,.0f} of approved book is on weak score bands. "
                'Prioritize monitoring and condition fulfillment.'
            ),
            'action_label': 'Post-approval queue',
            'action_url_name': 'post_approval_queue',
        })

    if ctx.get('in_appraisal', 0) >= 5:
        insights.append({
            'severity': 'info',
            'confidence': 0.7,
            'title': 'Appraisal backlog',
            'body': (
                f"{ctx['in_appraisal']} assigned loans still lack a completed appraisal. "
                'Clear Sheet 6 finish to unblock committee.'
            ),
            'action_label': 'Loan requests',
            'action_url_name': 'view_loan_requests',
        })

    if ctx.get('pending_committee', 0) >= 3:
        insights.append({
            'severity': 'medium',
            'confidence': 0.78,
            'title': 'Committee queue pressure',
            'body': (
                f"{ctx['pending_committee']} loans await committee votes. "
                'Managers should clear My votes needed first.'
            ),
            'action_label': 'Approval queue',
            'action_url_name': 'view_loan_requests_manager',
        })

    if ctx.get('awaiting_disburse', 0) >= 1:
        insights.append({
            'severity': 'info',
            'confidence': 0.8,
            'title': 'Disbursement pipeline active',
            'body': (
                f"{ctx['awaiting_disburse']} committee-approved loans are in post-approval "
                '(conditions / schedule / ready).'
            ),
            'action_label': 'Post-approval',
            'action_url_name': 'post_approval_queue',
        })

    growth = ctx.get('growth_pct')
    if growth is not None and growth <= -15:
        insights.append({
            'severity': 'medium',
            'confidence': 0.65,
            'title': 'Approved book contracting',
            'body': f'MoM approved book is down {abs(growth)}%. Check branch pipeline intake.',
            'action_label': 'Branch dashboard',
            'action_url_name': 'branch_report_dashboard',
        })
    elif growth is not None and growth >= 25:
        insights.append({
            'severity': 'info',
            'confidence': 0.68,
            'title': 'Strong MoM origination growth',
            'body': (
                f'Approved book up {growth}% this month. Watch risk-flagged share as volume rises.'
            ),
            'action_label': 'Credit Intelligence',
            'action_url_name': 'credit_intelligence_overview',
        })

    if not insights:
        insights.append({
            'severity': 'info',
            'confidence': 0.6,
            'title': 'Portfolio calm',
            'body': 'No elevated risk rules fired in scope. Continue monitoring score bands and committee TAT.',
            'action_label': 'Reports',
            'action_url_name': 'view_report_options',
        })

    return insights[:6]


def _watchlist(qs: QuerySet, limit: int = 8) -> List[Dict[str, Any]]:
    """Highest-risk scored loans for officer/manager attention."""
    rows = (
        qs.filter(appraisal__credit_score_total__isnull=False)
        .filter(
            Q(appraisal__credit_score_band__in=WEAK_BANDS)
            | Q(appraisal__credit_score_total__lt=55)
        )
        .select_related('appraisal', 'branch')
        .order_by('appraisal__credit_score_total')[:limit]
    )
    out = []
    for lr in rows:
        appr = lr.appraisal
        score = float(appr.credit_score_total) if appr and appr.credit_score_total is not None else None
        out.append({
            'id': lr.id,
            'loan_request_id': lr.loan_request_id,
            'applicant_name': lr.applicant_name,
            'branch': lr.branch.name if lr.branch_id else '',
            'score': score,
            'score_1000': int(score * 10) if score is not None else None,
            'band': getattr(appr, 'credit_score_band', '') or '',
            'amount': _money(lr.committee_final_amount or (appr.amount_approved if appr else None) or lr.amount_requested),
            'status': lr.status,
            'committee_status': lr.committee_status or '',
        })
    return out
