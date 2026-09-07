"""Shared DFI post-book: named rehab path + origination SLA.

Not a product engine. DECSI general files are not forced onto a stage.
SLA is informational — not a committee gate. CBS still posts money.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from django.db.models import Q
from django.utils import timezone

from loans.models import LoanAppeal, RehabCase, RehabEvent


TARGET_DAYS = 45

FORECLOSURE_FROM = {
    RehabCase.STAGE_RESTRUCTURE,
    RehabCase.STAGE_TA,
    RehabCase.STAGE_RECOVER,
}

SLA_STAGES = (
    ('screening', 'Screening'),
    ('technical', 'Technical'),
    ('appraisal', 'Appraisal'),
    ('review', 'Review'),
    ('committee', 'Committee'),
    ('legal', 'Legal'),
    ('first_release', 'First equity / loan release'),
)


def get_rehab_case(loan):
    try:
        return loan.rehab
    except RehabCase.DoesNotExist:
        return None


def first_release_at(loan):
    if getattr(loan, 'disbursed_at', None):
        return loan.disbursed_at
    first = (
        loan.disbursement_tranches.filter(disbursed_at__isnull=False)
        .order_by('disbursed_at')
        .first()
    )
    return first.disbursed_at if first else None


def technical_at(loan):
    """Plant desks all cleared → latest review time. General files skip this rung."""
    from django.core.exceptions import ObjectDoesNotExist

    try:
        profile = loan.project_profile
    except ObjectDoesNotExist:
        profile = None
    if profile is None:
        return None
    reviews = list(profile.technical_reviews.all())
    if not reviews:
        return None
    if any(r.status != r.STATUS_CLEARED or not r.reviewed_at for r in reviews):
        return None
    return max(r.reviewed_at for r in reviews)


def _committee_at(loan):
    return getattr(loan, 'committee_decided_at', None) or getattr(
        loan, 'submitted_to_committee_at', None,
    )


def _stage_at(loan, key):
    mapping = {
        'screening': getattr(loan, 'date_requested', None),
        'technical': technical_at(loan),
        'appraisal': getattr(loan, 'appraisal_completed_at', None),
        'review': getattr(loan, 'risk_reviewed_at', None),
        'committee': _committee_at(loan),
        'legal': getattr(loan, 'legal_cleared_at', None),
        'first_release': first_release_at(loan),
    }
    return mapping.get(key)


def sla_clock(loan) -> Dict[str, Any]:
    start = getattr(loan, 'date_requested', None)
    released = first_release_at(loan)
    end = released or timezone.now()
    elapsed = 0
    if start:
        elapsed = max(0, (end - start).days)
    late = elapsed > TARGET_DAYS
    if released and late:
        status = 'released_late'
    elif released:
        status = 'released_on_time'
    elif late:
        status = 'breached'
    else:
        status = 'on_track'
    return {
        'target_days': TARGET_DAYS,
        'elapsed_days': elapsed,
        'breached': late and released is None,
        'late': late,
        'status': status,
        'status_label': {
            'on_track': 'On track',
            'breached': 'SLA breach',
            'released_late': 'Released late',
            'released_on_time': 'Released on time',
        }[status],
        'first_release_at': released,
        'stages': [
            {'key': key, 'label': label, 'at': _stage_at(loan, key)}
            for key, label in SLA_STAGES
        ],
    }


def insurance_overdue(loan) -> List:
    today = timezone.localdate()
    return list(
        loan.insurance_policies.filter(expires_on__isnull=False, expires_on__lt=today)
    )


def revaluation_overdue(loan) -> List:
    today = timezone.localdate()
    return list(
        loan.revaluations.filter(completed_on__isnull=True, due_on__lt=today)
    )


def postbook_summary(loan) -> Dict[str, Any]:
    case = get_rehab_case(loan)
    open_appeals = 0
    if loan.pk:
        open_appeals = loan.appeals.filter(status=LoanAppeal.STATUS_OPEN).count()
    return {
        'sla': sla_clock(loan),
        'has_rehab': case is not None,
        'rehab_stage': case.stage if case else None,
        'rehab_stage_label': case.get_stage_display() if case else None,
        'insurance_overdue': insurance_overdue(loan) if loan.pk else [],
        'revaluation_overdue': revaluation_overdue(loan) if loan.pk else [],
        'open_appeals': open_appeals,
    }


def postbook_brief(loan) -> Dict[str, Any]:
    summary = postbook_summary(loan)
    sla = summary['sla']
    return {
        'sla_days': sla['elapsed_days'],
        'sla_target': sla['target_days'],
        'sla_status': sla['status'],
        'rehab_stage': summary['rehab_stage'],
        'open_appeals': summary['open_appeals'],
    }


def can_move_rehab(current: Optional[str], target: str) -> Tuple[bool, str]:
    valid = {k for k, _ in RehabCase.STAGE_CHOICES}
    if target not in valid:
        return False, 'Unknown rehabilitation stage.'
    if not current or current == target:
        return True, ''
    if target == RehabCase.STAGE_CLOSED:
        return True, ''
    if current == RehabCase.STAGE_FORECLOSURE and target != RehabCase.STAGE_CLOSED:
        return False, 'Foreclosure only closes. It does not move backward.'
    if target == RehabCase.STAGE_FORECLOSURE:
        if current in FORECLOSURE_FROM:
            return True, ''
        return False, (
            'Foreclosure is last. Restructure, technical assistance, '
            'or recover must come first.'
        )
    return True, ''


def set_rehab_stage(loan, stage: str, user, note: str = ''):
    current = None
    case = get_rehab_case(loan)
    if case is not None:
        current = case.stage
    ok, err = can_move_rehab(current, stage)
    if not ok:
        return None, err
    if case is None:
        case = RehabCase.objects.create(
            loan_request=loan, stage=stage, note=note or '', updated_by=user,
        )
    else:
        case.stage = stage
        if note:
            case.note = note
        case.updated_by = user
        case.save(update_fields=['stage', 'note', 'updated_by', 'updated_at'])
    RehabEvent.objects.create(
        case=case,
        from_stage=current or '',
        to_stage=stage,
        note=note or '',
        recorded_by=user,
    )
    return case, None


def ensure_rehab_stage(loan, stage: str, user, note: str = ''):
    """Open a case or advance, but never downgrade a later rescue stage."""
    case = get_rehab_case(loan)
    if case is None:
        return set_rehab_stage(loan, stage, user, note)
    order = list(RehabCase.STAGE_ORDER)
    try:
        if order.index(stage) <= order.index(case.stage):
            return case, None
    except ValueError:
        return case, None
    return set_rehab_stage(loan, stage, user, note)


def sla_breach_q():
    cutoff = timezone.now() - timedelta(days=TARGET_DAYS)
    return Q(date_requested__lt=cutoff, disbursed_at__isnull=True)
