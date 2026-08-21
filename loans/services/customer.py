"""Core banking / party customer lookup for loan intake and digital apply.

Sample DECSI Temenos party API (see docs/customer API.txt):

  GET {DECSI_BASE_URL}/getCusByCusNo/api/v1.0.0/party/custid/{cid}/custdets

  Customer example: 2000050041
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import requests
from django.conf import settings

from loans.services.mock_customers import SAMPLE_CUSTOMER_ID, build_mock_party_body

logger = logging.getLogger(__name__)


def _digits_only(value: str) -> str:
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def profile_data_source(profile: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """UI badge metadata for customer / banking profile origin."""
    if not profile:
        return {'code': 'none', 'label': 'No profile', 'tone': 'muted'}
    provider = (profile.get('provider') or '').strip().lower()
    if provider in ('decsi_party', 'decsi_cbs', 'live'):
        return {'code': 'live', 'label': 'Live core banking', 'tone': 'ok'}
    if provider in ('mock_fallback',) or profile.get('live_attempted'):
        return {
            'code': 'fallback',
            'label': 'Mock — live API failed',
            'tone': 'warn',
        }
    return {'code': 'mock', 'label': 'Demo / mock data', 'tone': 'muted'}


def compact_customer_profile(profile: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Keep only staff-important party fields (no email)."""
    if not profile:
        return {}
    out: Dict[str, str] = {}
    key_order = (
        ('customer_number', 'Customer no.'),
        ('phone_number', 'Phone'),
        ('phone_raw', 'Phone (raw)'),
        ('gender', 'Gender'),
        ('date_of_birth', 'Date of birth'),
        ('age', 'Age'),
        ('marital_status', 'Marital status'),
        ('status', 'Customer type'),
        ('customer_status', 'Customer rating'),
        ('home_address', 'Address'),
        ('city', 'Region / town'),
        ('street', 'Street'),
        ('branch_code', 'Account officer'),
        ('mnemonic', 'Mnemonic'),
        ('title', 'Title'),
        ('country', 'Country'),
        ('provider', 'Source'),
    )
    # Prefer normalized phone over raw
    for key, _label in key_order:
        if key == 'phone_raw' and profile.get('phone_number'):
            continue
        val = profile.get(key)
        if val is None or val == '':
            continue
        s = str(val).strip()
        if not s or s.upper() in ('NULL', 'NONE', 'N/A'):
            continue
        out[key] = s[:500]
    ds = profile.get('data_source')
    if isinstance(ds, dict) and ds.get('label'):
        out['data_source_label'] = str(ds['label'])[:120]
        if ds.get('code'):
            out['data_source_code'] = str(ds['code'])[:40]
    elif profile.get('provider') or profile.get('live_attempted'):
        meta = profile_data_source(profile)
        out['data_source_label'] = meta['label']
        out['data_source_code'] = meta['code']
    return out


def loan_cbs_highlights(loan) -> Dict[str, str]:
    """
    Resolve important CBS fields for a LoanRequest:
    stored snapshot → digital-apply account snapshot → empty.
    """
    snap = getattr(loan, 'customer_profile_snapshot', None) or {}
    if isinstance(snap, dict) and snap:
        c = compact_customer_profile(snap)
        if c:
            return c
        c = compact_customer_profile(normalize_customer_profile(snap))
        if c:
            return c

    try:
        app = loan.online_application
    except Exception:
        app = None
    if app is not None:
        account = getattr(app, 'applicant', None)
        full = getattr(account, 'customer_profile_snapshot', None) or {}
        if isinstance(full, dict) and full:
            c = compact_customer_profile(full)
            if c:
                return c
            return compact_customer_profile(normalize_customer_profile(full))
    return {}


def attach_profile_snapshot_to_loan(loan, profile: Optional[Dict[str, Any]]) -> bool:
    """Persist important API fields on the loan (no email)."""
    compact = compact_customer_profile(profile)
    if not compact:
        return False
    loan.customer_profile_snapshot = compact
    return True


def customer_api_is_live() -> bool:
    """True when DECSI party API base URL is configured and mock is not forced."""
    base = (getattr(settings, 'DECSI_BASE_URL', None) or '').strip()
    force_mock = getattr(settings, 'DECSI_CUSTOMER_FORCE_MOCK', False)
    return bool(base) and not force_mock


def _build_address(raw: Dict[str, Any]) -> str:
    parts = []
    for key in (
        'street', 'suburbTown', 'cityMunicipal', 'countryCode',
        'home_address', 'address', 'residentialAddress', 'HOME_ADDR',
    ):
        val = str(raw.get(key) or '').strip()
        if val and val.upper() not in ('NULL', 'NONE', 'N/A') and val not in parts:
            parts.append(val)
    return ', '.join(parts)


def _normalize_et_mobile(raw_phone: str) -> str:
    """Turn DECSI phone (e.g. 945517351) into portal local 09… / 07… when possible."""
    digits = _digits_only(raw_phone)
    if not digits:
        return ''
    if digits.startswith('251') and len(digits) >= 12:
        digits = digits[3:]
    if len(digits) == 9 and digits[0] in ('9', '7'):
        return '0' + digits
    if len(digits) == 10 and digits[0] == '0' and digits[1] in ('9', '7'):
        return digits
    return digits


def normalize_customer_profile(raw: Dict[str, Any], *, customer_number: str = '') -> Dict[str, Any]:
    """Normalize DECSI / Temenos party payloads into a stable profile.

    Maps the real DECSI fields from docs/customer API.txt, e.g.:
      customerId, code, name, firstName, familyName, phoneNumber, sms,
      street, suburbTown, cityMunicipal, customerType, customerStatus,
      gender, dateOfBirth, age, maritalStatus, mnemonic, accountOfficer
    """
    if not raw:
        return {}

    customer_number = str(
        raw.get('customerId')
        or raw.get('code')
        or raw.get('customer_number')
        or raw.get('custId')
        or raw.get('customerNo')
        or raw.get('CUSTOMER_ID')
        or customer_number
        or ''
    ).strip()

    name = str(
        raw.get('name')
        or raw.get('shortName')
        or raw.get('givenName')
        or raw.get('firstName')
        or raw.get('customerName')
        or raw.get('fullName')
        or raw.get('FULL_NAME')
        or ''
    ).strip()
    if not name:
        first = str(raw.get('firstName') or raw.get('givenName') or '').strip()
        family = str(raw.get('familyName') or raw.get('lastName') or '').strip()
        name = f'{first} {family}'.strip() if first or family else ''

    phone_raw = (
        raw.get('phoneNumber')
        or raw.get('sms')
        or raw.get('phone_number')
        or raw.get('mobile')
        or raw.get('MOBILE_NO')
        or raw.get('mobileNumber')
        or raw.get('tel')
        or ''
    )
    phone = _normalize_et_mobile(str(phone_raw))

    tin = str(
        raw.get('tin_number') or raw.get('tin') or raw.get('taxId') or raw.get('TIN_NO') or ''
    ).strip()
    address = _build_address(raw)
    gender = str(raw.get('gender') or raw.get('GENDER') or '').strip()
    # DECSI uses customerType = ACTIVE and customerStatus = rating text
    status = str(
        raw.get('customerType')
        or raw.get('status')
        or raw.get('CUSTOMER_STATUS')
        or ''
    ).strip()
    customer_status = str(raw.get('customerStatus') or '').strip()
    email = str(raw.get('email') or raw.get('emailAddress') or raw.get('EMAIL') or '').strip()
    city = str(
        raw.get('suburbTown')
        or raw.get('cityMunicipal')
        or raw.get('city')
        or raw.get('CITY')
        or raw.get('town')
        or ''
    ).strip()
    branch_code = str(
        raw.get('accountOfficer')
        or raw.get('branch_code')
        or raw.get('branchCode')
        or raw.get('BOOKING_BRANCH')
        or ''
    ).strip()

    date_of_birth = str(raw.get('dateOfBirth') or raw.get('birthIncorpDate') or '').strip()
    age = str(raw.get('age') or '').strip()
    marital_status = str(raw.get('maritalStatus') or '').strip()
    title = str(raw.get('title') or '').strip()
    sector = str(raw.get('sector') or '').strip()
    industry = str(raw.get('industry') or '').strip()
    mnemonic = str(raw.get('mnemonic') or '').strip()
    country = str(raw.get('countryCode') or raw.get('residence') or '').strip()

    return {
        'customer_number': customer_number,
        'name': name,
        'phone_number': phone,
        'phone_raw': str(phone_raw).strip(),
        'tin_number': tin,
        'home_address': address,
        'gender': gender,
        'status': status,
        'customer_status': customer_status,
        'email': email,
        'city': city,
        'branch_code': branch_code,
        'date_of_birth': date_of_birth,
        'age': age,
        'marital_status': marital_status,
        'title': title,
        'sector': sector,
        'industry': industry,
        'mnemonic': mnemonic,
        'country': country,
        'street': str(raw.get('street') or '').strip(),
        'provider': raw.get('provider') or 'core_banking',
        'raw_keys': sorted(str(k) for k in raw.keys())[:50] if isinstance(raw, dict) else [],
    }


def _sample_decsi_body(customer_number: str) -> Dict[str, Any]:
    """Party API body: catalog mock (Tekeste, Samrawit, …) or generic DEMO."""
    catalog = build_mock_party_body(customer_number)
    if catalog:
        return catalog
    digits = _digits_only(customer_number) or '0'
    return {
        'customerId': customer_number,
        'code': customer_number,
        'name': f'DEMO Customer {customer_number}',
        'firstName': f'DEMO Customer {customer_number}',
        'phoneNumber': '911000' + digits[-3:].zfill(3),
        'sms': '911000' + digits[-3:].zfill(3),
        'tin': f'00{digits.zfill(8)[-8:]}',
        'street': 'Mekelle, Tigray (mock core banking)',
        'suburbTown': 'Tigray',
        'cityMunicipal': 'Ethiopia',
        'countryCode': 'ET',
        'customerType': 'ACTIVE',
        'customerStatus': 'Standard Rated - Private Client',
        'gender': 'MALE',
        'provider': 'mock',
    }


def mock_fetch_customer_by_number(customer_number: str) -> Optional[Dict[str, Any]]:
    """
    Deterministic mock for local/dev when DECSI_BASE_URL is unset.
    Catalog: docs/customer API.txt + mock_customers (Samrawit and others).
    """
    cid = (customer_number or '').strip()
    if not cid:
        return None
    if cid.upper() in ('MISSING', 'NONE', '0'):
        return None
    profile = normalize_customer_profile(_sample_decsi_body(cid), customer_number=cid)
    profile['provider'] = 'mock'
    return profile


def live_fetch_customer_by_number(customer_number: str) -> Optional[Dict[str, Any]]:
    """
    Live GET:
      {DECSI_BASE_URL}/getCusByCusNo/api/v1.0.0/party/custid/{cid}/custdets
    Optional shorter path: base_url/getCusByCusNo/api  (set DECSI_CUSTOMER_DETAIL_PATH).
    """
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
        elif data.get('customer') or data.get('customerName') or data.get('name') or data.get('customerId'):
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
            profile['data_source'] = profile_data_source(profile)
            return profile
        if not getattr(settings, 'DECSI_CUSTOMER_FALLBACK_MOCK', True):
            return None
        mock = mock_fetch_customer_by_number(customer_number)
        if mock:
            mock['provider'] = 'mock_fallback'
            mock['live_attempted'] = True
            mock['data_source'] = profile_data_source(mock)
        return mock
    mock = mock_fetch_customer_by_number(customer_number)
    if mock:
        mock.setdefault('provider', 'mock')
        mock['data_source'] = profile_data_source(mock)
    return mock


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
