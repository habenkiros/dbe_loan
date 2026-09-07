"""Fayda / TIN identity adapters (off | mock | http).

Provider downtime is recorded as provider_error — it does not freeze origination.
"""

from __future__ import annotations

import logging
from typing import Any, Dict
from urllib.parse import urljoin

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def provider_mode() -> str:
    mode = (getattr(settings, 'IDENTITY_VERIFY_PROVIDER', 'mock') or 'mock').strip().lower()
    if mode in ('0', 'false', 'no', 'disabled', 'off'):
        return 'off'
    fayda = (getattr(settings, 'FAYDA_VERIFY_URL', '') or '').strip()
    tin_url = (getattr(settings, 'TIN_VERIFY_URL', '') or '').strip()
    if mode == 'http' and not (fayda or tin_url):
        return 'mock'
    if getattr(settings, 'IDENTITY_VERIFY_FORCE_MOCK', False):
        return 'mock'
    return mode if mode in ('mock', 'http', 'off') else 'mock'


def _digits(value: str) -> str:
    return ''.join(ch for ch in (value or '') if ch.isdigit())


def _mock_verify(party) -> Dict[str, Any]:
    fan = _digits(getattr(party, 'fan', '') or '')
    tin = _digits(getattr(party, 'tin', '') or '')
    ident = _digits(getattr(party, 'id_number', '') or '')
    name = (getattr(party, 'legal_name_en', '') or '').strip().lower()
    if not (fan or tin or ident):
        return {
            'provider': 'mock',
            'status': 'skipped',
            'verified': None,
            'reason': 'No FAN, TIN, or ID number to verify.',
        }
    denied_fan = fan.startswith('000') or fan == '999999999'
    denied_tin = tin.startswith('000') or tin == '000000000'
    denied_name = 'unverified' in name
    if denied_fan or denied_tin or denied_name:
        return {
            'provider': 'mock',
            'status': 'not_found',
            'verified': False,
            'reason': 'Mock provider did not confirm this identity.',
        }
    return {
        'provider': 'mock',
        'status': 'confirmed',
        'verified': True,
        'reason': 'Mock provider confirmed FAN/TIN (demo).',
    }


def _http_verify(party) -> Dict[str, Any]:
    kind = getattr(party, 'identity_kind', '') or ''
    fayda_url = (getattr(settings, 'FAYDA_VERIFY_URL', '') or '').strip()
    tin_url = (getattr(settings, 'TIN_VERIFY_URL', '') or '').strip()
    url = ''
    if kind in ('fayda_fan', 'national_id', 'kebele', 'passport') and fayda_url:
        url = fayda_url
    elif kind == 'tin' and tin_url:
        url = tin_url
    elif tin_url and getattr(party, 'tin', ''):
        url = tin_url
    elif fayda_url:
        url = fayda_url
    if not url:
        return {
            'provider': 'http',
            'status': 'skipped',
            'verified': None,
            'reason': 'No Fayda/TIN verify URL configured.',
        }
    timeout = int(getattr(settings, 'IDENTITY_VERIFY_TIMEOUT', 8) or 8)
    payload = {
        'identity_kind': kind,
        'fan': getattr(party, 'fan', '') or '',
        'tin': getattr(party, 'tin', '') or '',
        'id_number': getattr(party, 'id_number', '') or '',
        'legal_name_en': getattr(party, 'legal_name_en', '') or '',
        'legal_name_am': getattr(party, 'legal_name_am', '') or '',
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.status_code >= 500:
            return {
                'provider': 'http',
                'status': 'provider_error',
                'verified': None,
                'http_status': resp.status_code,
                'error': resp.text[:300],
            }
        body = resp.json() if resp.content else {}
        verified = body.get('verified')
        status = body.get('status') or (
            'confirmed' if verified is True else
            'not_found' if verified is False else
            'skipped'
        )
        return {
            'provider': 'http',
            'status': status,
            'verified': verified,
            'detail': {k: body[k] for k in list(body)[:12] if k != 'raw'},
            'url': urljoin(url, ''),
        }
    except Exception as exc:
        logger.warning('Identity verify HTTP failed: %s', exc)
        return {
            'provider': 'http',
            'status': 'provider_error',
            'verified': None,
            'error': str(exc)[:300],
        }


def verify_party(party) -> Dict[str, Any]:
    """Run the configured provider and persist verify_status on the party."""
    from django.utils import timezone
    from loans.models import KycParty

    mode = provider_mode()
    if mode == 'off':
        result = {'provider': 'off', 'status': 'skipped', 'verified': None}
    elif mode == 'http':
        result = _http_verify(party)
    else:
        result = _mock_verify(party)

    status = result.get('status') or 'skipped'
    mapping = {
        'confirmed': KycParty.VERIFY_CONFIRMED,
        'not_found': KycParty.VERIFY_NOT_FOUND,
        'mismatch': KycParty.VERIFY_MISMATCH,
        'provider_error': KycParty.VERIFY_ERROR,
        'skipped': KycParty.VERIFY_SKIPPED,
        'error': KycParty.VERIFY_ERROR,
    }
    party.verify_status = mapping.get(status, KycParty.VERIFY_SKIPPED)
    payload = dict(result)
    payload['checked_at'] = timezone.now().isoformat()
    party.verify_payload = payload
    party.save(update_fields=['verify_status', 'verify_payload', 'updated_at'])
    return payload


def verify_biometric(party, *, selfie_ref: str = '', face_match_score=None) -> Dict[str, Any]:
    """Phase 2 stub — stores vendor ref only; no raw biometric templates."""
    from loans.models import KycParty

    mode = provider_mode()
    if mode == 'off' or not selfie_ref:
        party.biometric_status = KycParty.BIOMETRIC_NONE
        party.liveness_ref = ''
        party.save(update_fields=['biometric_status', 'liveness_ref', 'updated_at'])
        return {'status': 'skipped', 'reason': 'Biometric provider not configured.'}
    party.liveness_ref = (selfie_ref or '')[:80]
    party.biometric_status = KycParty.BIOMETRIC_PENDING
    if face_match_score is not None:
        party.face_match_score = face_match_score
        party.biometric_status = (
            KycParty.BIOMETRIC_MATCHED if float(face_match_score) >= 70
            else KycParty.BIOMETRIC_FAILED
        )
    party.save(update_fields=[
        'liveness_ref', 'biometric_status', 'face_match_score', 'updated_at',
    ])
    return {
        'status': party.biometric_status,
        'liveness_ref': party.liveness_ref,
        'face_match_score': str(party.face_match_score or ''),
    }
