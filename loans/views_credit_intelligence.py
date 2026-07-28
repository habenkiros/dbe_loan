"""Credit Intelligence dashboard views (Phases 1–4)."""

from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_GET, require_http_methods

from loans.ci_assistant import run_assistant_query
from loans.ci_collateral import build_collateral_intelligence
from loans.ci_decision import build_application_decision
from loans.ci_portfolio import build_portfolio_analytics
from loans.ci_workspaces import build_manager_workspace, build_officer_workspace, build_risk_alerts
from loans.credit_intelligence import build_overview
from loans.portfolio_ledger import get_ledger_adapter
from loans.reporting import filter_choices_for_user


def _resolve_insight_urls(insights):
    out = []
    for item in insights:
        row = dict(item)
        name = row.pop('action_url_name', None)
        args = row.pop('action_url_args', None) or []
        href = '#'
        if name:
            try:
                href = reverse(name, args=args) if args else reverse(name)
            except NoReverseMatch:
                href = '#'
        row['action_url'] = href
        out.append(row)
    return out


def _overview_context(user):
    data = build_overview(user)
    data['insights'] = _resolve_insight_urls(data.get('insights') or [])
    data['ledger_connected'] = get_ledger_adapter().is_connected()
    return data


def _ci_shell(active: str, **extra):
    return {
        'ci_nav_active': active,
        **extra,
    }


@login_required(login_url='login')
def credit_intelligence_overview(request):
    """Executive Credit Intelligence Overview (HTML)."""
    data = _overview_context(request.user)
    pipeline = data.get('pipeline') or {}
    return render(request, 'loans/ci/overview.html', _ci_shell('overview', **{
        'ci': data,
        'scope_label': data.get('scope_label'),
        'portfolio_risk_level': data.get('portfolio_risk_level'),
        'kpis': data.get('kpis') or [],
        'insights': data.get('insights') or [],
        'watchlist': data.get('watchlist') or [],
        'score_bands': data.get('score_bands') or [],
        'branches': data.get('branches') or [],
        'pipeline': pipeline,
        'disclaimer': data.get('disclaimer'),
        'ledger_connected': data.get('ledger_connected'),
        'score_bands_json': json.dumps(data.get('score_bands') or []),
        'branches_json': json.dumps(data.get('branches') or []),
        'pipeline_json': json.dumps({
            'approved': pipeline.get('approved', 0),
            'pending': pipeline.get('pending', 0),
            'rejected': pipeline.get('rejected', 0),
        }),
    }))


@login_required(login_url='login')
def credit_intelligence_overview_api(request):
    return JsonResponse(_overview_context(request.user))


@login_required(login_url='login')
def ci_insights(request):
    alerts = _resolve_insight_urls(build_risk_alerts(request.user, limit=24))
    return render(request, 'loans/ci/insights.html', _ci_shell('insights', **{
        'scope_label': build_overview(request.user).get('scope_label'),
        'alerts': alerts,
    }))


@login_required(login_url='login')
def ci_officer(request):
    data = build_officer_workspace(request.user)
    data['alerts'] = _resolve_insight_urls(data.get('alerts') or [])
    return render(request, 'loans/ci/officer.html', _ci_shell('officer', **{
        'ws': data,
        'scope_label': data.get('scope_label'),
        'counts': data.get('counts') or {},
        'queue': data.get('queue') or [],
        'decision_cards': data.get('decision_cards') or [],
        'alerts': data.get('alerts') or [],
        'watchlist': data.get('watchlist') or [],
    }))


@login_required(login_url='login')
def ci_manager(request):
    data = build_manager_workspace(request.user)
    data['alerts'] = _resolve_insight_urls(data.get('alerts') or [])
    return render(request, 'loans/ci/manager.html', _ci_shell('manager', **{
        'ws': data,
        'scope_label': data.get('scope_label'),
        'pipeline': data.get('pipeline') or {},
        'branches': data.get('branches') or [],
        'team': data.get('team') or [],
        'alerts': data.get('alerts') or [],
        'pending_votes': data.get('pending_votes') or [],
        'branches_json': json.dumps(data.get('branches') or []),
    }))


@login_required(login_url='login')
def ci_portfolio(request):
    params = request.GET
    data = build_portfolio_analytics(request.user, params)
    choices = data.pop('filter_choices', {}) or filter_choices_for_user(request.user)
    return render(request, 'loans/ci/portfolio.html', _ci_shell('portfolio', **{
        'scope_label': data.get('scope_label'),
        'summary': data.get('summary') or {},
        'filters': data.get('filters') or {},
        'score_bands': data.get('score_bands') or [],
        'by_branch': data.get('by_branch') or [],
        'by_category': data.get('by_category') or [],
        'by_collateral': data.get('by_collateral') or [],
        'disclaimer': data.get('disclaimer'),
        'categories': data.get('categories') or [],
        'querystring': request.GET.urlencode(),
        'score_bands_json': json.dumps(data.get('score_bands') or []),
        'status_mix_json': json.dumps(data.get('status_mix') or []),
        'branches_json': json.dumps([
            {'name': b['name'], 'count': b['count']} for b in (data.get('by_branch') or [])[:12]
        ]),
        **choices,
    }))


@login_required(login_url='login')
def ci_collateral(request):
    data = build_collateral_intelligence(request.user)
    return render(request, 'loans/ci/collateral.html', _ci_shell('collateral', **{
        'scope_label': data.get('scope_label'),
        'kpis': data.get('kpis') or {},
        'high_risk': data.get('high_risk') or [],
        'by_type': data.get('by_type') or [],
        'disclaimer': data.get('disclaimer'),
        'by_type_json': json.dumps(data.get('by_type') or []),
    }))


@login_required(login_url='login')
@require_http_methods(['GET', 'POST'])
def ci_assistant(request):
    query = ''
    result = None
    if request.method == 'POST':
        query = (request.POST.get('query') or '').strip()
        result = run_assistant_query(request.user, query)
    elif request.GET.get('q'):
        query = (request.GET.get('q') or '').strip()
        result = run_assistant_query(request.user, query)
    return render(request, 'loans/ci/assistant.html', _ci_shell('assistant', **{
        'query': query,
        'result': result,
        'suggestions': [
            'Show risky loans in my scope',
            'Why might NPL look elevated?',
            'Compare branch risk performance',
            'Analyze repayment capacity / DSCR',
            'Summarize collateral coverage',
            'What is the approval rate?',
        ],
        'ledger_connected': get_ledger_adapter().is_connected(),
    }))


@login_required(login_url='login')
@require_GET
def ci_assistant_api(request):
    query = (request.GET.get('q') or request.GET.get('query') or '').strip()
    return JsonResponse(run_assistant_query(request.user, query))


@login_required(login_url='login')
@require_GET
def ci_application_decision_api(request, loan_request_id):
    from loans.models import LoanRequest
    from loans.reporting import reporting_base_queryset

    lr = get_object_or_404(reporting_base_queryset(request.user), pk=loan_request_id)
    card = build_application_decision(lr)
    if not card:
        return JsonResponse({'error': 'No appraisal yet'}, status=404)
    return JsonResponse(card)
