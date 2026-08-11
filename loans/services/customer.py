"""Core banking / party customer lookup for loan intake and Sheet 1 prefill."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _digits_only(value: str) -> str:
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def customer_api_is_live() -> bool:
    """True when DECSI party API base URL is configured and mock is not forced."""
    base = (getattr(settings, 'DECSI_BASE_URL', None) or '').strip()
    force_mock = getattr(settings, 'DECSI_CUSTOMER_FORCE_MOCK', False)
    return bool(base) and not force_mock


def normalize_customer_profile(raw: Dict[str, Any], *, customer_number: str = '') -> Dict[str, Any]:
    """Normalize party/API payloads into a stable profile for Sheet 1 + portal."""
    if not raw:
        return {}
    customer_number = (
        raw.get('customer_number')
        or raw.get('customerId')
        or raw.get('custId')
        or raw.get('customerNo')
        or raw.get('CUSTOMER_ID')
        or customer_number
        or ''
    )
    name = (
        raw.get('name')
        or raw.get('customerName')
        or raw.get('fullName')
        or raw.get('FULL_NAME')
        or raw.get('customer_name')
        or ''
    )
    if not name:
        first = str(raw.get('firstName') or raw.get('FIRST_NAME') or '').strip()
        last = str(raw.get('lastName') or raw.get('LAST_NAME') or '').strip()
        name = f'{first} {last}'.strip()
    phone = (
        raw.get('phone_number')
        or raw.get('phoneNumber')
        or raw.get('mobile')
        or raw.get('MOBILE_NO')
        or raw.get('mobileNumber')
        or raw.get('tel')
        or ''
    )
    tin = raw.get('tin_number') or raw.get('tin') or raw.get('taxId') or raw.get('TIN_NO') or ''
    address = (
        raw.get('home_address')
        or raw.get('address')
        or raw.get('residentialAddress')
        or raw.get('HOME_ADDR')
        or raw.get('residenceAddress')
        or ''
    )
    gender = raw.get('gender') or raw.get('GENDER') or ''
    status = raw.get('status') or raw.get('customerType') or raw.get('CUSTOMER_STATUS') or ''
    email = raw.get('email') or raw.get('emailAddress') or raw.get('EMAIL') or ''
    city = raw.get('city') or raw.get('CITY') or raw.get('town') or ''
    branch_code = raw.get('branch_code') or raw.get('branchCode') or raw.get('BOOKING_BRANCH') or ''
    return {
        'customer_number': str(customer_number).strip(),
        'name': str(name).strip(),
        'phone_number': str(phone).strip(),
        'tin_number': str(tin).strip(),
        'home_address': str(address).strip(),
        'gender': str(gender).strip(),
        'status': str(status).strip(),
        'email': str(email).strip(),
        'city': str(city).strip(),
        'branch_code': str(branch_code).strip(),
        'provider': raw.get('provider') or 'core_banking',
        'raw_keys': sorted(str(k) for k in raw.keys())[:40] if isinstance(raw, dict) else [],
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
        'email': f'customer{_digits_only(cid)[-4:] or "0000"}@demo.local',
        'provider': 'mock',
    })


def live_fetch_customer_by_number(customer_number: str) -> Optional[Dict[str, Any]]:
    base = (getattr(settings, 'DECSI_BASE_URL', None) or '').rstrip('/')
    if not base:
        return None
    cid = (customer_number or '').strip()
    if not cid:
        return None
    path = getattr(
        settings,
        'DECSI_CUSTOMER_DETAIL_PATH',
        '/getCusByCusNo/api/v1.0.0/party/custid/{cid}/custdets',
    )
    url = f'{base}{path.format(cid=cid)}'
    timeout = getattr(settings, 'DECSI_CUSTOMER_TIMEOUT', 8)
    headers = {}
    api_key = (getattr(settings, 'DECSI_CBS_API_KEY', '') or '').strip()
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
        headers['X-API-Key'] = api_key
    try:
        response = requests.get(url, timeout=timeout, headers=headers or None)
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
    body = data.get('body') if isinstance(data, dict) else None
    if body is None and isinstance(data, dict):
        if data.get('data'):
            body = data['data']
        elif data.get('customer') or data.get('customerName') or data.get('name'):
            body = data
    header_status = ''
    if isinstance(data, dict):
        header_status = str((data.get('header') or {}).get('status') or data.get('status') or '').lower()
    if header_status and header_status not in ('success', 'ok', '0', 'true', '1'):
        if header_status in ('error', 'fail', 'failed', 'not_found'):
            return None
    if not body:
        return None
    row = body[0] if isinstance(body, list) else body
    if not isinstance(row, dict):
        return None
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
        if not getattr(settings, 'DECSI_CUSTOMER_FALLBACK_MOCK', True):
            return None
    return mock_fetch_customer_by_number(customer_number)


def portal_customer_lookup(
    customer_number: str,
    *,
    require: Optional[bool] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Lookup for digital-apply registration.
    Returns (profile_or_None, message).
    When DECSI API is live (or require=True), missing customers are errors.
    """
    from applicant_portal.security import get_portal_settings

    cn = (customer_number or '').strip()
    if not cn:
        return None, 'Enter a customer number.'

    if require is None:
        policy = get_portal_settings()
        require = bool(policy.require_customer_lookup) or customer_api_is_live()

    if customer_api_is_live():
        profile = live_fetch_customer_by_number(cn)
        if profile:
            return profile, 'Customer found in DECSI core banking.'
        if require:
            return None, (
                'Customer number not found in DECSI core banking. '
                'Confirm the number at your branch.'
            )
        return None, 'Customer not found; continuing without core-banking details.'

    profile = fetch_customer_by_number(cn)
    if profile:
        live_note = 'mock' if profile.get('provider') == 'mock' else profile.get('provider', 'core')
        return profile, f'Customer profile loaded ({live_note}).'
    if require:
        return None, 'Customer number not found. Check the number or visit your branch.'
    return None, 'No customer profile available.'


def apply_profile_to_account_fields(profile: Dict[str, Any]) -> Dict[str, str]:
    """Map CBS profile to portal account field values."""
    if not profile:
        return {}
    out: Dict[str, str] = {}
    if profile.get('name'):
        out['full_name'] = str(profile['name'])[:255]
    if profile.get('phone_number'):
        out['phone_number'] = str(profile['phone_number'])[:30]
    if profile.get('email'):
        out['email'] = str(profile['email'])[:254]
    if profile.get('customer_number'):
        out['customer_number'] = str(profile['customer_number'])[:50]
    return out


def refresh_customer_profile_for_account(account) -> Optional[Dict[str, Any]]:
    """Re-fetch CBS profile, update snapshot (+ optional name)."""
    cn = (getattr(account, 'customer_number', None) or '').strip()
    if not cn:
        return None
    profile, _msg = portal_customer_lookup(cn, require=False)
    if not profile:
        return None
    account.customer_profile_snapshot = profile
    fields = ['customer_profile_snapshot', 'updated_at']
    bank_name = (profile.get('name') or '').strip()
    if bank_name and len(bank_name) >= 3:
        account.full_name = bank_name[:255]
        fields.append('full_name')
    bank_email = (profile.get('email') or '').strip()
    if bank_email and not (account.email or '').strip():
        account.email = bank_email[:254]
        fields.append('email')
    account.save(update_fields=fields)
    return profile
