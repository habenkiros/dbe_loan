"""Phase 2 — Credit Officer / Manager workspaces + risk alert feed."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from loans.ci_decision import build_application_decision
from loans.credit_intelligence import WEAK_BANDS, _money, _watchlist, scoped_loans


def build_risk_alerts(user, limit: int = 12) -> List[Dict[str, Any]]:
    """Portfolio + application risk alerts for Intelligence Center."""
    from loans.ci_alerts import (
        append_aging_file_alerts,
        append_committee_sla_alerts,
        append_coverage_alerts,
        append_missing_docs_alerts,
    )
    from loans.models import LoanRequest

    qs, _ = scoped_loans(user)
    alerts: List[Dict[str, Any]] = []

    # Operational differentiators (aging / docs / SLA / policy coverage)
    append_aging_file_alerts(qs, alerts, limit=4)
    append_missing_docs_alerts(qs, alerts, limit=4)
    append_committee_sla_alerts(qs, alerts, limit=4)
    append_coverage_alerts(qs, alerts, limit=4)

    weak = qs.filter(appraisal__credit_score_band__in=WEAK_BANDS).select_related(
        'appraisal', 'branch',
    ).order_by('appraisal__credit_score_total')[:6]
    for lr in weak:
        appr = lr.appraisal
        score = float(appr.credit_score_total) if appr and appr.credit_score_total is not None else None
        alerts.append({
            'severity': 'high' if (appr and appr.credit_score_band == 'unacceptable') else 'medium',
            'kind': 'high_risk_borrower',
            'title': f'High-risk scored: {lr.applicant_name}',
            'body': (
                f'{lr.loan_request_id} · band {getattr(appr, "credit_score_band", "")} · '
                f'score {int(score * 10) if score is not None else "—"}/1000'
            ),
            'loan_id': lr.id,
            'action_label': 'Open loan',
            'action_url_name': 'loan_request_detail',
            'action_url_args': [lr.id],
        })

    low_dscr = qs.filter(
        appraisal__dscr_annual__isnull=False,
        appraisal__dscr_annual__lt=Decimal('1.0'),
    ).select_related('appraisal')[:4]
    for lr in low_dscr:
        dscr = lr.appraisal.dscr_annual
        alerts.append({
            'severity': 'high',
            'kind': 'repayment_capacity',
            'title': f'Low annual DSCR: {lr.applicant_name}',
            'body': f'{lr.loan_request_id} · DSCR {float(dscr):.2f}',
            'loan_id': lr.id,
            'action_label': 'Sheet 3',
            'action_url_name': 'loan_appraisal_step',
            'action_url_args': [lr.id, 3],
        })

    pending = qs.filter(committee_status=LoanRequest.COMMITTEE_PENDING).count()
    if pending >= 3:
        alerts.append({
            'severity': 'medium',
            'kind': 'committee_queue',
            'title': 'Committee queue pressure',
            'body': f'{pending} loans awaiting committee votes in your scope.',
            'action_label': 'Approval queue',
            'action_url_name': 'view_loan_requests_manager',
            'action_url_args': [],
        })

    order = {'high': 0, 'medium': 1, 'info': 2}
    alerts.sort(key=lambda a: order.get(a.get('severity'), 9))
    return alerts[:limit]


def build_officer_workspace(user) -> Dict[str, Any]:
    """Assigned pipeline, pending reviews, AI recs, alerts for loan officers / BM."""
    from loans.models import LoanRequest

    qs, scope_label = scoped_loans(user)
    role = getattr(user, 'role', None)
    if role == 'loan_officer':
        assigned = qs
    else:
        assigned = qs.filter(assigned_loan_officer__isnull=False)

    pending_appraisal = assigned.filter(
        appraisal_completed_at__isnull=True,
    ).exclude(status__iexact='Rejected')
    pending_committee = assigned.filter(committee_status=LoanRequest.COMMITTEE_PENDING)
    returned = assigned.filter(committee_status=LoanRequest.COMMITTEE_RETURNED)

    queue = list(
        pending_appraisal.select_related('appraisal', 'branch', 'assigned_loan_officer')
        .order_by('-date_requested')[:15]
    )
    decisions = []
    for lr in queue[:8]:
        if getattr(lr, 'appraisal', None):
            card = build_application_decision(lr, lr.appraisal)
            if card:
                decisions.append(card)

    alerts = build_risk_alerts(user)
    watch = _watchlist(assigned, limit=8)

    return {
        'scope_label': scope_label,
        'role_view': 'officer',
        'counts': {
            'assigned': assigned.count(),
            'pending_appraisal': pending_appraisal.count(),
            'pending_committee': pending_committee.count(),
            'returned': returned.count(),
            'watchlist': len(watch),
        },
        'queue': [
            {
                'id': lr.id,
                'loan_request_id': lr.loan_request_id,
                'applicant_name': lr.applicant_name,
                'branch': lr.branch.name if lr.branch_id else '',
                'amount': _money(lr.amount_requested),
                'status': lr.status,
                'score': float(lr.appraisal.credit_score_total)
                if getattr(lr, 'appraisal', None) and lr.appraisal.credit_score_total is not None
                else None,
                'band': getattr(lr.appraisal, 'credit_score_band', '') if getattr(lr, 'appraisal', None) else '',
                'officer': (
                    (lr.assigned_loan_officer.get_full_name() or lr.assigned_loan_officer.username)
                    if lr.assigned_loan_officer_id else ''
                ),
            }
            for lr in queue
        ],
        'decision_cards': decisions,
        'alerts': alerts,
        'watchlist': watch,
        'generated_at': timezone.now().isoformat(),
    }


def build_manager_workspace(user) -> Dict[str, Any]:
    """Approval pipeline, branch comparison, team load for managers/exec."""
    from loans.models import LoanRequest

    User = get_user_model()
    qs, scope_label = scoped_loans(user)

    pending_committee = qs.filter(committee_status=LoanRequest.COMMITTEE_PENDING).count()
    returned = qs.filter(committee_status=LoanRequest.COMMITTEE_RETURNED).count()
    approved = qs.filter(
        Q(status__iexact='Approved') | Q(committee_status=LoanRequest.COMMITTEE_APPROVED)
    ).count()
    in_appraisal = qs.filter(
        appraisal_completed_at__isnull=True,
        assigned_loan_officer__isnull=False,
    ).exclude(status__iexact='Rejected').count()
    awaiting_disburse = qs.filter(
        disbursement_status__in=[
            LoanRequest.DISBURSE_AWAITING_CONDITIONS,
            LoanRequest.DISBURSE_SCHEDULE_CONFIRMED,
            LoanRequest.DISBURSE_READY,
        ]
    ).count()

    branch_agg = list(
        qs.values('branch__name')
        .annotate(
            total=Count('id'),
            pending_c=Count('id', filter=Q(committee_status=LoanRequest.COMMITTEE_PENDING)),
            weak=Count('id', filter=Q(appraisal__credit_score_band__in=WEAK_BANDS)),
            avg_score=Avg('appraisal__credit_score_total'),
            requested_sum=Sum('amount_requested'),
        )
        .order_by('-total')[:12]
    )
    branches = [
        {
            'name': r['branch__name'] or 'Unassigned',
            'total': r['total'],
            'pending_committee': r['pending_c'],
            'weak_band': r['weak'],
            'avg_score': round(float(r['avg_score']), 1) if r['avg_score'] is not None else None,
            'requested': _money(r['requested_sum']),
        }
        for r in branch_agg
    ]

    officer_ids = list(
        qs.exclude(assigned_loan_officer_id=None)
        .values_list('assigned_loan_officer_id', flat=True)
        .distinct()[:20]
    )
    team = []
    for oid in officer_ids:
        oqs = qs.filter(assigned_loan_officer_id=oid)
        u = User.objects.filter(pk=oid).first()
        if not u:
            continue
        avg = oqs.aggregate(a=Avg('appraisal__credit_score_total'))['a']
        team.append({
            'id': oid,
            'name': u.get_full_name() or u.username,
            'assigned': oqs.count(),
            'pending_appraisal': oqs.filter(appraisal_completed_at__isnull=True)
            .exclude(status__iexact='Rejected').count(),
            'pending_committee': oqs.filter(committee_status=LoanRequest.COMMITTEE_PENDING).count(),
            'avg_score': round(float(avg), 1) if avg is not None else None,
        })
    team.sort(key=lambda t: (-t['pending_appraisal'], -t['assigned']))

    alerts = build_risk_alerts(user)
    recent_pending = list(
        qs.filter(committee_status=LoanRequest.COMMITTEE_PENDING)
        .select_related('appraisal', 'branch', 'assigned_loan_officer')
        .order_by('date_requested')[:12]
    )

    return {
        'scope_label': scope_label,
        'role_view': 'manager',
        'pipeline': {
            'in_appraisal': in_appraisal,
            'pending_committee': pending_committee,
            'returned': returned,
            'approved': approved,
            'awaiting_disburse': awaiting_disburse,
            'total': qs.count(),
        },
        'branches': branches,
        'team': team,
        'alerts': alerts,
        'pending_votes': [
            {
                'id': lr.id,
                'loan_request_id': lr.loan_request_id,
                'applicant_name': lr.applicant_name,
                'branch': lr.branch.name if lr.branch_id else '',
                'amount': _money(lr.amount_requested),
                'score': float(lr.appraisal.credit_score_total)
                if getattr(lr, 'appraisal', None) and lr.appraisal.credit_score_total is not None
                else None,
                'band': getattr(lr.appraisal, 'credit_score_band', '') if getattr(lr, 'appraisal', None) else '',
                'officer': (
                    (lr.assigned_loan_officer.get_full_name() or lr.assigned_loan_officer.username)
                    if lr.assigned_loan_officer_id else ''
                ),
            }
            for lr in recent_pending
        ],
        'generated_at': timezone.now().isoformat(),
    }
