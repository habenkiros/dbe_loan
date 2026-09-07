"""Shared KYC identity case: parties, band recompute, applicant-facing gates."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from loans.services.document_extraction_defaults import _bucket_for_name
from loans.services.document_forensics import applicant_facing


def is_strict_identity_type(doc_type) -> bool:
    name = getattr(doc_type, 'name', '') or ''
    bucket = _bucket_for_name(name)
    if bucket in ('id', 'tin'):
        return True
    if getattr(doc_type, 'identity_match_strict', False):
        return True
    return False


def _related_case(obj, attr: str):
    if obj is None:
        return None
    try:
        return getattr(obj, attr)
    except ObjectDoesNotExist:
        return None
    except Exception:
        return None


def ensure_identity_case(*, loan_request=None, online_application=None):
    from loans.models import KycIdentityCase

    case = None
    if loan_request is not None:
        case = _related_case(loan_request, 'kyc_identity_case')
    if case is None and online_application is not None:
        case = getattr(online_application, 'kyc_identity_case', None)

    if case is None:
        case = KycIdentityCase.objects.create(
            loan_request=loan_request if getattr(loan_request, 'pk', None) else None,
        )
    if loan_request is not None and case.loan_request_id != loan_request.pk:
        case.loan_request = loan_request
        case.save(update_fields=['loan_request', 'updated_at'])
    if online_application is not None and getattr(online_application, 'kyc_identity_case_id', None) != case.pk:
        online_application.kyc_identity_case = case
        online_application.save(update_fields=['kyc_identity_case', 'updated_at'])

    ensure_applicant_party(case, loan_request=loan_request, online_application=online_application)
    return case


def ensure_applicant_party(case, *, loan_request=None, online_application=None):
    from loans.models import KycParty

    party = case.parties.filter(role=KycParty.ROLE_APPLICANT).first()
    name = ''
    phone = ''
    tin = ''
    if loan_request is not None:
        name = (getattr(loan_request, 'applicant_name', '') or '').strip()
        phone = (getattr(loan_request, 'phone_number', '') or '').strip()
        try:
            bi = getattr(loan_request, 'basic_info', None)
            if bi and getattr(bi, 'tin_number', ''):
                tin = (bi.tin_number or '').strip()
        except Exception:
            pass
    if online_application is not None:
        name = name or (getattr(online_application, 'applicant_name', '') or '').strip()
        phone = phone or (getattr(online_application, 'phone_number', '') or '').strip()
        if not name and getattr(online_application, 'applicant', None):
            name = (online_application.applicant.full_name or '').strip()

    if party is None:
        party = KycParty.objects.create(
            identity_case=case,
            role=KycParty.ROLE_APPLICANT,
            legal_name_en=name,
            tin=tin,
        )
        return party

    fields = []
    if name and not party.legal_name_en:
        party.legal_name_en = name
        fields.append('legal_name_en')
    if tin and not party.tin:
        party.tin = tin
        fields.append('tin')
    if fields:
        fields.append('updated_at')
        party.save(update_fields=fields)
    return party


def save_applicant_identity(
    *,
    loan_request=None,
    online_application=None,
    identity_kind: str = '',
    legal_name_en: str = '',
    legal_name_am: str = '',
    fan: str = '',
    tin: str = '',
    id_number: str = '',
    verify: bool = True,
):
    from loans.models import KycParty
    from loans.services.identity_verify import verify_party

    case = ensure_identity_case(
        loan_request=loan_request, online_application=online_application,
    )
    party = ensure_applicant_party(
        case, loan_request=loan_request, online_application=online_application,
    )
    kind = (identity_kind or '').strip() or KycParty.KIND_NATIONAL_ID
    allowed = {c[0] for c in KycParty.KIND_CHOICES}
    if kind not in allowed:
        kind = KycParty.KIND_NATIONAL_ID
    party.identity_kind = kind
    if legal_name_en:
        party.legal_name_en = legal_name_en.strip()[:255]
    if legal_name_am:
        party.legal_name_am = legal_name_am.strip()[:255]
    party.fan = (fan or '').strip()[:40]
    if tin:
        party.tin = tin.strip()[:40]
    party.id_number = (id_number or '').strip()[:80]
    party.save()
    if verify:
        verify_party(party)
    recompute_identity_case(case)
    return party


def apply_extracted_fields_to_party(party, extracted: Dict[str, Any]) -> None:
    if not party or not extracted:
        return
    fields = []
    name = (extracted.get('applicant_name') or '').strip()
    if name and not party.legal_name_en:
        party.legal_name_en = name[:255]
        fields.append('legal_name_en')
    tin = (extracted.get('tin_number') or '').strip()
    if tin and not party.tin:
        party.tin = tin[:40]
        fields.append('tin')
    gender = (extracted.get('gender') or '').strip()
    if gender and not party.gender:
        party.gender = gender[:20]
        fields.append('gender')
    if fields:
        fields.append('updated_at')
        party.save(update_fields=fields)


def identity_fields_for_party(party) -> List[str]:
    fields = ['applicant_name']
    if party is None:
        return ['applicant_name', 'phone_number', 'tin_number']
    if (party.tin or '').strip():
        fields.append('tin_number')
    if (party.fan or '').strip():
        fields.append('fan')
    if (party.id_number or '').strip():
        fields.append('id_number')
    if (party.legal_name_am or '').strip():
        fields.append('legal_name_am')
    return fields


def _doc_rows_for_case(case) -> List[Any]:
    docs: List[Any] = []
    loan = getattr(case, 'loan_request', None)
    if loan is not None:
        docs.extend(list(loan.application_documents.select_related('document_type').all()))
    app = _related_case(case, 'online_application')
    if app is not None and not docs:
        docs.extend(list(app.documents.select_related('document_type').all()))
    return docs


def recompute_identity_case(case) -> None:
    from loans.models import KycIdentityCase, KycParty, LoanRequestDocument

    if case is None:
        return
    docs = _doc_rows_for_case(case)
    parties = list(case.parties.all())
    applicant = next((p for p in parties if p.role == KycParty.ROLE_APPLICANT), None)

    blockers: List[str] = []
    reasons: List[str] = []
    scores: List[int] = []
    identity_fails = 0
    identity_ok = 0
    needs_review = 0
    unreadable = 0
    reuse = False
    provider_error = False
    provider_denied = False

    for party in parties:
        if party.verify_status in (KycParty.VERIFY_NOT_FOUND, KycParty.VERIFY_MISMATCH):
            provider_denied = True
            blockers.append(
                f'{party.get_role_display()} identity was not confirmed by Fayda/TIN.'
            )
        elif party.verify_status == KycParty.VERIFY_ERROR:
            provider_error = True
            reasons.append('provider_unconfirmed')

    for doc in docs:
        checks = getattr(doc, 'automated_checks', None) or {}
        auth = getattr(doc, 'auth_status', '') or checks.get('auth_status') or ''
        auth_score = getattr(doc, 'authenticity_score', None)
        if auth_score is None:
            auth_score = (checks.get('forensics') or {}).get('authenticity_score')
        if auth_score is not None:
            scores.append(int(auth_score))
        ident = checks.get('identity_match') or {}
        if ident:
            if ident.get('passed') is False:
                identity_fails += 1
            elif ident.get('passed') is True:
                identity_ok += 1
        facing = applicant_facing(checks) if checks else {}
        strict = is_strict_identity_type(getattr(doc, 'document_type', None))
        if facing.get('retake') and strict:
            unreadable += 1
            blockers.append(
                f'Retake required: {getattr(doc.document_type, "name", "document")}.'
            )
        if auth in (LoanRequestDocument.AUTH_REJECTED, 'rejected'):
            blockers.append(
                f'Rejected document: {getattr(doc.document_type, "name", "document")}.'
            )
        if auth in (LoanRequestDocument.AUTH_NEEDS_REVIEW, 'needs_review'):
            needs_review += 1
        if checks.get('duplicate_other') or (checks.get('forensics') or {}).get('near_duplicates'):
            reuse = True
            reasons.append('reuse_other_loan')

    avg = int(sum(scores) / len(scores)) if scores else 70
    if identity_fails:
        reasons.append('identity_mismatch')
    band = KycIdentityCase.BAND_CLEAR
    if blockers or identity_fails or provider_denied or unreadable:
        band = KycIdentityCase.BAND_BLOCKED
        if identity_fails and not any('match' in b.lower() for b in blockers):
            blockers.append('Identity on a document does not match the applicant.')
    elif needs_review or reuse or provider_error or avg < 70:
        band = KycIdentityCase.BAND_REVIEW
        if not docs:
            band = KycIdentityCase.BAND_REVIEW
        if provider_error:
            reasons.append('provider_unconfirmed')
    if not docs and not any(p.fan or p.tin or p.id_number for p in parties):
        band = KycIdentityCase.BAND_REVIEW
        avg = min(avg, 50)

    findings = dict(case.findings or {})
    findings.update({
        'recomputed_at': timezone.now().isoformat(),
        'document_count': len(docs),
        'identity_ok': identity_ok,
        'identity_fails': identity_fails,
        'needs_review': needs_review,
        'reuse': reuse,
        'reasons': sorted(set(reasons)),
        'applicant': {
            'name': getattr(applicant, 'legal_name_en', '') if applicant else '',
            'kind': getattr(applicant, 'identity_kind', '') if applicant else '',
            'verify_status': getattr(applicant, 'verify_status', '') if applicant else '',
            'fan': getattr(applicant, 'fan', '') if applicant else '',
            'tin': getattr(applicant, 'tin', '') if applicant else '',
        },
    })
    case.band = band
    case.score = avg
    case.blockers = blockers[:12]
    case.findings = findings
    case.save(update_fields=['band', 'score', 'blockers', 'findings', 'updated_at'])


def get_identity_case(loan_request=None, online_application=None):
    if loan_request is not None:
        case = _related_case(loan_request, 'kyc_identity_case')
        if case is not None:
            return case
        app = getattr(loan_request, 'online_application', None)
        if app is not None:
            return getattr(app, 'kyc_identity_case', None)
    if online_application is not None:
        return getattr(online_application, 'kyc_identity_case', None)
    return None


def identity_committee_blockers(loan_request) -> List[str]:
    case = get_identity_case(loan_request=loan_request)
    if case is None:
        return []
    from loans.models import KycIdentityCase
    if case.band != KycIdentityCase.BAND_BLOCKED:
        return []
    msgs = list(case.blockers or [])
    return msgs[:4] or ['Identity / document authentication is blocked until the pack is fixed.']


def identity_fee_blockers(application) -> List[str]:
    from loans.services.document_auth import get_document_auth_policy

    policy = get_document_auth_policy()
    if policy and not getattr(policy, 'block_fee_on_strict_identity_fail', True):
        return []
    blockers: List[str] = []
    for doc in application.documents.select_related('document_type'):
        if not is_strict_identity_type(doc.document_type):
            continue
        checks = doc.automated_checks or {}
        facing = applicant_facing({**checks, 'auth_status': doc.auth_status})
        if facing.get('block_fee') or doc.auth_status == 'rejected':
            blockers.append(
                facing.get('message')
                or f'Retake {doc.document_type.name} before continuing.'
            )
    return blockers


def suggested_kyc_hints(loan_request) -> Dict[str, str]:
    """Officer hints next to checklist ticks — does not pre-check boxes."""
    hints: Dict[str, str] = {}
    case = get_identity_case(loan_request=loan_request)
    if case is None:
        return hints
    findings = case.findings or {}
    if findings.get('identity_ok') and not findings.get('identity_fails'):
        hints['identity_match'] = 'System: name / ID on documents match this file.'
    elif findings.get('identity_fails'):
        hints['identity_match'] = 'System: identity mismatch — review before clearing.'
    applicant = findings.get('applicant') or {}
    if applicant.get('verify_status') == 'confirmed':
        hints['identity_docs'] = 'System: Fayda/TIN adapter confirmed the applicant.'
    try:
        from loans.models import SanctionsScreeningResult
        latest = (
            SanctionsScreeningResult.objects.filter(loan_request=loan_request)
            .order_by('-id')
            .first()
        )
        if latest is not None:
            if latest.hit:
                hints['pep_sanctions'] = 'System: PEP / sanctions hit — compliance case on file.'
            else:
                hints['pep_sanctions'] = 'System: no PEP / sanctions hit on last screen.'
    except Exception:
        pass
    return hints


def case_payload(loan_request) -> Optional[Dict[str, Any]]:
    case = get_identity_case(loan_request=loan_request)
    if case is None:
        return None
    parties = []
    for p in case.parties.all():
        parties.append({
            'role': p.get_role_display(),
            'name': p.legal_name_en or p.legal_name_am,
            'kind': p.get_identity_kind_display(),
            'fan': p.fan,
            'tin': p.tin,
            'id_number': p.id_number,
            'verify': p.get_verify_status_display(),
            'verify_status': p.verify_status,
            'biometric': p.get_biometric_status_display() if p.biometric_status else '',
        })
    docs = []
    loan = getattr(case, 'loan_request', None) or loan_request
    if loan is not None:
        for d in loan.application_documents.select_related('document_type')[:16]:
            docs.append({
                'name': d.document_type.name,
                'auth': d.get_auth_status_display(),
                'quality': d.quality_score,
                'authenticity': d.authenticity_score,
                'reuse': bool((d.automated_checks or {}).get('duplicate_other')),
            })
    return {
        'band': case.band,
        'band_label': case.get_band_display(),
        'score': case.score,
        'blockers': case.blockers or [],
        'findings': case.findings or {},
        'parties': parties,
        'documents': docs,
        'scan_override': (case.findings or {}).get('scan_override'),
    }


def record_scan_override(case, user, note: str) -> None:
    findings = dict(case.findings or {})
    findings['scan_override'] = {
        'note': (note or '').strip(),
        'by': getattr(user, 'pk', None),
        'username': getattr(user, 'username', ''),
        'at': timezone.now().isoformat(),
    }
    case.findings = findings
    case.save(update_fields=['findings', 'updated_at'])
