"""Collateral Restriction (government) + Power of Attorney — post-approval legal papers."""

from __future__ import annotations

from typing import List, Optional

from django.utils import timezone

from loans.process_policy import requirement_on


def has_verified_doc(loan_request, kind: str) -> bool:
    from loans.models import LoanCollateralLegalDocument

    return loan_request.collateral_legal_documents.filter(
        kind=kind,
        status=LoanCollateralLegalDocument.STATUS_VERIFIED,
    ).exists()


def restriction_satisfied(loan_request) -> bool:
    """True if restriction not required, or a verified government paper exists."""
    if not requirement_on(loan_request, 'require_collateral_restriction'):
        return True
    from loans.models import LoanCollateralLegalDocument

    return has_verified_doc(loan_request, LoanCollateralLegalDocument.KIND_RESTRICTION)


def poa_satisfied(loan_request) -> bool:
    """True if POA not used, or a verified POA deed exists."""
    if not getattr(loan_request, 'collateral_held_via_poa', False):
        return True
    from loans.models import LoanCollateralLegalDocument

    return has_verified_doc(loan_request, LoanCollateralLegalDocument.KIND_POA)


def _optional_kind_satisfied(loan_request, required_flag: str, kind: str) -> bool:
    if not requirement_on(loan_request, required_flag):
        return True
    return has_verified_doc(loan_request, kind)


def title_search_satisfied(loan_request) -> bool:
    from loans.models import LoanCollateralLegalDocument
    return _optional_kind_satisfied(
        loan_request, 'require_title_search', LoanCollateralLegalDocument.KIND_TITLE_SEARCH,
    )


def mortgage_registration_satisfied(loan_request) -> bool:
    from loans.models import LoanCollateralLegalDocument
    return _optional_kind_satisfied(
        loan_request, 'require_mortgage_registration', LoanCollateralLegalDocument.KIND_MORTGAGE_REG,
    )


def notary_stamp_satisfied(loan_request) -> bool:
    from loans.models import LoanCollateralLegalDocument
    return _optional_kind_satisfied(
        loan_request, 'require_notary_stamp', LoanCollateralLegalDocument.KIND_NOTARY_STAMP,
    )


def collateral_legal_blockers(loan_request) -> List[str]:
    blockers = []
    from loans.models import LoanCollateralLegalDocument

    if requirement_on(loan_request, 'require_collateral_restriction'):
        if not has_verified_doc(loan_request, LoanCollateralLegalDocument.KIND_RESTRICTION):
            blockers.append(
                'Government Collateral Restriction paper must be uploaded and verified '
                'before disbursement.'
            )
    if getattr(loan_request, 'collateral_held_via_poa', False):
        if not has_verified_doc(loan_request, LoanCollateralLegalDocument.KIND_POA):
            blockers.append(
                'Loan Collateral Power of Attorney must be uploaded and verified '
                '(collateral is held via POA).'
            )
    if requirement_on(loan_request, 'require_title_search'):
        if not has_verified_doc(loan_request, LoanCollateralLegalDocument.KIND_TITLE_SEARCH):
            blockers.append('Title / ownership search must be uploaded and verified before disbursement.')
    if requirement_on(loan_request, 'require_mortgage_registration'):
        if not has_verified_doc(loan_request, LoanCollateralLegalDocument.KIND_MORTGAGE_REG):
            blockers.append('Mortgage / restriction registration proof must be verified before disbursement.')
    if requirement_on(loan_request, 'require_notary_stamp'):
        if not has_verified_doc(loan_request, LoanCollateralLegalDocument.KIND_NOTARY_STAMP):
            blockers.append('Notary / stamp-duty receipt must be verified before disbursement.')
    return blockers


def _doc_state(docs, required: bool, not_used: bool = False) -> str:
    if not_used:
        return 'not_used'
    if not required:
        return 'waived'
    verified = [d for d in docs if d.status == 'verified']
    if verified:
        return 'verified'
    pending = [d for d in docs if d.status == 'uploaded']
    if pending:
        return 'pending'
    rejected = [d for d in docs if d.status == 'rejected']
    if rejected:
        return 'rejected'
    return 'missing'


def collateral_legal_summary(loan_request) -> dict:
    from loans.models import LoanCollateralLegalDocument

    docs = list(
        loan_request.collateral_legal_documents.order_by('-created_at')
        .select_related('uploaded_by', 'verified_by')
    )
    restriction_docs = [d for d in docs if d.kind == LoanCollateralLegalDocument.KIND_RESTRICTION]
    poa_docs = [d for d in docs if d.kind == LoanCollateralLegalDocument.KIND_POA]
    title_docs = [d for d in docs if d.kind == LoanCollateralLegalDocument.KIND_TITLE_SEARCH]
    mort_docs = [d for d in docs if d.kind == LoanCollateralLegalDocument.KIND_MORTGAGE_REG]
    notary_docs = [d for d in docs if d.kind == LoanCollateralLegalDocument.KIND_NOTARY_STAMP]
    require_restriction = requirement_on(loan_request, 'require_collateral_restriction')
    via_poa = bool(getattr(loan_request, 'collateral_held_via_poa', False))
    require_title = requirement_on(loan_request, 'require_title_search')
    require_mort = requirement_on(loan_request, 'require_mortgage_registration')
    require_notary = requirement_on(loan_request, 'require_notary_stamp')
    return {
        'require_restriction': require_restriction,
        'via_poa': via_poa,
        'require_title_search': require_title,
        'require_mortgage_registration': require_mort,
        'require_notary_stamp': require_notary,
        'restriction_ok': restriction_satisfied(loan_request),
        'poa_ok': poa_satisfied(loan_request),
        'title_ok': title_search_satisfied(loan_request),
        'mortgage_ok': mortgage_registration_satisfied(loan_request),
        'notary_ok': notary_stamp_satisfied(loan_request),
        'restriction_state': _doc_state(restriction_docs, require_restriction),
        'poa_state': _doc_state(poa_docs, via_poa, not_used=not via_poa),
        'title_state': _doc_state(title_docs, require_title),
        'mortgage_state': _doc_state(mort_docs, require_mort),
        'notary_state': _doc_state(notary_docs, require_notary),
        'restriction_docs': restriction_docs,
        'poa_docs': poa_docs,
        'title_docs': title_docs,
        'mortgage_docs': mort_docs,
        'notary_docs': notary_docs,
        'latest_restriction': restriction_docs[0] if restriction_docs else None,
        'latest_poa': poa_docs[0] if poa_docs else None,
        'all_docs': docs,
        'blockers': collateral_legal_blockers(loan_request),
    }


def closing_pack_summary(loan_request) -> dict:
    """Combined Restriction + POA + Agreement progress for the post-approval workspace."""
    from loans.agreement_signing import agreement_summary

    legal = collateral_legal_summary(loan_request)
    agr = agreement_summary(loan_request)

    if legal['restriction_ok']:
        rest_label = 'Verified' if legal['require_restriction'] else 'Not required'
    else:
        rest_label = {
            'pending': 'Uploaded — verify',
            'rejected': 'Rejected — re-upload',
            'missing': 'Not uploaded',
        }.get(legal['restriction_state'], 'Open')

    if not legal['via_poa']:
        poa_label = 'Not used'
    elif legal['poa_ok']:
        poa_label = 'Verified'
    else:
        poa_label = {
            'pending': 'Uploaded — verify',
            'rejected': 'Rejected — re-upload',
            'missing': 'Not uploaded',
        }.get(legal['poa_state'], 'Open')

    if not agr['required']:
        agr_label = 'Not required'
    elif agr['ok']:
        agr_label = 'Fully signed'
    elif agr['latest_loan']:
        agr_label = f'{agr["signed_count"]}/{agr["slot_count"]} signed'
    else:
        agr_label = 'Not generated'

    items = [
        {
            'key': 'restriction',
            'title': 'Collateral Restriction',
            'ok': legal['restriction_ok'],
            'required': legal['require_restriction'],
            'label': rest_label,
        },
        {
            'key': 'poa',
            'title': 'Power of Attorney',
            'ok': legal['poa_ok'],
            'required': legal['via_poa'],
            'label': poa_label,
        },
        {
            'key': 'title',
            'title': 'Title search',
            'ok': legal['title_ok'],
            'required': legal['require_title_search'],
            'label': 'Verified' if legal['title_ok'] and legal['require_title_search'] else (
                'Not required' if not legal['require_title_search'] else 'Open'
            ),
        },
        {
            'key': 'mortgage',
            'title': 'Mortgage registration',
            'ok': legal['mortgage_ok'],
            'required': legal['require_mortgage_registration'],
            'label': 'Verified' if legal['mortgage_ok'] and legal['require_mortgage_registration'] else (
                'Not required' if not legal['require_mortgage_registration'] else 'Open'
            ),
        },
        {
            'key': 'notary',
            'title': 'Notary / stamp',
            'ok': legal['notary_ok'],
            'required': legal['require_notary_stamp'],
            'label': 'Verified' if legal['notary_ok'] and legal['require_notary_stamp'] else (
                'Not required' if not legal['require_notary_stamp'] else 'Open'
            ),
        },
        {
            'key': 'agreement',
            'title': 'Digital signatures',
            'ok': agr['ok'],
            'required': agr['required'],
            'label': agr_label,
        },
    ]
    done = sum(1 for i in items if i['ok'])
    return {
        'items': items,
        'done': done,
        'total': len(items),
        'ok': done == len(items),
        'legal': legal,
        'agreement': agr,
    }


def validate_legal_upload(kind: str, data: dict) -> Optional[str]:
    """Return an error message if required fields for this paper are missing."""
    from loans.models import LoanCollateralLegalDocument

    ref = (data.get('reference_number') or '').strip()
    office = (data.get('issuing_office') or '').strip()
    if kind == LoanCollateralLegalDocument.KIND_RESTRICTION:
        if len(ref) < 2:
            return 'Enter the government restriction / title reference number.'
        if len(office) < 2:
            return 'Enter the issuing office (Land Administration, Municipality, or equivalent).'
        return None
    if kind == LoanCollateralLegalDocument.KIND_POA:
        if len(ref) < 2:
            return 'Enter the POA deed / notary reference number.'
        if len((data.get('grantor_name') or '').strip()) < 2:
            return 'Enter the POA grantor (collateral owner).'
        if len((data.get('attorney_name') or '').strip()) < 2:
            return 'Enter the attorney-in-fact named in the POA (usually the borrower).'
        return None
    if kind in (
        LoanCollateralLegalDocument.KIND_TITLE_SEARCH,
        LoanCollateralLegalDocument.KIND_MORTGAGE_REG,
        LoanCollateralLegalDocument.KIND_NOTARY_STAMP,
    ):
        if len(ref) < 2:
            return 'Enter the document reference number.'
        if len(office) < 2:
            return 'Enter the issuing office.'
        return None
    return 'Unknown document type.'


def verify_legal_document(doc, user, *, approve: bool = True, note: str = '') -> None:
    from loans.models import LoanCollateralLegalDocument

    note = (note or '').strip()
    if approve:
        doc.status = LoanCollateralLegalDocument.STATUS_VERIFIED
    else:
        if len(note) < 5:
            raise ValueError('Add a short reason when rejecting a legal paper.')
        doc.status = LoanCollateralLegalDocument.STATUS_REJECTED
    doc.verified_by = user
    doc.verified_at = timezone.now()
    if note:
        doc.verification_note = note[:400]
        extra = (('Rejected: ' if not approve else 'Verified: ') + note)
        doc.notes = ((doc.notes or '') + '\n' + extra).strip()
    doc.save()
