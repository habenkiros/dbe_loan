"""CBS / Temenos-style client: customer outstanding + loan disbursement booking.

Follows the same DECSI_BASE_URL pattern as party customer lookup.
Paths are env-overridable; when base URL is unset (or force-mock), deterministic
mocks keep local/dev and tests working offline.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass
class OutstandingResult:
    customer_number: str
    total_outstanding: Decimal
    active_loans: int = 0
    npl_amount: Decimal = Decimal('0')
    currency: str = 'ETB'
    provider: str = 'mock'
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BookDisbursementResult:
    ok: bool
    booking_ref: str = ''
    loan_account: str = ''
    status: str = ''  # booked | failed | mock | skipped
    message: str = ''
    provider: str = 'mock'
    raw: Dict[str, Any] = field(default_factory=dict)


def cbs_base_url() -> str:
    return (getattr(settings, 'DECSI_BASE_URL', None) or '').rstrip('/')


def cbs_force_mock() -> bool:
    return bool(getattr(settings, 'DECSI_CBS_FORCE_MOCK', False)) or bool(
        getattr(settings, 'DECSI_CUSTOMER_FORCE_MOCK', False)
    )


def cbs_enabled() -> bool:
    """True when live CBS mode is intended (base URL set and not force-mock)."""
    if getattr(settings, 'DECSI_CBS_ENABLED', None) is False:
        return False
    if cbs_force_mock():
        # Mock adapter still "connected" for demo when DECSI_CBS_USE_MOCK_LEDGER
        return bool(getattr(settings, 'DECSI_CBS_USE_MOCK_LEDGER', True))
    if cbs_base_url():
        return True
    return bool(getattr(settings, 'DECSI_CBS_USE_MOCK_LEDGER', True))


def _timeout() -> int:
    return int(getattr(settings, 'DECSI_CBS_TIMEOUT', getattr(settings, 'DECSI_CUSTOMER_TIMEOUT', 8)))


def _headers() -> Dict[str, str]:
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    api_key = (getattr(settings, 'DECSI_CBS_API_KEY', None) or '').strip()
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    return headers


def _path(template_setting: str, default: str, **fmt) -> str:
    tmpl = getattr(settings, template_setting, None) or default
    return tmpl.format(**fmt)


def _money(v) -> Decimal:
    try:
        return Decimal(str(v or 0)).quantize(Decimal('0.01'))
    except Exception:
        return Decimal('0.00')


def mock_fetch_customer_outstanding(customer_number: str) -> Optional[OutstandingResult]:
    cid = (customer_number or '').strip()
    if not cid or cid.upper() in ('MISSING', 'NONE', '0'):
        return None
    digest = int(hashlib.sha256(cid.encode('utf-8')).hexdigest()[:8], 16)
    outstanding = Decimal(str((digest % 900_000) + 10_000))
    npl = Decimal('0') if digest % 5 else (outstanding * Decimal('0.12')).quantize(Decimal('0.01'))
    active = 1 + (digest % 3)
    return OutstandingResult(
        customer_number=cid,
        total_outstanding=outstanding,
        active_loans=active,
        npl_amount=npl,
        provider='mock',
        raw={'mock': True, 'customer_number': cid},
    )


def live_fetch_customer_outstanding(customer_number: str) -> Optional[OutstandingResult]:
    base = cbs_base_url()
    if not base:
        return None
    cid = (customer_number or '').strip()
    if not cid:
        return None
    path = _path(
        'DECSI_OUTSTANDING_PATH',
        '/getCusByCusNo/api/v1.0.0/party/custid/{cid}/outstanding',
        cid=cid,
    )
    url = f'{base}{path}' if path.startswith('/') else f'{base}/{path}'
    try:
        response = requests.get(url, headers=_headers(), timeout=_timeout())
    except requests.RequestException as exc:
        logger.warning('CBS outstanding lookup failed for %s: %s', cid, exc)
        return None
    if response.status_code != 200:
        logger.info('CBS outstanding HTTP %s for %s', response.status_code, cid)
        return None
    try:
        data = response.json()
    except ValueError:
        return None

    body = data.get('body', data)
    if isinstance(body, list):
        body = body[0] if body else {}
    if not isinstance(body, dict):
        return None
    if data.get('header', {}).get('status') not in (None, 'success', 'Success', 'ok'):
        # Some gateways omit header; allow if outstanding field present
        if 'totalOutstanding' not in body and 'outstanding' not in body and 'total_outstanding' not in body:
            return None

    total = (
        body.get('total_outstanding')
        or body.get('totalOutstanding')
        or body.get('outstanding')
        or body.get('balance')
        or 0
    )
    npl = body.get('npl_amount') or body.get('nplAmount') or body.get('npl') or 0
    active = body.get('active_loans') or body.get('activeLoans') or body.get('loanCount') or 0
    return OutstandingResult(
        customer_number=cid,
        total_outstanding=_money(total),
        active_loans=int(active or 0),
        npl_amount=_money(npl),
        currency=str(body.get('currency') or 'ETB'),
        provider='decsi_cbs',
        raw=body if isinstance(body, dict) else {'body': body},
    )


def fetch_customer_outstanding(customer_number: str) -> Optional[OutstandingResult]:
    """Live outstanding when DECSI_BASE_URL set; else mock (for demo/CI)."""
    force_mock = cbs_force_mock()
    base = cbs_base_url()
    if base and not force_mock:
        result = live_fetch_customer_outstanding(customer_number)
        if result:
            return result
        if not getattr(settings, 'DECSI_CUSTOMER_FALLBACK_MOCK', True):
            return None
        mock = mock_fetch_customer_outstanding(customer_number)
        if mock:
            mock.provider = 'mock_fallback'
        return mock
    return mock_fetch_customer_outstanding(customer_number)


def mock_book_disbursement(payload: Dict[str, Any]) -> BookDisbursementResult:
    cid = str(payload.get('customer_number') or '').strip() or 'UNKNOWN'
    loan_id = str(payload.get('loan_request_id') or payload.get('external_ref') or 'LR')
    digest = hashlib.sha256(f'{cid}:{loan_id}'.encode('utf-8')).hexdigest()[:10].upper()
    ref = f'MOCK-DISB-{digest}'
    account = f'LA-{_digits(cid)[-6:].zfill(6)}-{digest[:4]}'
    return BookDisbursementResult(
        ok=True,
        booking_ref=ref,
        loan_account=account,
        status='mock',
        message='Mock CBS booking succeeded (DECSI_BASE_URL unset or force-mock).',
        provider='mock',
        raw={'mock': True, 'payload': payload, 'booked_at': timezone.now().isoformat()},
    )


def live_book_disbursement(payload: Dict[str, Any]) -> BookDisbursementResult:
    base = cbs_base_url()
    if not base:
        return BookDisbursementResult(ok=False, status='failed', message='DECSI_BASE_URL not configured.')
    path = getattr(settings, 'DECSI_DISBURSE_PATH', None) or '/loanDisburse/api/v1.0.0/loans/disburse'
    url = f'{base}{path}' if path.startswith('/') else f'{base}/{path}'
    try:
        response = requests.post(url, json=payload, headers=_headers(), timeout=_timeout())
    except requests.RequestException as exc:
        logger.warning('CBS disburse failed: %s', exc)
        return BookDisbursementResult(
            ok=False, status='failed', message=f'CBS connection error: {exc}', provider='decsi_cbs',
        )
    try:
        data = response.json() if response.content else {}
    except ValueError:
        data = {'raw_text': (response.text or '')[:500]}

    if response.status_code not in (200, 201):
        msg = (
            (data.get('header') or {}).get('statusDesc')
            or data.get('message')
            or data.get('error')
            or f'HTTP {response.status_code}'
        )
        return BookDisbursementResult(
            ok=False, status='failed', message=str(msg), provider='decsi_cbs', raw=data if isinstance(data, dict) else {},
        )

    body = data.get('body', data) if isinstance(data, dict) else {}
    if isinstance(body, list):
        body = body[0] if body else {}
    if not isinstance(body, dict):
        body = {}
    header_status = (data.get('header') or {}).get('status') if isinstance(data, dict) else None
    if header_status and str(header_status).lower() not in ('success', 'ok', 'booked'):
        msg = (data.get('header') or {}).get('statusDesc') or 'CBS rejected booking'
        return BookDisbursementResult(
            ok=False, status='failed', message=str(msg), provider='decsi_cbs', raw=data,
        )

    ref = (
        body.get('booking_ref')
        or body.get('bookingRef')
        or body.get('transactionId')
        or body.get('txnId')
        or body.get('reference')
        or ''
    )
    account = (
        body.get('loan_account')
        or body.get('loanAccount')
        or body.get('accountNumber')
        or body.get('accountNo')
        or ''
    )
    return BookDisbursementResult(
        ok=True,
        booking_ref=str(ref),
        loan_account=str(account),
        status='booked',
        message='CBS disbursement booked.',
        provider='decsi_cbs',
        raw=body,
    )


def book_disbursement(payload: Dict[str, Any]) -> BookDisbursementResult:
    """Book a loan disbursement in CBS (live or mock)."""
    force_mock = cbs_force_mock()
    base = cbs_base_url()
    if base and not force_mock:
        result = live_book_disbursement(payload)
        if result.ok or not getattr(settings, 'DECSI_CUSTOMER_FALLBACK_MOCK', True):
            return result
        # Fallback mock only when allowed (demo)
        mock = mock_book_disbursement(payload)
        mock.provider = 'mock_fallback'
        mock.message = f'Live CBS failed ({result.message}); used mock fallback.'
        mock.raw['live_error'] = result.message
        return mock
    return mock_book_disbursement(payload)


def build_disbursement_payload(loan_request, user, *, notes: str = '') -> Dict[str, Any]:
    from loans.disbursement import final_annual_rate_pct, final_loan_amount, final_term_months

    amount = final_loan_amount(loan_request)
    return {
        'external_ref': loan_request.loan_request_id,
        'loan_request_id': loan_request.loan_request_id,
        'hub_loan_pk': loan_request.pk,
        'customer_number': (loan_request.customer_number or '').strip(),
        'applicant_name': loan_request.applicant_name,
        'amount': float(amount),
        'currency': 'ETB',
        'term_months': final_term_months(loan_request),
        'annual_rate_pct': float(final_annual_rate_pct(loan_request)),
        'branch_code': getattr(loan_request.branch, 'code', None) or (
            str(loan_request.branch_id) if loan_request.branch_id else ''
        ),
        'branch_name': loan_request.branch.name if loan_request.branch_id else '',
        'officer_username': getattr(user, 'username', ''),
        'notes': notes or '',
        'requested_at': timezone.now().isoformat(),
    }


def _digits(value: str) -> str:
    return ''.join(ch for ch in str(value or '') if ch.isdigit())
