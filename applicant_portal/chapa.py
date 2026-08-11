"""Chapa payment gateway for digital-apply processing fees.

Docs: https://developer.chapa.co/docs
  POST /v1/transaction/initialize
  GET  /v1/transaction/verify/{tx_ref}
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

import requests
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

CHAPA_INIT_URL = 'https://api.chapa.co/v1/transaction/initialize'
CHAPA_VERIFY_URL = 'https://api.chapa.co/v1/transaction/verify/{tx_ref}'


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


def make_tx_ref(application) -> str:
    # Chapa prefers unique transaction references (max ~50).
    short = application.public_id.hex[:12]
    return f'DA-{short}-{uuid.uuid4().hex[:8]}'.upper()


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
    return_path = reverse(
        'applicant_portal:apply_payment_return',
        args=[application.public_id],
    )
    callback_path = reverse('applicant_portal:chapa_webhook')
    return_url = f'{_site_url()}{return_path}?tx_ref={tx_ref}'
    callback_url = f'{_site_url()}{callback_path}'

    application.chapa_tx_ref = tx_ref
    application.payment_method = 'chapa'
    application.payment_status = OnlineApplication.PAY_PENDING
    application.payment_reference = tx_ref[:64]

    if not chapa_live_enabled():
        mock_url = f'{_site_url()}{return_path}?tx_ref={tx_ref}&status=success&mock=1'
        application.chapa_checkout_url = mock_url
        application.save(update_fields=[
            'chapa_tx_ref', 'chapa_checkout_url', 'payment_method',
            'payment_status', 'payment_reference', 'updated_at',
        ])
        return True, 'Mock checkout ready (Chapa not configured).', mock_url

    phone = (application.phone_number or application.applicant.phone_number or '').strip()
    name = (application.applicant_name or application.applicant.full_name or 'Applicant').strip()
    parts = name.split(None, 1)
    first = parts[0][:50] if parts else 'Applicant'
    last = parts[1][:50] if len(parts) > 1 else 'Digital'
    email = (application.email or application.applicant.email or '').strip()
    if not email:
        # Chapa requires email; use a stable synthetic inbox per account.
        email = f'applicant+{application.applicant.public_id.hex[:12]}@apply.local'

    payload = {
        'amount': f'{Decimal(amount):.2f}',
        'currency': getattr(settings, 'CHAPA_CURRENCY', 'ETB') or 'ETB',
        'email': email,
        'first_name': first,
        'last_name': last,
        'phone_number': phone[:15] if phone else '',
        'tx_ref': tx_ref,
        'callback_url': callback_url,
        'return_url': return_url,
        'customization': {
            'title': 'Digital apply fee',
            'description': f'Processing fee · {tx_ref}',
        },
        'meta': {
            'application_id': str(application.public_id),
            'queue_ready': False,
        },
    }
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
