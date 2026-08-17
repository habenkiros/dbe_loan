"""Digital loan agreement signatures — post-approval, before disbursement.

Captures PNG signatures from a pad with audit metadata (IP, UA, content hash,
typed-name confirmation, ID, and an intent declaration).
This is electronic signature evidence for branch tablet capture — not PKI.
"""

from __future__ import annotations

import hashlib
import base64
import re
from typing import List, Optional, Tuple

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone


def hash_body(body_text: str) -> str:
    return hashlib.sha256((body_text or '').encode('utf-8')).hexdigest()


def _norm_name(value: str) -> str:
    return ' '.join((value or '').split()).casefold()


def _format_money(amount) -> str:
    if amount is None:
        return '—'
    try:
        return f'{amount:,.2f}'
    except (TypeError, ValueError):
        return str(amount)


def build_loan_agreement_body(loan_request) -> str:
    from loans.collateral_legal import collateral_legal_summary
    from loans.disbursement import final_loan_amount, schedule_summary
    from loans.models import LoanAppraisal, LoanRequestBasicInfo

    appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    basic = LoanRequestBasicInfo.objects.filter(loan_request=loan_request).first()
    amount = final_loan_amount(loan_request, appraisal)
    term = (
        (appraisal.term_approved_months if appraisal and appraisal.term_approved_months else None)
        or (basic.term_months if basic else None)
        or '—'
    )
    rate = (
        (appraisal.rate_approved if appraisal and appraisal.rate_approved is not None else None)
        or (basic.interest_rate if basic else None)
        or '—'
    )
    branch = loan_request.branch.name if loan_request.branch_id else '—'
    district = ''
    if loan_request.branch_id and getattr(loan_request.branch, 'district', None):
        district = loan_request.branch.district.name
    officer = ''
    if loan_request.assigned_loan_officer_id:
        officer = (
            loan_request.assigned_loan_officer.get_full_name()
            or loan_request.assigned_loan_officer.username
        )
    tin = (basic.tin_number if basic else '') or '—'
    today = timezone.localdate().strftime('%d %B %Y')
    legal = collateral_legal_summary(loan_request)
    restriction_line = 'Not required for this facility.'
    if legal.get('require_restriction'):
        latest = (legal.get('restriction_docs') or [None])[0]
        if latest and latest.reference_number:
            restriction_line = (
                f'Reference {latest.reference_number}'
                + (f' issued by {latest.issuing_office}' if latest.issuing_office else '')
                + (f' · parcel {latest.parcel_reference}' if getattr(latest, 'parcel_reference', '') else '')
            )
        else:
            restriction_line = 'Required — government restriction paper to be verified before disbursement.'
    poa_line = 'Not applicable (collateral not held via POA).'
    if legal.get('via_poa'):
        latest_poa = (legal.get('poa_docs') or [None])[0]
        if latest_poa and latest_poa.grantor_name:
            poa_line = (
                f'{latest_poa.grantor_name} → {latest_poa.attorney_name or "—" }'
                + (f' (deed {latest_poa.reference_number})' if latest_poa.reference_number else '')
            )
        else:
            poa_line = 'Required — Loan Collateral Power of Attorney to be verified before disbursement.'

    sched = schedule_summary(loan_request)
    instalments = sched.get('row_count') or '—'

    return (
        f'DECSI — LOAN AGREEMENT\n'
        f'Dedebit Credit and Savings Institution\n'
        f'================================================\n\n'
        f'1. PARTIES\n'
        f'This Agreement is made on {today} at {branch}'
        f'{(" / " + district) if district else ""} between:\n'
        f'(a) Dedebit Credit and Savings Institution (“DECSI”, the Lender); and\n'
        f'(b) {loan_request.applicant_name} (“the Borrower”).\n'
        f'Phone: {loan_request.phone_number or "—"}\n'
        f'Customer no.: {loan_request.customer_number or "—"}\n'
        f'TIN: {tin}\n'
        f'Loan request: {loan_request.loan_request_id}\n'
        f'Assigned officer: {officer or "—"}\n\n'
        f'2. FACILITY\n'
        f'DECSI agrees to lend, and the Borrower agrees to take, a loan of ETB {_format_money(amount)} '
        f'(the “Principal”) for a term of {term} months at {rate}% per annum, for the purpose: '
        f'{loan_request.reason or "as stated in the application"}.\n'
        f'Repayment shall follow the schedule confirmed in the DECSI Loan Hub '
        f'({instalments} instalment(s)). Interest accrues as shown on that schedule.\n\n'
        f'3. COLLATERAL AND LEGAL PAPERS\n'
        f'The Borrower charges in favour of DECSI the collateral described on this file.\n'
        f'Government Collateral Restriction: {restriction_line}\n'
        f'Loan Collateral Power of Attorney: {poa_line}\n'
        f'DECSI may enforce the security if the Borrower defaults.\n\n'
        f'4. BORROWER UNDERTAKINGS\n'
        f'The Borrower confirms that the information given is true, will use the Principal '
        f'for the stated purpose, will repay on schedule, and will not dispose of pledged '
        f'collateral without DECSI’s written consent.\n\n'
        f'5. DEFAULT\n'
        f'Failure to pay any instalment when due, or a material misstatement, entitles DECSI '
        f'to demand the outstanding balance and to realise the security in accordance with '
        f'applicable Ethiopian law and DECSI policy.\n\n'
        f'6. ELECTRONIC SIGNATURE\n'
        f'Each party may sign this Agreement by drawing a signature on an electronic device. '
        f'The drawn mark, the typed name, the identity number recorded at signing, the time, '
        f'IP address, and the SHA-256 content hash of this text constitute the audit record. '
        f'Altering this text after a signature is captured voids prior signatures. '
        f'The Borrower intends to be legally bound as if this were a wet-ink original.\n\n'
        f'7. GOVERNING LAW\n'
        f'This Agreement is governed by the laws of the Federal Democratic Republic of Ethiopia.\n'
    )


def agreements_satisfied(loan_request) -> bool:
    if not getattr(loan_request, 'require_agreement_signatures', True):
        return True
    from loans.models import LoanAgreement

    active = loan_request.agreements.exclude(status=LoanAgreement.STATUS_VOID)
    loan_agreements = active.filter(kind=LoanAgreement.KIND_LOAN)
    if not loan_agreements.exists():
        return False
    return loan_agreements.filter(status=LoanAgreement.STATUS_SIGNED).exists()


def agreement_blockers(loan_request) -> List[str]:
    if not getattr(loan_request, 'require_agreement_signatures', True):
        return []
    from loans.models import LoanAgreement

    active = list(
        loan_request.agreements.exclude(status=LoanAgreement.STATUS_VOID)
        .filter(kind=LoanAgreement.KIND_LOAN)
        .order_by('-generated_at')
    )
    if not active:
        return [
            'Loan agreement must be generated and digitally signed '
            '(borrower + loan officer) before disbursement.'
        ]
    latest = active[0]
    if latest.status != LoanAgreement.STATUS_SIGNED:
        missing = _missing_roles(latest)
        label = ', '.join(missing) if missing else 'required parties'
        return [
            f'Loan agreement is not fully signed — awaiting signature(s): {label}.'
        ]
    return []


def _needed_role_keys(agreement) -> List[str]:
    from loans.models import LoanAgreementSignature

    needed = []
    if agreement.require_borrower:
        needed.append(LoanAgreementSignature.ROLE_BORROWER)
    if agreement.require_guarantor:
        needed.append(LoanAgreementSignature.ROLE_GUARANTOR)
    if agreement.require_officer:
        needed.append(LoanAgreementSignature.ROLE_OFFICER)
    if agreement.require_branch_manager:
        needed.append(LoanAgreementSignature.ROLE_BRANCH_MANAGER)
    return needed


def _missing_roles(agreement) -> List[str]:
    from loans.models import LoanAgreementSignature

    labels = dict(LoanAgreementSignature.ROLE_CHOICES)
    have = set(
        agreement.signatures.filter(is_valid=True).values_list('role', flat=True)
    )
    return [labels.get(r, r) for r in _needed_role_keys(agreement) if r not in have]


def signature_slots(agreement) -> List[dict]:
    """Ordered signer slots with captured signature when present."""
    from loans.models import LoanAgreementSignature

    labels = dict(LoanAgreementSignature.ROLE_CHOICES)
    by_role = {
        s.role: s
        for s in agreement.signatures.filter(is_valid=True)
    }
    slots = []
    for role in _needed_role_keys(agreement):
        sig = by_role.get(role)
        slots.append({
            'role': role,
            'label': labels.get(role, role),
            'signed': sig is not None,
            'signature': sig,
        })
    return slots


def agreement_summary(loan_request) -> dict:
    from loans.models import LoanAgreement

    agreements = list(
        loan_request.agreements.exclude(status=LoanAgreement.STATUS_VOID)
        .prefetch_related('signatures')
        .order_by('-generated_at')
    )
    latest_loan = next(
        (a for a in agreements if a.kind == LoanAgreement.KIND_LOAN),
        None,
    )
    slots = signature_slots(latest_loan) if latest_loan else []
    signed_count = sum(1 for s in slots if s['signed'])
    return {
        'required': bool(getattr(loan_request, 'require_agreement_signatures', True)),
        'ok': agreements_satisfied(loan_request),
        'agreements': agreements,
        'latest_loan': latest_loan,
        'missing_roles': _missing_roles(latest_loan) if latest_loan else [],
        'slots': slots,
        'signed_count': signed_count,
        'slot_count': len(slots),
        'blockers': agreement_blockers(loan_request),
    }


@transaction.atomic
def generate_loan_agreement(
    loan_request,
    user,
    *,
    kind: Optional[str] = None,
    require_guarantor: bool = False,
    require_branch_manager: bool = False,
    void_previous: bool = True,
):
    from loans.models import LoanAgreement

    kind = kind or LoanAgreement.KIND_LOAN
    if void_previous:
        loan_request.agreements.filter(kind=kind).exclude(
            status=LoanAgreement.STATUS_VOID,
        ).update(
            status=LoanAgreement.STATUS_VOID,
            voided_at=timezone.now(),
            void_reason='Superseded by regenerated agreement',
        )

    body = build_loan_agreement_body(loan_request)
    titles = {
        LoanAgreement.KIND_LOAN: f'Loan agreement — {loan_request.loan_request_id}',
        LoanAgreement.KIND_COLLATERAL_PLEDGE: (
            f'Collateral pledge — {loan_request.loan_request_id}'
        ),
        LoanAgreement.KIND_GUARANTEE: f'Guarantee — {loan_request.loan_request_id}',
    }
    agr = LoanAgreement.objects.create(
        loan_request=loan_request,
        kind=kind,
        title=titles.get(kind, f'Agreement — {loan_request.loan_request_id}'),
        body_text=body,
        content_hash=hash_body(body),
        status=LoanAgreement.STATUS_PENDING,
        require_borrower=True,
        require_guarantor=require_guarantor,
        require_officer=True,
        require_branch_manager=require_branch_manager,
        generated_by=user,
    )
    return agr


def _client_ip(request) -> Optional[str]:
    forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    return forwarded or request.META.get('REMOTE_ADDR') or None


_DATA_URL_RE = re.compile(
    r'^data:image/(png|jpeg|jpg);base64,([A-Za-z0-9+/=\s]+)$',
    re.IGNORECASE,
)


def decode_signature_data_url(data_url: str) -> Tuple[bytes, str]:
    """Return (bytes, extension) from a canvas data URL."""
    raw = (data_url or '').strip()
    m = _DATA_URL_RE.match(raw)
    if not m:
        raise ValueError('Signature must be a PNG/JPEG data URL from the pad.')
    ext = m.group(1).lower()
    if ext == 'jpg':
        ext = 'jpeg'
    blob = base64.b64decode(m.group(2))
    if len(blob) < 40:
        raise ValueError('Signature image is empty — please draw again.')
    if len(blob) > 1_500_000:
        raise ValueError('Signature image is too large.')
    return blob, 'png' if ext == 'png' else 'jpg'


@transaction.atomic
def record_signature(
    agreement,
    *,
    role: str,
    signer_name: str,
    data_url: str,
    request,
    signer_user=None,
    notes: str = '',
    typed_name: str = '',
    signer_id_number: str = '',
    declaration_accepted: bool = False,
):
    from loans.models import LoanAgreement, LoanAgreementSignature

    if agreement.status == LoanAgreement.STATUS_VOID:
        raise ValueError('This agreement was voided — generate a new one.')
    if agreement.content_hash != hash_body(agreement.body_text):
        raise ValueError('Agreement text hash mismatch — regenerate the agreement.')

    valid_roles = {c[0] for c in LoanAgreementSignature.ROLE_CHOICES}
    if role not in valid_roles:
        raise ValueError('Invalid signer role.')

    required_map = {
        LoanAgreementSignature.ROLE_BORROWER: agreement.require_borrower,
        LoanAgreementSignature.ROLE_GUARANTOR: agreement.require_guarantor,
        LoanAgreementSignature.ROLE_OFFICER: agreement.require_officer,
        LoanAgreementSignature.ROLE_BRANCH_MANAGER: agreement.require_branch_manager,
    }
    if not required_map.get(role):
        raise ValueError('This signer role is not required on this agreement.')

    if not declaration_accepted:
        raise ValueError('The signer must confirm they have read the agreement and intend to be bound.')

    name = (signer_name or '').strip()
    if len(name) < 2:
        raise ValueError('Enter the full name of the person signing.')

    typed = (typed_name or '').strip() or name
    if _norm_name(typed) != _norm_name(name):
        raise ValueError('Typed name must match the signer’s full name.')

    id_no = (signer_id_number or '').strip()
    if role in (
        LoanAgreementSignature.ROLE_BORROWER,
        LoanAgreementSignature.ROLE_GUARANTOR,
    ) and len(id_no) < 3:
        raise ValueError('Record the borrower’s / guarantor’s ID number (national ID, kebele ID, or passport).')

    blob, ext = decode_signature_data_url(data_url)

    agreement.signatures.filter(role=role, is_valid=True).update(is_valid=False)

    sig = LoanAgreementSignature(
        agreement=agreement,
        role=role,
        signer_name=name[:255],
        typed_name=typed[:255],
        signer_id_number=id_no[:80],
        declaration_accepted=True,
        signer_user=signer_user,
        content_hash_at_sign=agreement.content_hash,
        ip_address=_client_ip(request),
        user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:512],
        notes=(notes or '')[:255],
        is_valid=True,
    )
    filename = f'agr{agreement.pk}_{role}_{timezone.now().strftime("%Y%m%d%H%M%S")}.{ext}'
    sig.signature_image.save(filename, ContentFile(blob), save=False)
    sig.save()
    agreement.refresh_status()
    return sig
