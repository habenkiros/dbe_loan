"""Phase 4 — Rule-based Credit Analyst Assistant + ledger adapter stub."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from django.urls import reverse
from django.utils import timezone

from loans.ci_collateral import build_collateral_intelligence
from loans.ci_portfolio import build_portfolio_analytics
from loans.ci_workspaces import build_risk_alerts
from loans.credit_intelligence import WEAK_BANDS, build_overview, scoped_loans
from loans.portfolio_ledger import get_ledger_adapter


def run_assistant_query(user, query: str) -> Dict[str, Any]:
    """
    Structured NL router — keyword rules, not generative LLM.
    Returns answer text, optional chart payload, and drill-down links.
    """
    q = (query or '').strip()
    q_lower = q.lower()
    if not q_lower:
        return {
            'query': q,
            'understood': False,
            'answer': 'Ask about risky loans, NPL/outstanding (ledger stub), branch risk, DSCR, or collateral coverage.',
            'charts': [],
            'links': _default_links(),
            'generated_at': timezone.now().isoformat(),
        }

    overview = build_overview(user)
    portfolio = build_portfolio_analytics(user, {})
    collateral = build_collateral_intelligence(user)
    alerts = build_risk_alerts(user, limit=8)
    ledger = get_ledger_adapter()

    charts: List[Dict[str, Any]] = []
    links: List[Dict[str, str]] = []
    answer = ''
    understood = True

    if _match(q_lower, ('npl', 'non-performing', 'non performing', 'default rate')):
        npl = ledger.npl_ratio(user)
        if npl is None:
            answer = (
                'True NPL is not available yet — core banking ledger is not connected. '
                f'Origination proxy: risk-flagged (Weak/Unacceptable) share is '
                f'{_kpi(overview, "risk_flagged")}% of scored apps; '
                f'high-risk approved exposure is ETB {_kpi(overview, "high_risk_exposure"):,.0f}.'
            )
        else:
            answer = f'Ledger NPL ratio: {npl:.2%}.'
        links = [
            {'label': 'Overview', 'url': reverse('credit_intelligence_overview')},
            {'label': 'Portfolio', 'url': reverse('ci_portfolio')},
        ]
        charts.append({'type': 'score_bands', 'data': overview.get('score_bands') or []})

    elif _match(q_lower, ('outstanding', 'portfolio balance', 'book balance')):
        out = ledger.total_outstanding(user)
        if out is None:
            answer = (
                'Live outstanding is not wired (CBS adapter stub). '
                f'Approved origination book in scope: ETB {_kpi(overview, "approved_book"):,.0f}. '
                f'Bureau outstanding where captured: ETB {_kpi(overview, "bureau_outstanding"):,.0f}.'
            )
        else:
            answer = f'Ledger outstanding: ETB {float(out):,.0f}.'
        links = [{'label': 'Overview', 'url': reverse('credit_intelligence_overview')}]

    elif _match(q_lower, ('risky', 'high-risk', 'weak band', 'watchlist', 'sme risk')):
        watch = overview.get('watchlist') or []
        place = _extract_place(q_lower)
        qs, _ = scoped_loans(user)
        if place:
            qs = qs.filter(
                Q_branch_or_district(place)
            )
            watch = [
                w for w in watch
                if place in (w.get('branch') or '').lower()
            ] or [
                {
                    'loan_request_id': lr.loan_request_id,
                    'applicant_name': lr.applicant_name,
                    'branch': lr.branch.name if lr.branch_id else '',
                    'band': getattr(lr.appraisal, 'credit_score_band', ''),
                    'score_1000': int(float(lr.appraisal.credit_score_total) * 10)
                    if lr.appraisal and lr.appraisal.credit_score_total is not None else None,
                    'id': lr.id,
                }
                for lr in qs.filter(appraisal__credit_score_band__in=WEAK_BANDS)
                .select_related('appraisal', 'branch')[:8]
            ]
        answer = (
            f'Found {len(watch)} high-risk scored applications'
            + (f' matching “{place}”' if place else ' in your scope')
            + '. Top: '
            + ('; '.join(
                f'{w.get("loan_request_id")} ({w.get("applicant_name")}, '
                f'{w.get("band") or "—"}, {w.get("score_1000") or "—"}/1000)'
                for w in watch[:5]
            ) or 'none right now')
            + '.'
        )
        charts.append({'type': 'score_bands', 'data': overview.get('score_bands') or []})
        links = [{'label': 'Officer workspace', 'url': reverse('ci_officer')}]
        for w in watch[:5]:
            if w.get('id'):
                links.append({
                    'label': w.get('loan_request_id') or 'Loan',
                    'url': reverse('loan_request_detail', args=[w['id']]),
                })

    elif _match(q_lower, ('branch', 'compare branch', 'branch risk')):
        branches = portfolio.get('by_branch') or []
        if not branches:
            answer = 'No branch rows in the current filtered scope.'
        else:
            top = branches[0]
            riskiest = max(branches, key=lambda b: b.get('weak') or 0)
            answer = (
                f'Top volume: {top["name"]} ({top["count"]} loans, ETB {top["amount"]:,.0f}). '
                f'Most weak-band apps: {riskiest["name"]} ({riskiest.get("weak") or 0}). '
                f'Approval rate overall: {portfolio["summary"]["approval_rate"]}%.'
            )
        charts.append({
            'type': 'branches',
            'data': [{'name': b['name'], 'count': b['count']} for b in branches[:10]],
        })
        links = [
            {'label': 'Portfolio', 'url': reverse('ci_portfolio')},
            {'label': 'Manager workspace', 'url': reverse('ci_manager')},
        ]

    elif _match(q_lower, ('dscr', 'repayment capacity', 'cash flow', 'cashflow')):
        s = portfolio['summary']
        answer = (
            f'Average annual DSCR (where entered): '
            f'{s["avg_dscr_annual"] if s["avg_dscr_annual"] is not None else "n/a"}. '
            f'{s["low_dscr_count"]} apps below 1.0 '
            f'({s["low_dscr_share"]}% of those with DSCR).'
        )
        links = [{'label': 'Portfolio filters', 'url': reverse('ci_portfolio')}]
        for a in alerts:
            if a.get('kind') == 'repayment_capacity' and a.get('loan_id'):
                links.append({
                    'label': a['title'][:40],
                    'url': reverse('loan_appraisal_step', args=[a['loan_id'], 3]),
                })

    elif _match(q_lower, ('collateral', 'coverage', 'valuation')):
        k = collateral['kpis']
        answer = (
            f'Total collateral value in scope: ETB {k["total_collateral_value"]:,.0f} '
            f'({k["apps_with_value"]} apps with value). '
            f'Avg coverage ratio: {k["avg_coverage_ratio"] if k["avg_coverage_ratio"] is not None else "n/a"}. '
            f'{k["below_policy_count"]} below policy min ({k["policy_min_ratio"]:.0%}×). '
            f'{k["missing_value_count"]} apps missing collateral value.'
        )
        charts.append({'type': 'collateral_types', 'data': collateral.get('by_type') or []})
        links = [{'label': 'Collateral Intelligence', 'url': reverse('ci_collateral')}]

    elif _match(q_lower, ('approve', 'approval rate', 'reject')):
        s = portfolio['summary']
        answer = (
            f'Approval rate {s["approval_rate"]}% '
            f'({s["approved"]} approved / {s["total"]} in filter). '
            f'Reject rate {s["reject_rate"]}%.'
        )
        charts.append({'type': 'status_mix', 'data': portfolio.get('status_mix') or []})
        links = [{'label': 'Portfolio', 'url': reverse('ci_portfolio')}]

    else:
        understood = False
        answer = (
            'I can answer questions like: '
            '“Show risky SME loans”, “Why might NPL look high?”, '
            '“Compare branch risk”, “Analyze DSCR”, “Collateral coverage”. '
            f'Portfolio risk level now: {overview.get("portfolio_risk_level")}.'
        )
        links = _default_links()

    return {
        'query': q,
        'understood': understood,
        'answer': answer,
        'charts': charts,
        'links': links[:12],
        'alerts_sample': alerts[:3],
        'ledger_connected': ledger.is_connected(),
        'generated_at': timezone.now().isoformat(),
    }


def _match(text: str, needles) -> bool:
    return any(n in text for n in needles)


def _extract_place(text: str) -> Optional[str]:
    m = re.search(r'\bin\s+([a-zA-Z][a-zA-Z\s-]{1,40})', text)
    if not m:
        return None
    place = m.group(1).strip().lower()
    for stop in ('my', 'the', 'our', 'this', 'scope', 'portfolio'):
        if place == stop:
            return None
    return place


def Q_branch_or_district(place: str):
    from django.db.models import Q
    return (
        Q(branch__name__icontains=place)
        | Q(branch__district__name__icontains=place)
        | Q(applicant_name__icontains=place)
    )


def _kpi(overview: Dict[str, Any], key: str) -> float:
    for k in overview.get('kpis') or []:
        if k.get('key') == key:
            try:
                return float(k.get('value') or 0)
            except Exception:
                return 0.0
    return 0.0


def _default_links() -> List[Dict[str, str]]:
    return [
        {'label': 'Overview', 'url': reverse('credit_intelligence_overview')},
        {'label': 'Officer workspace', 'url': reverse('ci_officer')},
        {'label': 'Portfolio', 'url': reverse('ci_portfolio')},
        {'label': 'Assistant', 'url': reverse('ci_assistant')},
    ]
