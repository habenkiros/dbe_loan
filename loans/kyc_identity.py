"""Shared KYC identity case: parties, band recompute, applicant-facing gates."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from loans.product_family import (
    FAMILY_IDEA_EQUITY,
    FAMILY_PROJECT,
    FAMILY_WHOLESALE,
)
from loans.services.document_extraction_defaults import _bucket_for_name
from loans.services.document_forensics import applicant_facing

ENTITY_PARTY_FAMILIES = {FAMILY_PROJECT, FAMILY_WHOLESALE, FAMILY_IDEA_EQUITY}
RELATED_ROLES = ('director', 'ubo', 'guarantor', 'spouse')


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


def _parse_share(value) -> Optional[Any]:
    from decimal import Decimal, InvalidOperation

    if value is None or value == '':
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if parsed < 0 or parsed > 100:
        return None
    return parsed


def _parse_date(value):
    from datetime import datetime

    text = (value or '').strip() if not hasattr(value, 'year') else ''
    if hasattr(value, 'year') and value:
        return value
    if not text:
        return None
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def needs_related_parties(obj) -> bool:
    if obj is None:
        return False
    cat = getattr(obj, 'category', None)
    if cat is None:
        loan = getattr(obj, 'loan_request', None)
        cat = getattr(loan, 'category', None) if loan is not None else None
    family = getattr(cat, 'product_family', None) or ''
    if family in ENTITY_PARTY_FAMILIES:
        return True
    mode = getattr(cat, 'appraisal_mode', None) or ''
    return mode == 'corporate'


def related_role_choices():
    from loans.models import KycParty
    return [c for c in KycParty.ROLE_CHOICES if c[0] in RELATED_ROLES]


def party_completeness(case) -> Dict[str, Any]:
    from loans.models import KycParty

    parties = list(
        KycParty.objects.filter(identity_case_id=case.pk)
    ) if case is not None and getattr(case, 'pk', None) else []
    related = [p for p in parties if p.role != KycParty.ROLE_APPLICANT]
    directors = [p for p in related if p.role == KycParty.ROLE_DIRECTOR]
    ubos = [p for p in related if p.role == KycParty.ROLE_UBO]
    guarantors = [p for p in related if p.role == KycParty.ROLE_GUARANTOR]
    share = sum((p.share_percent or 0) for p in related if p.role in (
        KycParty.ROLE_UBO, KycParty.ROLE_DIRECTOR,
    ))
    complete = bool(directors or ubos)
    return {
        'complete': complete,
        'related_count': len(related),
        'directors': len(directors),
        'ubos': len(ubos),
        'guarantors': len(guarantors),
        'share_percent': float(share) if share else 0,
    }


def _id_portrait_bytes(case) -> Tuple[bytes, str]:
    for doc in _doc_rows_for_case(case):
        dt = getattr(doc, 'document_type', None)
        bucket = _bucket_for_name(getattr(dt, 'name', '') or '')
        if bucket != 'id' and not is_strict_identity_type(dt):
            continue
        if bucket == 'tin':
            continue
        f = getattr(doc, 'file', None)
        if f is None or not getattr(f, 'name', ''):
            continue
        try:
            f.open('rb')
            raw = f.read()
            f.seek(0)
        except Exception:
            continue
        ext = f.name.rsplit('.', 1)[-1].lower() if '.' in f.name else 'jpg'
        if raw:
            return raw, ext
    return b'', ''


def save_applicant_selfie(
    *,
    loan_request=None,
    online_application=None,
    uploaded_file,
):
    from django.core.files.base import ContentFile
    from loans.services.document_auth import _read_upload_bytes
    from loans.services.identity_verify import verify_biometric

    case = ensure_identity_case(
        loan_request=loan_request, online_application=online_application,
    )
    party = ensure_applicant_party(
        case, loan_request=loan_request, online_application=online_application,
    )
    raw = _read_upload_bytes(uploaded_file) if uploaded_file else b''
    if not raw:
        return party
    name = getattr(uploaded_file, 'name', '') or 'selfie.jpg'
    party.selfie.save(name, ContentFile(raw), save=False)
    party.save(update_fields=['selfie', 'updated_at'])
    id_raw, id_ext = _id_portrait_bytes(case)
    verify_biometric(
        party,
        selfie_bytes=raw,
        selfie_filename=name,
        id_portrait_bytes=id_raw,
        id_ext=id_ext,
    )
    recompute_identity_case(case)
    return party


def save_related_party(
    *,
    loan_request=None,
    online_application=None,
    role: str = '',
    legal_name_en: str = '',
    legal_name_am: str = '',
    identity_kind: str = '',
    fan: str = '',
    tin: str = '',
    id_number: str = '',
    share_percent=None,
    capacity: str = '',
    date_of_birth=None,
    party_id=None,
    verify: bool = True,
):
    from loans.models import KycParty
    from loans.services.identity_verify import verify_party

    case = ensure_identity_case(
        loan_request=loan_request, online_application=online_application,
    )
    role = (role or '').strip() or KycParty.ROLE_UBO
    if role not in RELATED_ROLES:
        role = KycParty.ROLE_UBO
    party = None
    if party_id:
        party = case.parties.filter(pk=party_id).exclude(role=KycParty.ROLE_APPLICANT).first()
    if party is None:
        party = KycParty(identity_case=case, role=role)
    else:
        party.role = role
    kind = (identity_kind or '').strip() or KycParty.KIND_NATIONAL_ID
    allowed = {c[0] for c in KycParty.KIND_CHOICES}
    if kind not in allowed:
        kind = KycParty.KIND_NATIONAL_ID
    party.identity_kind = kind
    party.legal_name_en = (legal_name_en or '').strip()[:255]
    party.legal_name_am = (legal_name_am or '').strip()[:255]
    party.fan = (fan or '').strip()[:40]
    party.tin = (tin or '').strip()[:40]
    party.id_number = (id_number or '').strip()[:80]
    party.capacity = (capacity or '').strip()[:80]
    party.share_percent = _parse_share(share_percent)
    parsed_dob = _parse_date(date_of_birth)
    if parsed_dob:
        party.date_of_birth = parsed_dob
    party.save()
    if verify and (party.fan or party.tin or party.id_number):
        verify_party(party)
    recompute_identity_case(case)
    return party


def delete_related_party(*, loan_request=None, online_application=None, party_id) -> bool:
    from loans.models import KycParty

    case = get_identity_case(loan_request=loan_request, online_application=online_application)
    if case is None or not party_id:
        return False
    deleted, _ = case.parties.filter(pk=party_id).exclude(role=KycParty.ROLE_APPLICANT).delete()
    if deleted:
        recompute_identity_case(case)
    return bool(deleted)


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
    parties = list(KycParty.objects.filter(identity_case_id=case.pk).order_by('id'))
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
    biometric_failed = False
    biometric_hard_fail = False

    for party in parties:
        if party.verify_status in (KycParty.VERIFY_NOT_FOUND, KycParty.VERIFY_MISMATCH):
            provider_denied = True
            blockers.append(
                f'{party.get_role_display()} identity was not confirmed by Fayda/TIN.'
            )
        elif party.verify_status == KycParty.VERIFY_ERROR:
            provider_error = True
            reasons.append('provider_unconfirmed')
        if party.biometric_status == KycParty.BIOMETRIC_FAILED:
            biometric_failed = True
            score_val = float(party.face_match_score or 0)
            if score_val < 40:
                biometric_hard_fail = True
                blockers.append(
                    f'{party.get_role_display()} face match failed.'
                )
            else:
                reasons.append('biometric_review')
        elif party.biometric_status == KycParty.BIOMETRIC_PENDING:
            reasons.append('biometric_pending')

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
    ubo = party_completeness(case)
    loan = getattr(case, 'loan_request', None)
    app = _related_case(case, 'online_application')
    needs_ubo = needs_related_parties(loan) or needs_related_parties(app)
    if needs_ubo and not ubo.get('complete'):
        reasons.append('ubo_incomplete')
    band = KycIdentityCase.BAND_CLEAR
    if blockers or identity_fails or provider_denied or unreadable or biometric_hard_fail:
        band = KycIdentityCase.BAND_BLOCKED
        if identity_fails and not any('match' in b.lower() for b in blockers):
            blockers.append('Identity on a document does not match the applicant.')
    elif needs_review or reuse or provider_error or avg < 70 or biometric_failed or (
        needs_ubo and not ubo.get('complete')
    ) or 'biometric_pending' in reasons:
        band = KycIdentityCase.BAND_REVIEW
        if not docs:
            band = KycIdentityCase.BAND_REVIEW
        if provider_error:
            reasons.append('provider_unconfirmed')
    if (
        band != KycIdentityCase.BAND_BLOCKED
        and not docs
        and not any(p.fan or p.tin or p.id_number for p in parties)
    ):
        band = KycIdentityCase.BAND_REVIEW
        avg = min(avg, 50)

    applicant_bio = {
        'status': getattr(applicant, 'biometric_status', '') if applicant else '',
        'score': str(getattr(applicant, 'face_match_score', '') or '') if applicant else '',
        'liveness_ref': getattr(applicant, 'liveness_ref', '') if applicant else '',
        'has_selfie': bool(applicant and getattr(getattr(applicant, 'selfie', None), 'name', '')),
    }
    findings = dict(case.findings or {})
    findings.update({
        'recomputed_at': timezone.now().isoformat(),
        'document_count': len(docs),
        'identity_ok': identity_ok,
        'identity_fails': identity_fails,
        'needs_review': needs_review,
        'reuse': reuse,
        'reasons': sorted(set(reasons)),
        'biometric': applicant_bio,
        'ubo': ubo,
        'needs_ubo': needs_ubo,
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
        hints['legal_personality'] = 'System: applicant identity confirmed on the case.'
    bio = findings.get('biometric') or {}
    if bio.get('status') == 'matched':
        hints['identity_match'] = (
            hints.get('identity_match') or 'System: selfie matched the ID portrait.'
        )
    elif bio.get('status') == 'failed':
        hints['identity_match'] = 'System: face match failed — review before clearing.'
    ubo = findings.get('ubo') or {}
    if findings.get('needs_ubo'):
        if ubo.get('complete'):
            msg = (
                f"System: {ubo.get('directors', 0)} director(s), "
                f"{ubo.get('ubos', 0)} UBO(s) recorded"
            )
            if ubo.get('share_percent'):
                msg += f", share {ubo['share_percent']}%"
            hints['ubo'] = msg + '.'
            hints['ubo_recorded'] = hints['ubo']
            if ubo.get('directors'):
                hints['title_or_authority'] = 'System: a director is on the identity case.'
        else:
            hints['ubo'] = 'System: no director or UBO on the identity case yet.'
            hints['ubo_recorded'] = hints['ubo']
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
    from loans.models import KycParty

    case = get_identity_case(loan_request=loan_request)
    if case is None:
        return None
    parties = []
    for p in case.parties.all():
        parties.append({
            'pk': p.pk,
            'role': p.get_role_display(),
            'role_key': p.role,
            'name': p.legal_name_en or p.legal_name_am,
            'kind': p.get_identity_kind_display(),
            'fan': p.fan,
            'tin': p.tin,
            'id_number': p.id_number,
            'verify': p.get_verify_status_display(),
            'verify_status': p.verify_status,
            'biometric': p.get_biometric_status_display() if p.biometric_status else '',
            'biometric_status': p.biometric_status,
            'face_match_score': str(p.face_match_score) if p.face_match_score is not None else '',
            'liveness_ref': p.liveness_ref,
            'share_percent': str(p.share_percent) if p.share_percent is not None else '',
            'capacity': p.capacity,
            'has_selfie': bool(getattr(p.selfie, 'name', '')),
            'is_related': p.role != p.ROLE_APPLICANT,
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
        'loan_id': getattr(loan, 'pk', None),
        'related_roles': related_role_choices(),
        'identity_kinds': KycParty.KIND_CHOICES,
        'needs_ubo': bool((case.findings or {}).get('needs_ubo')),
        'ubo': (case.findings or {}).get('ubo') or {},
        'biometric': (case.findings or {}).get('biometric') or {},
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
