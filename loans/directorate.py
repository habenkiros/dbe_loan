"""Named Appraisal / ITS / MIS inboxes. Queues only — no new loan models."""

from __future__ import annotations

from datetime import timedelta
from typing import Sequence, Tuple

from django.db.models import Count, Max, Q, QuerySet
from django.utils import timezone

from loans.dbe_desks import DESK_APPRAISAL, DESK_ITS, DESK_MIS, user_desk_key
from loans.kyc_desk import KYC_DESKS, kyc_queue_queryset, scope_kyc_queryset
from loans.product_family import FAMILY_GENERAL, FAMILY_WHOLESALE
from loans.rehab import TARGET_DAYS

APPRAISAL_QUEUES = (
    ('kyc_open', 'KYC incomplete'),
    ('desk_blockers', 'Product desk blockers'),
    ('with_crm', 'CRM comment rounds'),
    ('ready', 'Ready for committee'),
)

ITS_QUEUES = (
    ('scan', 'Online apply — Scan pending'),
    ('cbs_failed', 'CBS booking failed'),
    ('portal_stuck', 'Portal stuck / not queued'),
)

MIS_QUEUES = (
    ('funds', 'Tagged financing funds'),
    ('wholesale', 'Wholesale / PFI files'),
    ('utilization', 'Utilization overdue'),
    ('rehab', 'Origination SLA'),
)

QUEUES = {
    DESK_APPRAISAL: APPRAISAL_QUEUES,
    DESK_ITS: ITS_QUEUES,
    DESK_MIS: MIS_QUEUES,
}

DESK_TITLES = {
    DESK_APPRAISAL: 'Appraisal Directorate',
    DESK_ITS: 'ITS Directorate',
    DESK_MIS: 'PM & MIS Directorate',
}

DESK_ROLES = {
    DESK_APPRAISAL: (
        'credit_head', 'credit_loan_officer', 'loan_officer',
        'vp', 'branch_manager',
    ),
    DESK_ITS: ('vp_it',),
    DESK_MIS: ('finance_manager', 'credit_head', 'auditor'),
}

ROW_LOAN = 'loan'
ROW_APPLICATION = 'application'

_ENGINE_SCAN_CAP = 400


def user_can_access_directorate(user, desk: str) -> bool:
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False) or getattr(user, 'role', None) in (
        'admin', 'superadmin',
    ):
        return True
    if user_desk_key(user) == desk:
        return True
    return getattr(user, 'role', None) in DESK_ROLES.get(desk, ())


def _loan_base() -> QuerySet:
    from loans.models import LoanRequest

    return LoanRequest.objects.select_related(
        'category', 'branch', 'assigned_loan_officer', 'financing_fund',
    ).order_by('-id')


def _dbe_files() -> QuerySet:
    return _loan_base().exclude(category__product_family=FAMILY_GENERAL)


def _kyc_cleared_q() -> Q:
    from loans.models import CreditDeskScreening

    return Q(
        desk_screenings__stage=CreditDeskScreening.STAGE_KYC,
        desk_screenings__desk__in=KYC_DESKS,
        desk_screenings__status=CreditDeskScreening.STATUS_CLEARED,
    )


def _with_kyc_cleared_count(qs: QuerySet) -> QuerySet:
    return qs.annotate(
        kyc_cleared=Count('desk_screenings', filter=_kyc_cleared_q(), distinct=True),
    )


def _open_committee_q() -> Q:
    from loans.models import LoanRequest

    return Q(
        committee_status__in=(
            LoanRequest.COMMITTEE_NOT_SUBMITTED,
            LoanRequest.COMMITTEE_RETURNED,
            LoanRequest.COMMITTEE_PENDED,
        ),
    )


def _engine_has_blockers(loan) -> bool:
    try:
        from loans.engines import get_engine
        return bool(get_engine(loan).committee_blockers())
    except Exception:
        return False


def _split_by_engine_blockers(qs: QuerySet, want_blockers: bool) -> List:
    rows = list(qs[:_ENGINE_SCAN_CAP])
    matched = [loan for loan in rows if _engine_has_blockers(loan) is want_blockers]
    return matched


def appraisal_queryset(queue: str, user=None) -> Tuple[Sequence, str, str]:
    label = dict(APPRAISAL_QUEUES).get(queue, 'Appraisal')
    if queue == 'with_crm':
        qs, _ = kyc_queue_queryset(user, 'appraisal')
        return qs, label, ROW_LOAN
    base = _with_kyc_cleared_count(scope_kyc_queryset(user, _dbe_files()))
    if queue == 'kyc_open':
        return base.filter(kyc_cleared__lt=3), label, ROW_LOAN
    open_files = base.filter(kyc_cleared__gte=3).filter(_open_committee_q())
    if queue == 'desk_blockers':
        return _split_by_engine_blockers(open_files, True), label, ROW_LOAN
    if queue == 'ready':
        from loans.models import LoanRequest
        pending = scope_kyc_queryset(user, _dbe_files()).filter(
            committee_status=LoanRequest.COMMITTEE_PENDING,
        )
        ready = _split_by_engine_blockers(open_files, False)
        pending_ids = {loan.pk for loan in pending[:_ENGINE_SCAN_CAP]}
        merged = [loan for loan in ready if loan.pk not in pending_ids] + list(pending[:50])
        return merged, label, ROW_LOAN
    return base.filter(kyc_cleared__lt=3), label, ROW_LOAN


def its_queryset(queue: str) -> Tuple[Sequence, str, str]:
    label = dict(ITS_QUEUES).get(queue, 'ITS')
    from loans.models import LoanRequest

    if queue == 'scan':
        qs, _ = kyc_queue_queryset(None, 'scan')
        return qs, label, ROW_LOAN
    if queue == 'cbs_failed':
        qs = _loan_base().filter(cbs_booking_status=LoanRequest.CBS_BOOK_FAILED)
        return qs, label, ROW_LOAN
    # portal_stuck
    from applicant_portal.models import OnlineApplication

    cutoff = timezone.now() - timedelta(days=7)
    apps = (
        OnlineApplication.objects.filter(
            Q(status=OnlineApplication.STATUS_SUBMITTED, loan_request__isnull=True)
            | Q(status=OnlineApplication.STATUS_PAYMENT, updated_at__lt=cutoff)
        )
        .select_related('applicant', 'category', 'branch')
        .order_by('-updated_at')
    )
    return apps, label, ROW_APPLICATION


def mis_queryset(queue: str) -> Tuple[Sequence, str, str]:
    label = dict(MIS_QUEUES).get(queue, 'MIS')
    from loans.models import LoanRequest

    if queue == 'funds':
        return _loan_base().filter(financing_fund__isnull=False), label, ROW_LOAN
    if queue == 'wholesale':
        return _loan_base().filter(category__product_family=FAMILY_WHOLESALE), label, ROW_LOAN
    if queue == 'utilization':
        cutoff = timezone.localdate() - timedelta(days=90)
        qs = (
            _loan_base()
            .filter(category__product_family=FAMILY_WHOLESALE)
            .filter(
                disbursement_status__in=(
                    LoanRequest.DISBURSE_PARTIAL,
                    LoanRequest.DISBURSE_DISBURSED,
                ),
            )
            .annotate(last_util=Max('pfi_profile__utilization_reports__as_of'))
            .filter(Q(last_util__isnull=True) | Q(last_util__lt=cutoff))
        )
        return qs, label, ROW_LOAN
    # rehab / origination SLA
    cutoff = timezone.now() - timedelta(days=TARGET_DAYS)
    qs = (
        _loan_base()
        .filter(date_requested__lt=cutoff, disbursed_at__isnull=True)
        .exclude(
            disbursement_status__in=(
                LoanRequest.DISBURSE_PARTIAL,
                LoanRequest.DISBURSE_DISBURSED,
            ),
        )
        .exclude(committee_status=LoanRequest.COMMITTEE_DECLINED)
    )
    return qs, label, ROW_LOAN


def directorate_queue(desk: str, queue: str, user=None) -> Tuple[Sequence, str, str, Sequence]:
    choices = QUEUES.get(desk) or APPRAISAL_QUEUES
    valid = {key for key, _ in choices}
    if queue not in valid:
        queue = choices[0][0]
    if desk == DESK_ITS:
        rows, label, kind = its_queryset(queue)
    elif desk == DESK_MIS:
        rows, label, kind = mis_queryset(queue)
    else:
        rows, label, kind = appraisal_queryset(queue, user)
    return rows, label, kind, choices


def default_queue(desk: str) -> str:
    return (QUEUES.get(desk) or APPRAISAL_QUEUES)[0][0]


def counts_for(desk: str, user=None) -> dict:
    out = {}
    for key, _ in QUEUES.get(desk) or ():
        rows, _label, _kind, _ = directorate_queue(desk, key, user)
        if hasattr(rows, 'count') and not isinstance(rows, list):
            out[key] = rows.count()
        else:
            out[key] = len(rows)
    return out
