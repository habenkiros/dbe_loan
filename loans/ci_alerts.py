"""Credit Intelligence operational risk alerts (aging, docs, SLA, coverage)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.db.models import Q
from django.utils import timezone


def _int_setting(name: str, default: int) -> int:
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


def aging_appraisal_days() -> int:
    return max(1, _int_setting('CI_AGING_APPRAISAL_DAYS', 7))


def committee_sla_days() -> int:
    return max(1, _int_setting('CI_COMMITTEE_SLA_DAYS', 5))


def _days_since(dt) -> Optional[int]:
    if not dt:
        return None
    now = timezone.now()
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return max(0, (now.date() - dt.date()).days)


def _min_coverage_ratio() -> Decimal:
    try:
        from collateral.policy import get_collateral_policy
        return Decimal(str(get_collateral_policy().min_coverage_ratio))
    except Exception:
        return Decimal('1.0')


def append_aging_file_alerts(qs, alerts: List[Dict[str, Any]], *, limit: int = 5) -> None:
    """Files stuck in appraisal longer than policy days."""
    from loans.models import LoanRequest

    days = aging_appraisal_days()
    cutoff = timezone.now() - timedelta(days=days)
    rows = (
        qs.filter(
            appraisal_completed_at__isnull=True,
            assigned_loan_officer__isnull=False,
            date_requested__lte=cutoff,
        )
        .exclude(status__iexact='Rejected')
        .exclude(committee_status=LoanRequest.COMMITTEE_APPROVED)
        .select_related('branch', 'assigned_loan_officer')
        .order_by('date_requested')[:limit]
    )
    for lr in rows:
        age = _days_since(lr.date_requested)
        officer = ''
        if lr.assigned_loan_officer_id:
            officer = lr.assigned_loan_officer.get_full_name() or lr.assigned_loan_officer.username
        alerts.append({
            'severity': 'high' if (age or 0) >= days * 2 else 'medium',
            'kind': 'aging_file',
            'title': f'Aging appraisal file: {lr.applicant_name}',
            'body': (
                f'{lr.loan_request_id} · open {age if age is not None else "—"} days '
                f'(threshold {days})'
                + (f' · officer {officer}' if officer else '')
            ),
            'loan_id': lr.id,
            'action_label': 'Open loan',
            'action_url_name': 'loan_request_detail',
            'action_url_args': [lr.id],
        })


def append_missing_docs_alerts(qs, alerts: List[Dict[str, Any]], *, limit: int = 5) -> None:
    """Open files missing required checklist documents."""
    from loans.document_checklist import checklist_for_loan, required_items
    from loans.models import LoanRequest

    candidates = (
        qs.exclude(status__iexact='Rejected')
        .exclude(disbursement_status=LoanRequest.DISBURSE_DISBURSED)
        .prefetch_related('application_documents')
        .order_by('-date_requested')[:40]
    )
    found = 0
    for lr in candidates:
        if found >= limit:
            break
        try:
            required = required_items(checklist_for_loan(lr))
        except Exception:
            continue
        if not required:
            continue
        uploaded = {d.document_type_id for d in lr.application_documents.all()}
        missing = [item.name for item in required if item.id not in uploaded]
        if not missing:
            continue
        found += 1
        shown = ', '.join(missing[:3])
        more = f' (+{len(missing) - 3} more)' if len(missing) > 3 else ''
        alerts.append({
            'severity': 'medium',
            'kind': 'missing_docs',
            'title': f'Missing documents: {lr.applicant_name}',
            'body': f'{lr.loan_request_id} · {shown}{more}',
            'loan_id': lr.id,
            'action_label': 'Documents',
            'action_url_name': 'upload_loan_request_documents',
            'action_url_args': [lr.id],
        })


def append_committee_sla_alerts(qs, alerts: List[Dict[str, Any]], *, limit: int = 5) -> None:
    """Committee-pending loans past SLA days since submission."""
    from loans.models import LoanRequest

    days = committee_sla_days()
    cutoff = timezone.now() - timedelta(days=days)
    rows = (
        qs.filter(
            committee_status__in=(
                LoanRequest.COMMITTEE_PENDING,
                LoanRequest.COMMITTEE_PENDED,
            ),
        )
        .filter(
            Q(submitted_to_committee_at__lte=cutoff)
            | Q(submitted_to_committee_at__isnull=True, date_requested__lte=cutoff)
        )
        .select_related('branch', 'current_approval_level')
        .order_by('submitted_to_committee_at', 'date_requested')[:limit]
    )
    for lr in rows:
        anchor = lr.submitted_to_committee_at or lr.date_requested
        age = _days_since(anchor)
        level = ''
        if lr.current_approval_level_id:
            level = lr.current_approval_level.name
        alerts.append({
            'severity': 'high' if (age or 0) >= days * 2 else 'medium',
            'kind': 'committee_sla',
            'title': f'Committee SLA breach: {lr.applicant_name}',
            'body': (
                f'{lr.loan_request_id} · pending {age if age is not None else "—"} days '
                f'(SLA {days}d)'
                + (f' · {level}' if level else '')
            ),
            'loan_id': lr.id,
            'action_label': 'Committee review',
            'action_url_name': 'loan_request_detail_manager',
            'action_url_args': [lr.id],
        })


def committee_sla_breach_loans(*, limit: int = 200):
    """
    Loans past committee SLA for digest emails.

    Returns list of (loan, age_days, severity) ordered by oldest first.
    """
    from loans.models import LoanRequest

    days = committee_sla_days()
    cutoff = timezone.now() - timedelta(days=days)
    qs = (
        LoanRequest.objects.filter(
            committee_status__in=(
                LoanRequest.COMMITTEE_PENDING,
                LoanRequest.COMMITTEE_PENDED,
            ),
        )
        .filter(
            Q(submitted_to_committee_at__lte=cutoff)
            | Q(submitted_to_committee_at__isnull=True, date_requested__lte=cutoff)
        )
        .select_related(
            'branch', 'current_approval_level', 'assigned_loan_officer',
        )
        .order_by('submitted_to_committee_at', 'date_requested')[:limit]
    )

    rows = []
    for lr in qs:
        anchor = lr.submitted_to_committee_at or lr.date_requested
        age = _days_since(anchor) or 0
        severity = 'high' if age >= days * 2 else 'medium'
        rows.append((lr, age, severity))
    return rows


def send_committee_sla_digest(*, dry_run: bool = False, dedupe_hours: int = 24) -> Dict[str, Any]:
    """Notify eligible voters (and officer) for each SLA-breached committee file."""
    from loans.models import LoanNotification
    from loans.services.notifications import (
        notify_assigned_officer,
        notify_eligible_voters,
    )

    days = committee_sla_days()
    notified_loans = 0
    notifications = 0
    skipped = 0
    details = []

    for lr, age, severity in committee_sla_breach_loans():
        level = lr.current_approval_level
        if not level:
            skipped += 1
            continue
        recent = LoanNotification.objects.filter(
            loan_request=lr,
            kind=LoanNotification.KIND_COMMITTEE_SLA,
            created_at__gte=timezone.now() - timedelta(hours=max(1, dedupe_hours)),
        ).exists()
        if recent:
            skipped += 1
            details.append({'loan': lr.loan_request_id, 'status': 'deduped'})
            continue

        title = f'Committee SLA: {lr.loan_request_id} ({age}d / {days}d)'
        message = (
            f'{lr.applicant_name} is still at {level.name} after {age} day(s) '
            f'(SLA {days} days). Severity: {severity}. '
            'Please review and cast or update your vote.'
        )
        if dry_run:
            notified_loans += 1
            details.append({'loan': lr.loan_request_id, 'status': 'dry_run', 'age': age})
            continue

        n = notify_eligible_voters(
            lr,
            level,
            kind=LoanNotification.KIND_COMMITTEE_SLA,
            title=title,
            message=message,
        )
        n += notify_assigned_officer(
            lr,
            kind=LoanNotification.KIND_COMMITTEE_SLA,
            title=title,
            message=message,
        )
        notifications += n
        notified_loans += 1
        details.append({'loan': lr.loan_request_id, 'status': 'sent', 'notifications': n, 'age': age})

    return {
        'sla_days': days,
        'notified_loans': notified_loans,
        'notifications': notifications,
        'skipped': skipped,
        'details': details,
        'dry_run': dry_run,
    }

def append_coverage_alerts(qs, alerts: List[Dict[str, Any]], *, limit: int = 5) -> None:
    """Collateral coverage below bank policy minimum."""
    min_ratio = _min_coverage_ratio()
    thin_cov = (
        qs.filter(
            appraisal__collateral_coverage_ratio__isnull=False,
            appraisal__collateral_coverage_ratio__lt=min_ratio,
        )
        .select_related('appraisal')
        .order_by('appraisal__collateral_coverage_ratio')[:limit]
    )
    for lr in thin_cov:
        ratio = lr.appraisal.collateral_coverage_ratio
        alerts.append({
            'severity': 'high' if ratio is not None and ratio < (min_ratio * Decimal('0.75')) else 'medium',
            'kind': 'collateral_coverage',
            'title': f'Thin collateral coverage: {lr.applicant_name}',
            'body': (
                f'{lr.loan_request_id} · coverage {float(ratio):.2f}× '
                f'(policy min {float(min_ratio):.2f}×)'
            ),
            'loan_id': lr.id,
            'action_label': 'Open loan',
            'action_url_name': 'loan_request_detail',
            'action_url_args': [lr.id],
        })
