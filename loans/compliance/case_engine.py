"""Fraud / AML case workflow: open → investigate → escalate → close."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

OPEN_STATUSES = frozenset({
    'open', 'investigating', 'escalated',
})


def user_can_access_compliance_desk(user) -> bool:
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) in (
        'risk_compliance', 'auditor', 'admin', 'superadmin', 'ceo', 'credit_head',
    )


def user_can_manage_compliance_cases(user) -> bool:
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) in ('risk_compliance', 'admin', 'superadmin')


def _next_case_number() -> str:
    from loans.models import ComplianceCase
    prefix = f'FC-{timezone.now().strftime("%Y%m")}-'
    last = (
        ComplianceCase.objects.filter(case_number__startswith=prefix)
        .order_by('-case_number')
        .values_list('case_number', flat=True)
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(last.rsplit('-', 1)[-1]) + 1
        except ValueError:
            seq = ComplianceCase.objects.count() + 1
    return f'{prefix}{seq:04d}'


def _log_event(case, *, event_type: str, user=None, notes: str = '', payload: Optional[dict] = None):
    from loans.models import ComplianceCaseEvent
    ComplianceCaseEvent.objects.create(
        case=case,
        event_type=event_type,
        notes=(notes or '')[:4000],
        recorded_by=user,
        payload=payload or {},
    )


def open_case(
    *,
    case_type: str,
    source: str,
    summary: str,
    loan_request=None,
    document=None,
    opened_by=None,
    priority: str = 'medium',
    metadata: Optional[Dict[str, Any]] = None,
    blocks_origination: bool = True,
    blocks_disbursement: bool = True,
    fingerprint: str = '',
) -> Optional[object]:
    """
    Open a compliance case. Skips duplicate open cases with same fingerprint on same loan.
    Returns case or None if deduped / disabled.
    """
    from loans.compliance.policy import get_compliance_policy
    from loans.models import ComplianceCase

    policy = get_compliance_policy()
    if not getattr(policy, 'compliance_engine_enabled', True):
        return None

    meta = dict(metadata or {})
    fp = (fingerprint or meta.get('fingerprint') or '').strip()
    if loan_request and fp:
        for existing in ComplianceCase.objects.filter(
            loan_request=loan_request,
            source=source,
            status__in=OPEN_STATUSES,
        ).order_by('-opened_at')[:20]:
            if (existing.metadata or {}).get('fingerprint') == fp:
                return existing

    with transaction.atomic():
        case = ComplianceCase.objects.create(
            case_number=_next_case_number(),
            case_type=case_type,
            status=ComplianceCase.STATUS_OPEN,
            priority=priority,
            source=source,
            summary=(summary or '')[:500],
            loan_request=loan_request,
            document=document,
            opened_by=opened_by,
            assigned_to=opened_by if user_can_manage_compliance_cases(opened_by) else None,
            blocks_origination=blocks_origination,
            blocks_disbursement=blocks_disbursement,
            metadata={**meta, **({'fingerprint': fp} if fp else {})},
        )
        _log_event(
            case,
            event_type='opened',
            user=opened_by,
            notes=summary,
            payload={'source': source, 'priority': priority},
        )
    try:
        _notify_case_opened(case)
    except Exception:
        logger.exception('Compliance case notification failed for %s', case.case_number)
    return case


def transition_case(case, user, new_status: str, *, note: str = '') -> object:
    from loans.models import ComplianceCase

    old = case.status
    if old == new_status:
        return case
    valid = {c[0] for c in ComplianceCase.STATUS_CHOICES}
    if new_status not in valid:
        raise ValueError('Invalid case status.')
    case.status = new_status
    if new_status in (ComplianceCase.STATUS_CLOSED, ComplianceCase.STATUS_FALSE_POSITIVE):
        case.closed_at = timezone.now()
        case.closed_by = user
        case.resolution_note = (note or case.resolution_note or '')[:2000]
    case.save(update_fields=[
        'status', 'closed_at', 'closed_by', 'resolution_note', 'updated_at',
    ])
    _log_event(
        case,
        event_type='status_change',
        user=user,
        notes=note or f'{old} → {new_status}',
        payload={'from': old, 'to': new_status},
    )
    return case


def assign_case(case, user, assignee) -> object:
    case.assigned_to = assignee
    case.save(update_fields=['assigned_to', 'updated_at'])
    _log_event(
        case,
        event_type='assignment',
        user=user,
        notes=f'Assigned to {getattr(assignee, "username", assignee)}',
        payload={'assignee_id': getattr(assignee, 'pk', None)},
    )
    return case


def add_case_note(case, user, note: str) -> None:
    note = (note or '').strip()
    if len(note) < 3:
        raise ValueError('Note too short.')
    _log_event(case, event_type='note', user=user, notes=note)


def open_cases_for_loan(loan_request, *, open_only: bool = True):
    from loans.models import ComplianceCase
    qs = ComplianceCase.objects.filter(loan_request=loan_request)
    if open_only:
        qs = qs.filter(status__in=OPEN_STATUSES)
    return qs.order_by('-opened_at')


def compliance_blockers(loan_request) -> List[str]:
    """Human-readable blockers from open fraud/AML cases."""
    blockers = []
    for case in open_cases_for_loan(loan_request):
        if case.blocks_origination or case.blocks_disbursement:
            blockers.append(
                f'{case.get_case_type_display()} case {case.case_number} ({case.get_status_display()}): '
                f'{case.summary[:120]}'
            )
    return blockers


def origination_compliance_blocked(loan_request) -> bool:
    from loans.compliance.policy import get_compliance_policy
    policy = get_compliance_policy()
    if not getattr(policy, 'require_compliance_clear_before_committee', False):
        return False
    return open_cases_for_loan(loan_request).filter(blocks_origination=True).exists()


def disbursement_compliance_blocked(loan_request) -> bool:
    from loans.compliance.policy import get_compliance_policy
    policy = get_compliance_policy()
    if not getattr(policy, 'require_compliance_clear_before_disbursement', True):
        return False
    return open_cases_for_loan(loan_request).filter(blocks_disbursement=True).exists()


def maybe_open_banking_case(loan_request, appraisal, assessment: Dict[str, Any], *, opened_by=None):
    from loans.compliance.policy import get_compliance_policy
    from loans.models import ComplianceCase, TransactionAnomalyAssessment

    policy = get_compliance_policy()
    if not policy.auto_open_banking_anomaly:
        return None

    score = int(assessment.get('score') or 0)
    TransactionAnomalyAssessment.objects.create(
        loan_request=loan_request,
        appraisal=appraisal,
        score=score,
        risk_band=assessment.get('risk_band') or 'low',
        signals=assessment.get('signals') or [],
        provider=(appraisal.banking_behavior or {}).get('provider', ''),
        metadata={'tx_count': assessment.get('tx_count')},
    )
    if score < int(policy.anomaly_score_threshold or 60):
        return None

    priority = 'critical' if score >= 75 else 'high' if score >= 55 else 'medium'
    top = (assessment.get('signals') or [])[:3]
    detail = '; '.join(s.get('label', '') for s in top if s.get('label'))
    return open_case(
        case_type=ComplianceCase.TYPE_AML,
        source=ComplianceCase.SOURCE_BANKING,
        summary=f'Transaction anomaly score {score}/100 — {detail or "review banking behavior"}',
        loan_request=loan_request,
        opened_by=opened_by,
        priority=priority,
        metadata={
            'fingerprint': f'banking:{loan_request.pk}:{score // 10}',
            'anomaly_score': score,
            'risk_band': assessment.get('risk_band'),
            'signals': assessment.get('signals'),
        },
        fingerprint=f'banking:{loan_request.pk}',
    )


def maybe_open_document_case(document, *, duplicate_other: bool = False, suspicious: bool = False, opened_by=None):
    from loans.compliance.policy import get_compliance_policy
    from loans.models import ComplianceCase, LoanRequestDocument

    policy = get_compliance_policy()
    loan = document.loan_request
    if duplicate_other and policy.auto_open_document_duplicate:
        return open_case(
            case_type=ComplianceCase.TYPE_FRAUD,
            source=ComplianceCase.SOURCE_DOCUMENT,
            summary=f'Duplicate document fingerprint on another loan — {document.document_type.name}',
            loan_request=loan,
            document=document,
            opened_by=opened_by,
            priority='high',
            metadata={
                'fingerprint': f'doc_dup:{document.file_sha256}',
                'sha256': document.file_sha256,
                'document_type': document.document_type.name,
            },
            fingerprint=f'doc_dup:{document.file_sha256}',
        )
    if suspicious and policy.auto_open_document_suspicious:
        return open_case(
            case_type=ComplianceCase.TYPE_FRAUD,
            source=ComplianceCase.SOURCE_DOCUMENT,
            summary=f'Suspicious document flagged — {document.document_type.name}',
            loan_request=loan,
            document=document,
            opened_by=opened_by,
            priority='high',
            metadata={'fingerprint': f'doc_susp:{document.pk}'},
            fingerprint=f'doc_susp:{document.pk}',
        )
    if document.auth_status == LoanRequestDocument.AUTH_NEEDS_REVIEW and duplicate_other:
        return None
    return None


def maybe_open_sanctions_case(
    loan_request,
    screening_result: Dict[str, Any],
    *,
    opened_by=None,
    source: Optional[str] = None,
) -> Optional[object]:
    """Open a Sanctions/PEP case when screening hits and policy allows."""
    from loans.compliance.policy import get_compliance_policy
    from loans.compliance.sanctions_screen import persist_screening
    from loans.models import ComplianceCase

    policy = get_compliance_policy()
    match_types = {
        str(t).lower() for t in (screening_result.get('match_types') or [])
    }
    matches = screening_result.get('matches') or []
    for m in matches:
        if m.get('match_type'):
            match_types.add(str(m['match_type']).lower())

    wants_sanctions = bool(match_types & {'sanctions', 'sanction', 'ofac'})
    wants_pep = bool(match_types & {'pep', 'politically_exposed'})
    if not screening_result.get('hit'):
        persist_screening(loan_request, screening_result, opened_case=None)
        return None

    open_sanctions = wants_sanctions and getattr(policy, 'auto_open_sanctions_hit', True)
    open_pep = wants_pep and getattr(policy, 'auto_open_pep_hit', True)
    # Unknown hit type: treat as sanctions when either auto flag is on
    if not wants_sanctions and not wants_pep:
        open_sanctions = getattr(policy, 'auto_open_sanctions_hit', True)

    if not (open_sanctions or open_pep):
        persist_screening(loan_request, screening_result, opened_case=None)
        return None

    labels = []
    if wants_pep:
        labels.append('PEP')
    if wants_sanctions or not wants_pep:
        labels.append('sanctions')
    label = '/'.join(dict.fromkeys(labels)) or 'watchlist'
    top = matches[0] if matches else {}
    list_name = top.get('list_name') or 'watchlist'
    matched = top.get('matched_name') or (screening_result.get('subject') or {}).get('name') or 'subject'
    score = int(screening_result.get('score') or top.get('score') or 0)
    src = source or ComplianceCase.SOURCE_NAME_SCREEN
    case = open_case(
        case_type=ComplianceCase.TYPE_SANCTIONS,
        source=src,
        summary=f'{label.title()} screening hit — {matched} on {list_name} (score {score})',
        loan_request=loan_request,
        opened_by=opened_by,
        priority='critical' if score >= 90 or wants_sanctions else 'high',
        metadata={
            'fingerprint': f'sanctions:{loan_request.pk}:{_normalize_fp(matched)}',
            'screening': {
                'score': score,
                'match_types': sorted(match_types),
                'matches': matches[:10],
                'provider': screening_result.get('provider'),
            },
        },
        fingerprint=f'sanctions:{loan_request.pk}',
    )
    persist_screening(loan_request, screening_result, opened_case=case)
    return case


def _normalize_fp(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', (value or '').lower())[:40]


def screen_loan_and_open_case(
    loan_request,
    *,
    opened_by=None,
    source: Optional[str] = None,
) -> Optional[object]:
    """Run sanctions/PEP screen and open a case on hit. Safe no-op when provider off."""
    from loans.compliance.sanctions_screen import provider_mode, screen_loan_request

    if provider_mode() == 'off':
        return None
    try:
        result = screen_loan_request(loan_request)
    except Exception:
        logger.exception('Sanctions screen failed for loan %s', getattr(loan_request, 'pk', None))
        return None
    return maybe_open_sanctions_case(
        loan_request, result, opened_by=opened_by, source=source,
    )


def _notify_case_opened(case) -> None:
    from django.urls import reverse
    from loans.models import CustomUser, LoanNotification
    from loans.services.notifications import notify_users

    users = list(
        CustomUser.objects.filter(role='risk_compliance', is_active=True)[:8]
    )
    if not users:
        return
    lr = case.loan_request
    ref = lr.loan_request_id if lr else '—'
    url = reverse('compliance_case_detail', args=[case.pk])
    notify_users(
        users,
        kind=LoanNotification.KIND_COMPLIANCE_CASE_OPENED,
        title=f'Compliance case {case.case_number}',
        message=f'{case.get_case_type_display()} · {case.summary[:200]} (loan {ref})',
        loan_request=lr,
        url=url,
    )
