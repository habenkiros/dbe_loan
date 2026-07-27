"""Core banking / party customer lookup for loan intake and Sheet 1 prefill."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _digits_only(value: str) -> str:
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def normalize_customer_profile(raw: Dict[str, Any], *, customer_number: str = '') -> Dict[str, Any]:
    """Normalize party/API payloads into a stable profile for Sheet 1."""
    if not raw:
        return {}
    # Support both our wrapper shape and a raw Temenos-style body row.
    customer_number = (
        raw.get('customer_number')
        or raw.get('customerId')
        or raw.get('custId')
        or customer_number
        or ''
    )
    name = raw.get('name') or raw.get('customerName') or raw.get('fullName') or ''
    phone = raw.get('phone_number') or raw.get('phoneNumber') or raw.get('mobile') or ''
    tin = raw.get('tin_number') or raw.get('tin') or raw.get('taxId') or ''
    address = raw.get('home_address') or raw.get('address') or raw.get('residentialAddress') or ''
    gender = raw.get('gender') or ''
    status = raw.get('status') or raw.get('customerType') or ''
    return {
        'customer_number': str(customer_number).strip(),
        'name': str(name).strip(),
        'phone_number': str(phone).strip(),
        'tin_number': str(tin).strip(),
        'home_address': str(address).strip(),
        'gender': str(gender).strip(),
        'status': str(status).strip(),
        'provider': raw.get('provider') or 'core_banking',
    }


def mock_fetch_customer_by_number(customer_number: str) -> Optional[Dict[str, Any]]:
    """
    Deterministic mock for local/dev when DECSI_BASE_URL is unset.
    Use customer number DEMO / 1001 / any non-empty id.
    """
    cid = (customer_number or '').strip()
    if not cid:
        return None
    if cid.upper() in ('MISSING', 'NONE', '0'):
        return None
    return normalize_customer_profile({
        'customer_number': cid,
        'name': f'DEMO Customer {cid}',
        'phone_number': '0911000' + _digits_only(cid)[-4:].zfill(4),
        'tin_number': _digits_only(cid).zfill(10)[:10] or '0000000001',
        'home_address': 'Mekelle, Tigray (mock core banking)',
        'gender': 'Male',
        'status': 'ACTIVE',
        'provider': 'mock',
    })


def live_fetch_customer_by_number(customer_number: str) -> Optional[Dict[str, Any]]:
    base = (getattr(settings, 'DECSI_BASE_URL', None) or '').rstrip('/')
    if not base:
        return None
    cid = (customer_number or '').strip()
    if not cid:
        return None
    url = f'{base}/getCusByCusNo/api/v1.0.0/party/custid/{cid}/custdets'
    timeout = getattr(settings, 'DECSI_CUSTOMER_TIMEOUT', 8)
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning('Core banking lookup failed for %s: %s', cid, exc)
        return None
    if response.status_code != 200:
        logger.info('Core banking lookup HTTP %s for %s', response.status_code, cid)
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    if data.get('header', {}).get('status') != 'success' or not data.get('body'):
        return None
    row = data['body'][0] if isinstance(data['body'], list) else data['body']
    profile = normalize_customer_profile(row, customer_number=cid)
    profile['provider'] = 'decsi_party'
    return profile if profile.get('name') or profile.get('customer_number') else None


def fetch_customer_by_number(customer_number: str) -> Optional[Dict[str, Any]]:
    """
    Lookup customer by core-banking customer number.
    Uses live DECSI_BASE_URL when configured; otherwise returns a mock profile
    so Sheet 1 intake can be developed/tested offline.
    """
    base = (getattr(settings, 'DECSI_BASE_URL', None) or '').strip()
    force_mock = getattr(settings, 'DECSI_CUSTOMER_FORCE_MOCK', False)
    if base and not force_mock:
        profile = live_fetch_customer_by_number(customer_number)
        if profile:
            return profile
        # Fall through to mock only when explicitly allowed for demos.
        if not getattr(settings, 'DECSI_CUSTOMER_FALLBACK_MOCK', True):
            return None
    return mock_fetch_customer_by_number(customer_number)
