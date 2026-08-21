"""Remote OTP agreement signing (SMS link + 6-digit code)."""

from __future__ import annotations

import base64
import secrets
from datetime import timedelta
from typing import Optional, Tuple

from django.contrib.auth.hashers import check_password, make_password
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone

OTP_MINUTES = 30

# Minimal 1×1 PNG placeholder when no pad drawing (remote OTP).
_PLACEHOLDER_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
)


def _client_ip(request) -> Optional[str]:
    if request is None:
        return None
    forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    return forwarded or request.META.get('REMOTE_ADDR')


def issue_remote_sign_challenge(
    agreement,
    *,
    role: str,
    signer_name: str,
    signer_phone: str,
    signer_id_number: str = '',
    created_by=None,
    request=None,
) -> Tuple[object, str, str]:
    """
    Create challenge + send OTP SMS.
    Returns (challenge, raw_otp, public_url_path).
    """
    from loans.agreement_signing import hash_body
    from loans.models import LoanAgreement, LoanAgreementRemoteChallenge, LoanAgreementSignature
    from applicant_portal.notify import deliver_sms

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

    name = (signer_name or '').strip()
    phone = (signer_phone or '').strip()
    if len(name) < 2:
        raise ValueError('Enter the full name of the person signing.')
    if len(phone) < 9:
        raise ValueError('Enter a mobile number for the OTP SMS.')

    id_no = (signer_id_number or '').strip()
    if role in (
        LoanAgreementSignature.ROLE_BORROWER,
        LoanAgreementSignature.ROLE_GUARANTOR,
    ) and len(id_no) < 3:
        raise ValueError('Record the borrower’s / guarantor’s ID number.')

    # Invalidate open challenges for same role
    LoanAgreementRemoteChallenge.objects.filter(
        agreement=agreement, role=role, consumed_at__isnull=True,
    ).update(consumed_at=timezone.now())

    code = f'{secrets.randbelow(1_000_000):06d}'
    token = secrets.token_urlsafe(24)
    challenge = LoanAgreementRemoteChallenge.objects.create(
        agreement=agreement,
        role=role,
        token=token,
        otp_hash=make_password(code),
        signer_name=name[:255],
        signer_phone=phone[:30],
        signer_id_number=id_no[:80],
        content_hash=agreement.content_hash,
        expires_at=timezone.now() + timedelta(minutes=OTP_MINUTES),
        created_by=created_by,
        request_ip=_client_ip(request),
    )
    path = reverse('remote_agreement_sign', args=[token])
    body = (
        f'DECSI loan agreement OTP: {code}. '
        f'Valid {OTP_MINUTES} min. Open the sign link from your officer to finish.'
    )
    deliver_sms(phone, body, subject='Agreement OTP')
    return challenge, code, path


def complete_remote_sign(
    challenge,
    *,
    otp: str,
    declaration_accepted: bool,
    request=None,
) -> object:
    """Verify OTP and record a remote_otp signature bound to content_hash."""
    from loans.agreement_signing import hash_body
    from loans.models import LoanAgreement, LoanAgreementSignature

    if challenge.consumed_at:
        raise ValueError('This sign link was already used.')
    if challenge.expires_at <= timezone.now():
        raise ValueError('This OTP has expired. Ask the branch to send a new link.')
    if not declaration_accepted:
        raise ValueError('You must confirm you have read the agreement and intend to be bound.')
    if not check_password((otp or '').strip(), challenge.otp_hash):
        raise ValueError('Incorrect OTP. Check the SMS and try again.')

    agreement = challenge.agreement
    if agreement.status == LoanAgreement.STATUS_VOID:
        raise ValueError('This agreement was voided.')
    if agreement.content_hash != challenge.content_hash:
        raise ValueError('Agreement changed after the OTP was sent — request a new link.')
    if agreement.content_hash != hash_body(agreement.body_text):
        raise ValueError('Agreement text hash mismatch — contact the branch.')

    agreement.signatures.filter(role=challenge.role, is_valid=True).update(is_valid=False)

    import hashlib
    image_sha = hashlib.sha256(_PLACEHOLDER_PNG).hexdigest()
    sig = LoanAgreementSignature(
        agreement=agreement,
        role=challenge.role,
        signer_name=challenge.signer_name,
        typed_name=challenge.signer_name,
        signer_id_number=challenge.signer_id_number,
        declaration_accepted=True,
        signer_user=None,
        signature_method=LoanAgreementSignature.METHOD_REMOTE_OTP,
        signature_image_sha256=image_sha,
        content_hash_at_sign=agreement.content_hash,
        ip_address=_client_ip(request),
        user_agent=((request.META.get('HTTP_USER_AGENT') if request else '') or '')[:512],
        notes='Remote OTP acceptance',
        is_valid=True,
    )
    filename = f'agr{agreement.pk}_{challenge.role}_otp_{timezone.now().strftime("%Y%m%d%H%M%S")}.png'
    sig.signature_image.save(filename, ContentFile(_PLACEHOLDER_PNG), save=False)
    sig.save()

    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=['consumed_at'])
    LoanAgreementRemoteChallenge = challenge.__class__
    LoanAgreementRemoteChallenge.objects.filter(
        agreement=agreement, role=challenge.role, consumed_at__isnull=True,
    ).exclude(pk=challenge.pk).update(consumed_at=timezone.now())

    agreement.refresh_status()
    return sig
