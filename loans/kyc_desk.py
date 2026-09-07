"""Scan/Admin + parallel KYC (CRM, Engineering, Legal) for DBE product files.

DECSI FAMILY_GENERAL keeps the existing document-auth path and is not queued here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from django.db.models import QuerySet
from django.utils import timezone

from loans.dbe_desks import (
    DESK_CRM,
    DESK_ENGINEERING,
    DESK_LEGAL,
    DESK_SCAN_ADMIN,
)
from loans.product_family import (
    FAMILY_CONSUMER,
    FAMILY_GENERAL,
    FAMILY_IDEA_EQUITY,
    FAMILY_IFB_IJARAH,
    FAMILY_IFB_MURABAHA,
    FAMILY_LEASE,
    FAMILY_PROJECT,
    FAMILY_WHOLESALE,
    resolve_product_family,
)

KYC_DESKS = (DESK_CRM, DESK_ENGINEERING, DESK_LEGAL)

DESK_ROLES = {
    DESK_SCAN_ADMIN: ('admin', 'superadmin'),
    DESK_CRM: (
        'credit_head', 'credit_loan_officer', 'loan_officer',
        'vp', 'branch_manager',
    ),
    DESK_ENGINEERING: ('engineer', 'engineering_head'),
    DESK_LEGAL: ('legal_officer',),
}

QUEUE_CHOICES = (
    ('mine', 'My desk — pending'),
    ('scan', 'Scan / Admin (online apply)'),
    ('crm', 'CRM KYC'),
    ('appraisal', 'CRM — appraisal comments'),
    ('engineering', 'Engineering technical'),
    ('legal', 'Legal pack'),
    ('cleared', 'KYC complete'),
)

# (key, label, required)
_CORE_CHECKLIST = {
    DESK_SCAN_ADMIN: [
        ('scan_quality', 'Scans are complete and readable', True),
        ('pack_complete', 'Application pack received for this product', True),
        ('identity_docs', 'Identity documents are in the pack', True),
    ],
    DESK_CRM: [
        ('identity_docs', 'Identity documents present and readable', True),
        ('identity_match', 'Name / ID matches the applicant on this file', True),
        ('source_of_funds', 'Source of funds / wealth noted', True),
        ('pep_sanctions', 'PEP / sanctions screen reviewed', True),
        ('financial_pack', 'Financial / KYC pack complete for this product', True),
    ],
    DESK_ENGINEERING: [
        ('site_or_asset', 'Site or asset evidence is on file', True),
        ('technical_pack', 'Technical pack matches this product', True),
        ('spec_or_gps', 'Specification, GPS, or BOQ attached where this product needs it', True),
    ],
    DESK_LEGAL: [
        ('legal_personality', 'Legal personality / capacity confirmed', True),
        ('title_or_authority', 'Title, mandate, or board authority on file', True),
        ('contract_ready', 'No legal blocker to contracting', True),
    ],
}

_FAMILY_EXTRA = {
    FAMILY_PROJECT: {
        DESK_CRM: [
            ('ubo', 'Beneficial owners / directors recorded', True),
        ],
        DESK_ENGINEERING: [
            ('plant_or_civil', 'Plant / civil technical note reviewed', True),
        ],
        DESK_LEGAL: [
            ('ubo_recorded', 'Beneficial owners / directors match the identity case', True),
        ],
    },
    FAMILY_LEASE: {
        DESK_ENGINEERING: [
            ('asset_spec', 'Asset specification / serial reviewed', True),
        ],
    },
    FAMILY_IFB_IJARAH: {
        DESK_ENGINEERING: [
            ('asset_spec', 'Asset specification / serial reviewed', True),
        ],
        DESK_LEGAL: [
            ('sharia_pack', 'Sharia questionnaire on file', True),
        ],
    },
    FAMILY_IFB_MURABAHA: {
        DESK_LEGAL: [
            ('sharia_pack', 'Sharia questionnaire on file', True),
        ],
    },
    FAMILY_WHOLESALE: {
        DESK_CRM: [
            ('esms_policy', 'PFI ESMS / credit policy seen', True),
            ('ubo', 'Beneficial owners / directors recorded', True),
        ],
        DESK_ENGINEERING: [
            ('portfolio_pack', 'PAR / NPL and on-lending pack seen', True),
        ],
        DESK_LEGAL: [
            ('ubo_recorded', 'Beneficial owners / directors match the identity case', True),
        ],
    },
    FAMILY_IDEA_EQUITY: {
        DESK_CRM: [
            ('cap_table', 'Cap table / start-up evidence seen', True),
            ('ubo', 'Beneficial owners / directors recorded', True),
        ],
        DESK_LEGAL: [
            ('ubo_recorded', 'Beneficial owners / directors match the identity case', True),
        ],
    },
    FAMILY_CONSUMER: {
        DESK_CRM: [
            ('employer_salary', 'Employer and salary evidence seen', True),
        ],
    },
}


class KycClearBlocked(ValueError):
    """Raised when a desk tries to clear without the required checklist."""


def kyc_applies(loan_request) -> bool:
    return resolve_product_family(loan_request) != FAMILY_GENERAL


def checklist_spec(desk: str, family: str) -> List[Tuple[str, str, bool]]:
    rows = list(_CORE_CHECKLIST.get(desk) or [])
    extra = (_FAMILY_EXTRA.get(family) or {}).get(desk) or []
    seen = {key for key, _, _ in rows}
    for item in extra:
        if item[0] not in seen:
            rows.append(item)
            seen.add(item[0])
    return rows


def complete_checklist_payload(desk: str, loan_request=None, family: str = '') -> Dict[str, bool]:
    family = family or resolve_product_family(loan_request)
    return {key: True for key, _label, _req in checklist_spec(desk, family)}


def checklist_from_post(post, desk: str, loan_request) -> Dict[str, bool]:
    family = resolve_product_family(loan_request)
    truthy = {'on', '1', 'true', 'yes'}
    out = {}
    for key, _label, _req in checklist_spec(desk, family):
        out[key] = str(post.get(f'check_{key}') or '').strip().lower() in truthy
    return out


def missing_checklist_keys(row, family: str) -> List[str]:
    saved = row.checklist or {}
    missing = []
    for key, label, required in checklist_spec(row.desk, family):
        if required and not saved.get(key):
            missing.append(label)
    return missing


def user_desk_for_kyc(user) -> Optional[str]:
    from loans.dbe_desks import user_desk_key

    key = user_desk_key(user)
    if key in (DESK_SCAN_ADMIN, DESK_CRM, DESK_ENGINEERING, DESK_LEGAL):
        return key
    role = getattr(user, 'role', None)
    if role in DESK_ROLES[DESK_ENGINEERING]:
        return DESK_ENGINEERING
    if role in DESK_ROLES[DESK_LEGAL]:
        return DESK_LEGAL
    if role in DESK_ROLES[DESK_SCAN_ADMIN]:
        return DESK_SCAN_ADMIN
    if role in DESK_ROLES[DESK_CRM]:
        return DESK_CRM
    return None


def user_can_access_kyc_desk(user) -> bool:
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if getattr(user, 'role', None) in ('admin', 'superadmin'):
        return True
    return user_desk_for_kyc(user) is not None


def user_can_work_desk(user, desk: str) -> bool:
    if not user_can_access_kyc_desk(user):
        return False
    if getattr(user, 'is_superuser', False) or getattr(user, 'role', None) in ('admin', 'superadmin'):
        return True
    mine = user_desk_for_kyc(user)
    return mine == desk


def _is_online(loan_request) -> bool:
    return getattr(loan_request, 'source_channel', '') == getattr(
        loan_request, 'SOURCE_ONLINE', 'online',
    )


def ensure_intake_screenings(loan_request) -> list:
    """Create Scan/Admin for portal files, or the three KYC packs for staff files."""
    from loans.models import CreditDeskScreening

    if loan_request is None or not kyc_applies(loan_request):
        return []
    rows = []
    if _is_online(loan_request):
        scan, _ = CreditDeskScreening.objects.get_or_create(
            loan_request=loan_request,
            stage=CreditDeskScreening.STAGE_KYC,
            desk=CreditDeskScreening.DESK_SCAN,
        )
        rows.append(scan)
        if scan.status == CreditDeskScreening.STATUS_CLEARED:
            rows.extend(_ensure_kyc_packs(loan_request))
        return rows
    return _ensure_kyc_packs(loan_request)


def _ensure_kyc_packs(loan_request) -> list:
    from loans.models import CreditDeskScreening

    created = []
    for desk in KYC_DESKS:
        row, _ = CreditDeskScreening.objects.get_or_create(
            loan_request=loan_request,
            stage=CreditDeskScreening.STAGE_KYC,
            desk=desk,
        )
        created.append(row)
    return created


def _kyc_findings(loan_request, desk: str, user) -> Dict[str, Any]:
    findings: Dict[str, Any] = {}
    if desk not in (DESK_CRM, DESK_SCAN_ADMIN):
        return findings
    try:
        from loans.services.document_auth import document_identity_findings
        findings['identity'] = document_identity_findings(loan_request)
    except Exception:
        findings['identity'] = []
    try:
        from loans.compliance.case_engine import screen_loan_and_open_case
        from loans.compliance.sanctions_screen import provider_mode
        from loans.models import SanctionsScreeningResult

        mode = provider_mode()
        findings['sanctions'] = {'provider': mode, 'ran': False, 'hit': False, 'case_id': None}
        if mode != 'off':
            case = screen_loan_and_open_case(loan_request, opened_by=user, source='kyc')
            latest = (
                SanctionsScreeningResult.objects.filter(loan_request=loan_request)
                .order_by('-id')
                .first()
            )
            findings['sanctions'] = {
                'provider': mode,
                'ran': True,
                'hit': bool(latest and latest.hit),
                'case_id': getattr(case, 'pk', None),
                'score': int(getattr(latest, 'score', 0) or 0) if latest else 0,
            }
    except Exception:
        findings['sanctions'] = {'ran': False, 'error': True, 'hit': False}
    return findings


def set_screening_status(
    loan_request,
    desk: str,
    status: str,
    user,
    note: str = '',
    checklist: Optional[Dict[str, bool]] = None,
):
    from loans.models import CreditDeskScreening

    ensure_intake_screenings(loan_request)
    row = CreditDeskScreening.objects.get(
        loan_request=loan_request,
        stage=CreditDeskScreening.STAGE_KYC,
        desk=desk,
    )
    family = resolve_product_family(loan_request)
    if checklist is not None:
        row.checklist = dict(checklist)
    if status == CreditDeskScreening.STATUS_CLEARED:
        if desk == CreditDeskScreening.DESK_SCAN:
            from loans.kyc_identity import get_identity_case, record_scan_override
            from loans.models import KycIdentityCase
            case = get_identity_case(loan_request=loan_request)
            if case is not None and case.band == KycIdentityCase.BAND_BLOCKED:
                if len((note or '').strip()) < 8:
                    raise KycClearBlocked(
                        'Identity case is blocked. Record an override note '
                        '(at least 8 characters) to clear Scan/Admin.'
                    )
                record_scan_override(case, user, note)
        missing = missing_checklist_keys(row, family)
        if missing:
            raise KycClearBlocked(
                'Tick all required KYC items before clearing: ' + '; '.join(missing[:6])
            )
        row.findings = _kyc_findings(loan_request, desk, user)
    row.status = status
    row.note = (note or '').strip()
    row.reviewed_by = user
    row.reviewed_at = timezone.now()
    row.save(update_fields=[
        'status', 'note', 'checklist', 'findings',
        'reviewed_by', 'reviewed_at', 'updated_at',
    ])
    if desk == CreditDeskScreening.DESK_SCAN and status == CreditDeskScreening.STATUS_CLEARED:
        _ensure_kyc_packs(loan_request)
    return row


def annotate_kyc_rows(loan_request, rows: Sequence) -> list:
    family = resolve_product_family(loan_request)
    identity = []
    try:
        from loans.services.document_auth import document_identity_findings
        identity = document_identity_findings(loan_request)
    except Exception:
        identity = []
    hints = {}
    try:
        from loans.kyc_identity import suggested_kyc_hints
        hints = suggested_kyc_hints(loan_request)
    except Exception:
        hints = {}
    annotated = []
    for row in rows:
        saved = row.checklist or {}
        row.ui_items = [
            {
                'key': key,
                'label': label,
                'required': required,
                'checked': bool(saved.get(key)),
                'hint': hints.get(key) or '',
            }
            for key, label, required in checklist_spec(row.desk, family)
        ]
        row.ui_findings = row.findings or {}
        row.ui_identity = identity if row.desk == DESK_CRM else []
        annotated.append(row)
    return annotated


def kyc_committee_blockers(loan_request) -> list:
    from loans.kyc_identity import identity_committee_blockers

    msgs = list(identity_committee_blockers(loan_request))
    if not kyc_applies(loan_request):
        return msgs
    ensure_intake_screenings(loan_request)
    if kyc_is_complete(loan_request):
        return msgs
    msgs.append('CRM, Engineering, and Legal must clear KYC before this file goes to committee.')
    return msgs


def kyc_is_complete(loan_request) -> bool:
    from loans.models import CreditDeskScreening

    if not kyc_applies(loan_request):
        return True
    packs = CreditDeskScreening.objects.filter(
        loan_request=loan_request,
        stage=CreditDeskScreening.STAGE_KYC,
        desk__in=KYC_DESKS,
    )
    if packs.count() < 3:
        return False
    return not packs.exclude(status=CreditDeskScreening.STATUS_CLEARED).exists()


def kyc_queue_queryset(user, queue: str) -> Tuple[QuerySet, str]:
    from loans.models import CreditDeskScreening, LoanRequest

    label = dict(QUEUE_CHOICES).get(queue, 'KYC')
    base = LoanRequest.objects.select_related('category', 'branch', 'assigned_loan_officer').order_by('-id')
    if queue == 'scan':
        qs = base.filter(
            desk_screenings__stage=CreditDeskScreening.STAGE_KYC,
            desk_screenings__desk=CreditDeskScreening.DESK_SCAN,
            desk_screenings__status=CreditDeskScreening.STATUS_PENDING,
        ).distinct()
        return qs, label
    if queue in (DESK_CRM, DESK_ENGINEERING, DESK_LEGAL):
        qs = base.filter(
            desk_screenings__stage=CreditDeskScreening.STAGE_KYC,
            desk_screenings__desk=queue,
            desk_screenings__status__in=(
                CreditDeskScreening.STATUS_PENDING,
                CreditDeskScreening.STATUS_RETURNED,
            ),
        ).distinct()
        return qs, label
    if queue == 'appraisal':
        from loans.models import AppraisalCrmRound
        qs = base.filter(
            appraisal_crm_rounds__status=AppraisalCrmRound.STATUS_WITH_CRM,
        ).distinct()
        return qs, label
    if queue == 'cleared':
        dbe = list(base.exclude(category__product_family=FAMILY_GENERAL)[:400])
        done_ids = [loan.pk for loan in dbe if kyc_is_complete(loan)]
        return base.filter(pk__in=done_ids), label
    # mine
    desk = user_desk_for_kyc(user) or DESK_CRM
    if desk == DESK_SCAN_ADMIN:
        return kyc_queue_queryset(user, 'scan')
    if desk == DESK_CRM:
        kyc_qs, _ = kyc_queue_queryset(user, DESK_CRM)
        app_qs, _ = kyc_queue_queryset(user, 'appraisal')
        return (kyc_qs | app_qs).distinct(), 'My desk — pending'
    return kyc_queue_queryset(user, desk)
