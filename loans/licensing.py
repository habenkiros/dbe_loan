"""
Offline on-prem product license (Ed25519-signed).

License string format:
  SEQLA1.<base64url(json_payload)>.<base64url(signature)>

Payload fields (JSON):
  iss, aud, org, org_code, iat (YYYY-MM-DD), exp (YYYY-MM-DD),
  features (list), note (optional)

Verification uses the embedded Seqela public key (no phone-home).
Issuance requires the private key (Seqela only): deploy/license/private_key.pem
"""
from __future__ import annotations

import base64
import json
import os
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from django.conf import settings
from django.utils import timezone

LICENSE_PREFIX = 'SEQLA1'
LICENSE_AUD = 'loan_hub'
LICENSE_ISS = 'seqela'

# Seqela product-signing public key (pair private key is NOT shipped to customers).
EMBEDDED_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEALLlW48Ia+9h0xVP7Q27dbslbZNfwzMECwdG5jOkGRVU=
-----END PUBLIC KEY-----
"""

_cache_lock = threading.Lock()
_cache: Dict[str, Any] = {'key': None, 'checked_at': None, 'status': None}


@dataclass(frozen=True)
class LicenseStatus:
    valid: bool
    enforced: bool
    present: bool
    expired: bool
    grace: bool
    org: str = ''
    org_code: str = ''
    issued_on: Optional[date] = None
    expires_on: Optional[date] = None
    days_remaining: Optional[int] = None
    features: Tuple[str, ...] = ()
    note: str = ''
    message: str = ''
    raw_error: str = ''

    @property
    def ok_to_run(self) -> bool:
        """True when the application may serve normal traffic."""
        if not self.enforced:
            return True
        return self.valid or self.grace


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('ascii').rstrip('=')


def _b64url_decode(data: str) -> bytes:
    pad = '=' * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _load_public_key(pem: Optional[bytes] = None) -> Ed25519PublicKey:
    raw = pem or getattr(settings, 'LICENSE_PUBLIC_KEY_PEM', None) or EMBEDDED_PUBLIC_KEY_PEM
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    key = serialization.load_pem_public_key(raw)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError('License public key must be Ed25519')
    return key


def _load_private_key(pem: Optional[bytes] = None) -> Ed25519PrivateKey:
    raw = pem
    if raw is None:
        env_pem = os.getenv('LICENSE_PRIVATE_KEY_PEM', '').strip()
        if env_pem:
            raw = env_pem.replace('\\n', '\n').encode('utf-8')
        else:
            path = os.getenv(
                'LICENSE_PRIVATE_KEY_PATH',
                str(Path(settings.BASE_DIR) / 'deploy' / 'license' / 'private_key.pem'),
            )
            raw = Path(path).read_bytes()
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    key = serialization.load_pem_private_key(raw, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError('License private key must be Ed25519')
    return key


def _parse_ymd(value: str) -> date:
    return datetime.strptime(value, '%Y-%m-%d').date()


def issue_license(
    *,
    org: str,
    org_code: str,
    expires_on: date,
    issued_on: Optional[date] = None,
    features: Optional[List[str]] = None,
    note: str = '',
    private_key_pem: Optional[bytes] = None,
) -> str:
    """Create a signed license string (Seqela ops only)."""
    iat = issued_on or timezone.localdate()
    if expires_on < iat:
        raise ValueError('expires_on must be on or after issued_on')
    payload = {
        'iss': LICENSE_ISS,
        'aud': LICENSE_AUD,
        'org': org.strip(),
        'org_code': org_code.strip().upper(),
        'iat': iat.isoformat(),
        'exp': expires_on.isoformat(),
        'features': features or ['hub', 'digital_apply', 'market', 'collateral'],
        'note': (note or '').strip(),
    }
    body = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode('utf-8')
    sig = _load_private_key(private_key_pem).sign(body)
    return f'{LICENSE_PREFIX}.{_b64url_encode(body)}.{_b64url_encode(sig)}'


def _read_license_key_from_env_or_file() -> str:
    key = (os.getenv('LICENSE_KEY') or getattr(settings, 'LICENSE_KEY', '') or '').strip()
    if key:
        return key
    path = (os.getenv('LICENSE_KEY_FILE') or getattr(settings, 'LICENSE_KEY_FILE', '') or '').strip()
    if path and Path(path).is_file():
        return Path(path).read_text(encoding='utf-8').strip()
    default = Path(settings.BASE_DIR) / 'deploy' / 'license' / 'license.key'
    if default.is_file():
        return default.read_text(encoding='utf-8').strip()
    return ''


def license_enforced() -> bool:
    """Enforce when LICENSE_ENFORCE is on, or when DEBUG is off (on-prem default)."""
    if getattr(settings, 'TESTING', False):
        return False
    raw = (os.getenv('LICENSE_ENFORCE') or getattr(settings, 'LICENSE_ENFORCE', '') or '').strip().lower()
    if raw in ('1', 'true', 'yes', 'on'):
        return True
    if raw in ('0', 'false', 'no', 'off'):
        return False
    return not bool(getattr(settings, 'DEBUG', False))


def grace_days() -> int:
    try:
        raw = os.getenv('LICENSE_GRACE_DAYS', None)
        if raw is None:
            raw = getattr(settings, 'LICENSE_GRACE_DAYS', 7)
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 7


def verify_license_string(license_key: str, *, today: Optional[date] = None) -> LicenseStatus:
    enforced = license_enforced()
    today = today or timezone.localdate()
    key = (license_key or '').strip()
    if not key:
        return LicenseStatus(
            valid=False,
            enforced=enforced,
            present=False,
            expired=False,
            grace=False,
            message='No license key installed. Set LICENSE_KEY in .env (or deploy/license/license.key).',
            raw_error='missing',
        )

    parts = key.split('.')
    if len(parts) != 3 or parts[0] != LICENSE_PREFIX:
        return LicenseStatus(
            valid=False,
            enforced=enforced,
            present=True,
            expired=False,
            grace=False,
            message='License key format is invalid.',
            raw_error='format',
        )

    try:
        body = _b64url_decode(parts[1])
        sig = _b64url_decode(parts[2])
        _load_public_key().verify(sig, body)
        payload = json.loads(body.decode('utf-8'))
    except (InvalidSignature, ValueError, json.JSONDecodeError, TypeError) as exc:
        return LicenseStatus(
            valid=False,
            enforced=enforced,
            present=True,
            expired=False,
            grace=False,
            message='License signature is invalid or the key was tampered with.',
            raw_error=str(exc) or 'bad_signature',
        )

    if payload.get('iss') != LICENSE_ISS or payload.get('aud') != LICENSE_AUD:
        return LicenseStatus(
            valid=False,
            enforced=enforced,
            present=True,
            expired=False,
            grace=False,
            message='License is not valid for this product.',
            raw_error='aud',
        )

    try:
        iat = _parse_ymd(str(payload['iat']))
        exp = _parse_ymd(str(payload['exp']))
    except (KeyError, ValueError):
        return LicenseStatus(
            valid=False,
            enforced=enforced,
            present=True,
            expired=False,
            grace=False,
            message='License dates are missing or invalid.',
            raw_error='dates',
        )

    features = tuple(str(x) for x in (payload.get('features') or []))
    org = str(payload.get('org') or '')
    org_code = str(payload.get('org_code') or '')
    note = str(payload.get('note') or '')
    days_remaining = (exp - today).days
    expired = today > exp
    in_grace = False
    if expired:
        in_grace = today <= (exp + timedelta(days=grace_days()))

    if not expired:
        return LicenseStatus(
            valid=True,
            enforced=enforced,
            present=True,
            expired=False,
            grace=False,
            org=org,
            org_code=org_code,
            issued_on=iat,
            expires_on=exp,
            days_remaining=days_remaining,
            features=features,
            note=note,
            message=f'Licensed to {org or org_code or "customer"} until {exp.isoformat()}.',
        )

    if in_grace:
        return LicenseStatus(
            valid=False,
            enforced=enforced,
            present=True,
            expired=True,
            grace=True,
            org=org,
            org_code=org_code,
            issued_on=iat,
            expires_on=exp,
            days_remaining=days_remaining,
            features=features,
            note=note,
            message=(
                f'License expired on {exp.isoformat()}. Grace period active — '
                f'renew with Seqela before hard lockout.'
            ),
            raw_error='grace',
        )

    return LicenseStatus(
        valid=False,
        enforced=enforced,
        present=True,
        expired=True,
        grace=False,
        org=org,
        org_code=org_code,
        issued_on=iat,
        expires_on=exp,
        days_remaining=days_remaining,
        features=features,
        note=note,
        message=f'License expired on {exp.isoformat()}. Contact Seqela for a renewal key.',
        raw_error='expired',
    )


def get_license_status(*, force_refresh: bool = False) -> LicenseStatus:
    key = _read_license_key_from_env_or_file()
    now = timezone.now()
    with _cache_lock:
        cached = _cache.get('status')
        checked_at = _cache.get('checked_at')
        if (
            not force_refresh
            and cached is not None
            and _cache.get('key') == key
            and checked_at
            and (now - checked_at).total_seconds() < 300
        ):
            return cached
        status = verify_license_string(key)
        _cache['key'] = key
        _cache['checked_at'] = now
        _cache['status'] = status
        return status


def clear_license_cache() -> None:
    with _cache_lock:
        _cache['key'] = None
        _cache['checked_at'] = None
        _cache['status'] = None
