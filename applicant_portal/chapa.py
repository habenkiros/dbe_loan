"""Chapa payment gateway for digital-apply processing fees.

Docs: https://developer.chapa.co/docs
  POST /v1/transaction/initialize
  GET  /v1/transaction/verify/{tx_ref}
"""

from __future__ import annotations

import logging
import re
import uuid
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

CHAPA_INIT_URL = 'https://api.chapa.co/v1/transaction/initialize'
CHAPA_VERIFY_URL = 'https://api.chapa.co/v1/transaction/verify/{tx_ref}'
# Chapa customization.title max 16; description: letters, numbers, hyphen, underscore, space, dots.
_CHAPA_DESC_RE = re.compile(r'[^A-Za-z0-9 _.\-]+')
_BAD_EMAIL_TLDS = ('.local', '.test', '.invalid', '.localhost', '.example')


def chapa_secret_key() -> str:
    return (getattr(settings, 'CHAPA_SECRET_KEY', '') or '').strip()


def chapa_force_mock() -> bool:
    return bool(getattr(settings, 'CHAPA_FORCE_MOCK', False))


def chapa_live_enabled() -> bool:
    """True when a secret key is configured and mock is not forced."""
    return bool(chapa_secret_key()) and not chapa_force_mock()


def chapa_public_key() -> str:
    return (getattr(settings, 'CHAPA_PUBLIC_KEY', '') or '').strip()


def _site_url() -> str:
    return (getattr(settings, 'SITE_URL', '') or 'http://localhost:8000').rstrip('/')


def checkout_base_url(request=None) -> str:
    """Origin the browser is actually using — not the LAN IP baked into SITE_URL.

    Chapa redirects the customer to return_url. If that is 10.x:8443 while they
    applied on localhost:8000, they land on an IP (and lose the portal session).
    """
    if request is not None:
        host = (request.get_host() or '').strip()
        if host.startswith('127.0.0.1'):
            host = 'localhost' + host[9:]
        forwarded = (request.META.get('HTTP_X_FORWARDED_PROTO') or '').split(',')[0].strip()
        if forwarded in ('http', 'https'):
            scheme = forwarded
        else:
            scheme = 'https' if request.is_secure() else 'http'
        if host:
            return f'{scheme}://{host}'.rstrip('/')
    return _site_url()


def payment_return_url(application, tx_ref: str, *, request=None) -> str:
    path = reverse(
        'applicant_portal:apply_payment_return',
        args=[application.public_id],
    )
    return f'{checkout_base_url(request)}{path}?tx_ref={tx_ref}'


def payment_callback_url(*, request=None) -> str:
    path = reverse('applicant_portal:chapa_webhook')
    return f'{checkout_base_url(request)}{path}'


def make_tx_ref(application) -> str:
    # Chapa prefers unique transaction references (max ~50).
    short = application.public_id.hex[:12]
    return f'DA-{short}-{uuid.uuid4().hex[:8]}'.upper()


def _chapa_email(application) -> str:
    """Chapa requires a real-looking email; .local and empty values fail validation."""
    candidates = [
        getattr(application, 'email', '') or '',
        getattr(getattr(application, 'applicant', None), 'email', '') or '',
    ]
    for raw in candidates:
        email = (raw or '').strip()
        if not email:
            continue
        try:
            validate_email(email)
        except ValidationError:
            continue
        host = email.rsplit('@', 1)[-1].lower()
        if any(host.endswith(tld) for tld in _BAD_EMAIL_TLDS) or '.' not in host:
            continue
        return email
    token = application.applicant.public_id.hex[:12]
    return f'da{token}@decsi.com'


def _chapa_plain(value: str, *, max_len: int, fallback: str) -> str:
    cleaned = _CHAPA_DESC_RE.sub(' ', value or '')
    cleaned = ' '.join(cleaned.split())[:max_len].strip()
    return cleaned or fallback[:max_len]


def build_initialize_payload(application, *, tx_ref: str, return_url: str, callback_url: str) -> dict:
    amount = application.processing_fee_amount
    phone = (application.phone_number or application.applicant.phone_number or '').strip()
    name = (application.applicant_name or application.applicant.full_name or 'Applicant').strip()
    parts = name.split(None, 1)
    first = _chapa_plain(parts[0] if parts else 'Applicant', max_len=50, fallback='Applicant')
    last = _chapa_plain(parts[1] if len(parts) > 1 else 'Digital', max_len=50, fallback='Digital')
    phone_digits = re.sub(r'\D', '', phone)
    if phone_digits.startswith('251') and len(phone_digits) >= 12:
        phone_digits = '0' + phone_digits[3:]
    elif len(phone_digits) == 9:
        phone_digits = '0' + phone_digits
    return {
        'amount': f'{Decimal(amount):.2f}',
        'currency': getattr(settings, 'CHAPA_CURRENCY', 'ETB') or 'ETB',
        'email': _chapa_email(application),
        'first_name': first,
        'last_name': last,
        'phone_number': phone_digits[:10],
        'tx_ref': tx_ref,
        'callback_url': callback_url,
        'return_url': return_url,
        'customization': {
            'title': 'DECSI apply fee',  # 15 chars; Chapa max 16
            'description': _chapa_plain(f'Processing fee {tx_ref}', max_len=50, fallback='Processing fee'),
        },
        'meta': {
            'application_id': str(application.public_id),
            'hide_receipt': True,
        },
    }


def initialize_checkout(application, *, request=None) -> Tuple[bool, str, Optional[str]]:
    """
    Create a Chapa checkout session (or mock).
    Returns (ok, message, checkout_url).
    """
    from applicant_portal.models import OnlineApplication

    amount = application.processing_fee_amount
    if amount is None or amount <= 0:
        return True, 'No fee due.', None

    if application.payment_status == OnlineApplication.PAY_PAID:
        return True, 'Already paid.', None

    tx_ref = make_tx_ref(application)
    return_url = payment_return_url(application, tx_ref, request=request)
    callback_url = payment_callback_url(request=request)

    application.chapa_tx_ref = tx_ref
    application.payment_method = 'chapa'
    application.payment_status = OnlineApplication.PAY_PENDING
    application.payment_reference = tx_ref[:64]

    if not chapa_live_enabled():
        mock_url = f'{return_url}&status=success&mock=1'
        application.chapa_checkout_url = mock_url
        application.save(update_fields=[
            'chapa_tx_ref', 'chapa_checkout_url', 'payment_method',
            'payment_status', 'payment_reference', 'updated_at',
        ])
        return True, 'Mock checkout ready (Chapa not configured).', mock_url

    payload = build_initialize_payload(
        application,
        tx_ref=tx_ref,
        return_url=return_url,
        callback_url=callback_url,
    )
    headers = {
        'Authorization': f'Bearer {chapa_secret_key()}',
        'Content-Type': 'application/json',
    }
    try:
        resp = requests.post(CHAPA_INIT_URL, json=payload, headers=headers, timeout=25)
        data = resp.json() if resp.content else {}
    except requests.RequestException as exc:
        logger.exception('Chapa initialize network error: %s', exc)
        application.payment_status = OnlineApplication.PAY_FAILED
        application.save(update_fields=['payment_status', 'chapa_tx_ref', 'payment_method', 'payment_reference', 'updated_at'])
        return False, 'Could not reach Chapa. Try again in a moment.', None

    if resp.status_code >= 400 or (data.get('status') or '').lower() != 'success':
        msg = data.get('message') or data.get('message') or f'Chapa error HTTP {resp.status_code}'
        if isinstance(msg, dict):
            msg = '; '.join(f'{k}: {v}' for k, v in msg.items())
        logger.warning('Chapa initialize failed: %s %s', resp.status_code, data)
        application.payment_status = OnlineApplication.PAY_FAILED
        application.save(update_fields=[
            'payment_status', 'chapa_tx_ref', 'payment_method', 'payment_reference', 'updated_at',
        ])
        return False, str(msg)[:240], None

    checkout = (data.get('data') or {}).get('checkout_url') or ''
    if not checkout:
        application.payment_status = OnlineApplication.PAY_FAILED
        application.save(update_fields=['payment_status', 'updated_at'])
        return False, 'Chapa did not return a checkout URL.', None

    application.chapa_checkout_url = checkout[:500]
    application.save(update_fields=[
        'chapa_tx_ref', 'chapa_checkout_url', 'payment_method',
        'payment_status', 'payment_reference', 'updated_at',
    ])
    return True, 'Redirecting to Chapa…', checkout


def inline_checkout_config(application, *, request=None) -> Optional[dict]:
    """Config for Chapa Inline.js so the applicant stays on Digital Apply."""
    if not chapa_live_enabled() or not chapa_public_key():
        return None
    if not application.chapa_tx_ref:
        return None
    tx_ref = application.chapa_tx_ref
    payload = build_initialize_payload(
        application,
        tx_ref=tx_ref,
        return_url=payment_return_url(application, tx_ref, request=request),
        callback_url=payment_callback_url(request=request),
    )
    return {
        'publicKey': chapa_public_key(),
        'amount': payload['amount'],
        'currency': payload['currency'],
        'email': payload['email'],
        'firstName': payload['first_name'],
        'lastName': payload['last_name'],
        'phoneNumber': payload.get('phone_number') or '',
        'txRef': tx_ref,
        'callbackUrl': payload['callback_url'],
        'returnUrl': payload['return_url'],
        'checkoutUrl': (application.chapa_checkout_url or '')[:500],
    }


def tx_ref_from_request(request, application=None) -> str:
    """Chapa return/callback may send tx_ref or trx_ref."""
    get = getattr(request, 'GET', {})
    post = getattr(request, 'POST', {})
    raw = (
        get.get('tx_ref')
        or get.get('trx_ref')
        or post.get('tx_ref')
        or post.get('trx_ref')
        or ''
    )
    return (raw or getattr(application, 'chapa_tx_ref', '') or '').strip()


def verify_transaction(tx_ref: str) -> Tuple[bool, Dict[str, Any]]:
    """Verify payment with Chapa (or mock success when not live)."""
    tx_ref = (tx_ref or '').strip()
    if not tx_ref:
        return False, {'message': 'Missing transaction reference.'}

    if not chapa_live_enabled():
        return True, {
            'status': 'success',
            'data': {
                'status': 'success',
                'tx_ref': tx_ref,
                'reference': f'MOCK-{tx_ref[-10:]}',
            },
            'mock': True,
        }

    headers = {'Authorization': f'Bearer {chapa_secret_key()}'}
    url = CHAPA_VERIFY_URL.format(tx_ref=tx_ref)
    try:
        resp = requests.get(url, headers=headers, timeout=25)
        data = resp.json() if resp.content else {}
    except requests.RequestException as exc:
        logger.exception('Chapa verify network error: %s', exc)
        return False, {'message': str(exc)}

    ok = (
        resp.status_code == 200
        and (data.get('status') or '').lower() == 'success'
        and ((data.get('data') or {}).get('status') or '').lower() in ('success', 'successful')
    )
    return ok, data


def apply_verified_payment(application, tx_ref: str = '', chapa_data: Optional[dict] = None) -> bool:
    """Mark application paid when verification succeeds. Idempotent."""
    from applicant_portal.models import OnlineApplication

    if application.payment_status == OnlineApplication.PAY_PAID:
        return True

    data = (chapa_data or {}).get('data') or {}
    ref = (
        data.get('reference')
        or data.get('tx_ref')
        or tx_ref
        or application.chapa_tx_ref
        or ''
    )
    application.payment_status = OnlineApplication.PAY_PAID
    application.payment_method = 'chapa'
    application.payment_reference = str(ref)[:64]
    application.payment_paid_at = timezone.now()
    if tx_ref and not application.chapa_tx_ref:
        application.chapa_tx_ref = tx_ref[:64]
    if application.status in (OnlineApplication.STATUS_DOCUMENTS, OnlineApplication.STATUS_DRAFT):
        application.status = OnlineApplication.STATUS_PAYMENT
    application.save(update_fields=[
        'payment_status', 'payment_method', 'payment_reference', 'payment_paid_at',
        'chapa_tx_ref', 'status', 'updated_at',
    ])
    return True
