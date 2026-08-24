"""Fraud / AML compliance desk queues."""

from __future__ import annotations

from typing import Dict, Tuple

from django.db.models import Q, QuerySet

from loans.compliance.case_engine import OPEN_STATUSES

QUEUE_CHOICES = (
    ('open', 'Open cases'),
    ('investigating', 'Investigating'),
    ('escalated', 'Escalated'),
    ('fraud', 'Fraud cases'),
    ('aml', 'AML / transaction monitoring'),
    ('blocked', 'Blocking origination / disbursement'),
)


def compliance_queue_queryset(user, queue: str) -> Tuple[QuerySet, str]:
    from loans.models import ComplianceCase

    qs = ComplianceCase.objects.select_related(
        'loan_request', 'loan_request__branch', 'assigned_to', 'opened_by',
    )
    label = dict(QUEUE_CHOICES).get(queue, 'Compliance queue')

    if queue == 'investigating':
        qs = qs.filter(status=ComplianceCase.STATUS_INVESTIGATING)
    elif queue == 'escalated':
        qs = qs.filter(status=ComplianceCase.STATUS_ESCALATED)
    elif queue == 'fraud':
        qs = qs.filter(case_type=ComplianceCase.TYPE_FRAUD, status__in=OPEN_STATUSES)
    elif queue == 'aml':
        qs = qs.filter(case_type=ComplianceCase.TYPE_AML, status__in=OPEN_STATUSES)
    elif queue == 'blocked':
        qs = qs.filter(status__in=OPEN_STATUSES).filter(
            Q(blocks_origination=True) | Q(blocks_disbursement=True),
        )
    else:
        qs = qs.filter(status__in=OPEN_STATUSES)

    return qs.order_by('-priority', '-opened_at'), label


def compliance_desk_counts(user) -> Dict[str, int]:
    from django.db.models import Q
    from loans.models import ComplianceCase

    blocked_q = Q(blocks_origination=True) | Q(blocks_disbursement=True)
    return {
        'open': ComplianceCase.objects.filter(status__in=OPEN_STATUSES).count(),
        'investigating': ComplianceCase.objects.filter(status=ComplianceCase.STATUS_INVESTIGATING).count(),
        'escalated': ComplianceCase.objects.filter(status=ComplianceCase.STATUS_ESCALATED).count(),
        'fraud': ComplianceCase.objects.filter(case_type=ComplianceCase.TYPE_FRAUD, status__in=OPEN_STATUSES).count(),
        'aml': ComplianceCase.objects.filter(case_type=ComplianceCase.TYPE_AML, status__in=OPEN_STATUSES).count(),
        'blocked': ComplianceCase.objects.filter(status__in=OPEN_STATUSES).filter(blocked_q).count(),
    }
