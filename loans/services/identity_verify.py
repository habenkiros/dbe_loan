"""Fayda / TIN identity adapters and face/liveness (off | mock | http).

Provider downtime is recorded as provider_error — it does not freeze origination.
Biometric adapters persist a match score and vendor ref only, never a raw template.
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


def biometric_provider_mode() -> str:
    mode = (getattr(settings, 'BIOMETRIC_PROVIDER', 'mock') or 'mock').strip().lower()
    if mode in ('0', 'false', 'no', 'disabled', 'off'):
        return 'off'
    url = (getattr(settings, 'BIOMETRIC_VERIFY_URL', '') or '').strip()
    if mode == 'http' and not url:
        return 'mock'
    if getattr(settings, 'IDENTITY_VERIFY_FORCE_MOCK', False):
        return 'mock'
    return mode if mode in ('mock', 'http', 'off') else 'mock'


def _file_ext(name: str) -> str:
    if '.' not in (name or ''):
        return 'jpg'
    return name.rsplit('.', 1)[-1].lower().lstrip('.') or 'jpg'


def _match_min() -> int:
    return int(getattr(settings, 'BIOMETRIC_MATCH_MIN', 70) or 70)


def _score_from_hashes(selfie_hash: str, id_hash: str) -> int:
    from loans.services.document_forensics import hamming_hex

    if not selfie_hash:
        return 0
    if not id_hash:
        return 0
    dist = hamming_hex(selfie_hash, id_hash)
    if dist <= 18:
        return 92
    if dist <= 36:
        return 78
    if dist <= 64:
        return 58
    return 32


def _status_from_score(score) -> str:
    if score is None:
        return 'pending'
    try:
        value = float(score)
    except (TypeError, ValueError):
        return 'pending'
    if value >= _match_min():
        return 'matched'
    if value < 40:
        return 'failed'
    return 'pending'


def _mock_biometric(
    party,
    selfie_bytes: bytes,
    filename: str,
    id_raw: bytes,
    id_ext: str,
) -> Dict[str, Any]:
    import hashlib

    from loans.services.document_forensics import perceptual_hash_hex

    name = (filename or '').lower()
    legal = (getattr(party, 'legal_name_en', '') or '').strip().lower()
    digest = hashlib.sha256(selfie_bytes or b'empty').hexdigest()[:16]
    if 'fail' in name or legal.startswith('fail'):
        return {
            'provider': 'mock',
            'status': 'failed',
            'face_match_score': 22,
            'liveness_ref': f'mock-{digest}',
            'reason': 'Mock biometric failed (demo fail token).',
        }
    selfie_hash = perceptual_hash_hex(selfie_bytes or b'', _file_ext(filename))
    id_hash = perceptual_hash_hex(id_raw or b'', id_ext) if id_raw else ''
    if not id_hash:
        return {
            'provider': 'mock',
            'status': 'pending',
            'face_match_score': None,
            'liveness_ref': f'mock-{digest}',
            'selfie_phash': selfie_hash,
            'reason': 'Selfie captured. No ID portrait on file to compare yet.',
        }
    score = _score_from_hashes(selfie_hash, id_hash)
    return {
        'provider': 'mock',
        'status': _status_from_score(score),
        'face_match_score': score,
        'liveness_ref': f'mock-{digest}',
        'selfie_phash': selfie_hash,
        'id_phash': id_hash,
        'reason': 'Heuristic selfie-to-ID comparison (not a live biometric vendor).',
    }


def _http_biometric(
    party,
    selfie_bytes: bytes,
    filename: str,
    id_raw: bytes,
    id_ext: str,
) -> Dict[str, Any]:
    import hashlib

    from loans.services.document_forensics import perceptual_hash_hex

    url = (getattr(settings, 'BIOMETRIC_VERIFY_URL', '') or '').strip()
    if not url:
        return {
            'provider': 'http',
            'status': 'provider_error',
            'face_match_score': None,
            'error': 'BIOMETRIC_VERIFY_URL is empty.',
        }
    timeout = int(getattr(settings, 'BIOMETRIC_VERIFY_TIMEOUT', 8) or 8)
    selfie_hash = perceptual_hash_hex(selfie_bytes or b'', _file_ext(filename))
    id_hash = perceptual_hash_hex(id_raw or b'', id_ext) if id_raw else ''
    payload = {
        'party_id': getattr(party, 'pk', None),
        'legal_name_en': getattr(party, 'legal_name_en', '') or '',
        'selfie_phash': selfie_hash,
        'id_phash': id_hash,
        'filename': filename or '',
    }
    try:
        kwargs: Dict[str, Any] = {'timeout': timeout, 'data': payload}
        if getattr(settings, 'BIOMETRIC_SEND_IMAGE', False) and selfie_bytes:
            kwargs['files'] = {
                'selfie': (filename or 'selfie.jpg', selfie_bytes, 'application/octet-stream'),
            }
        else:
            kwargs['json'] = payload
            kwargs.pop('data', None)
        resp = requests.post(url, **kwargs)
        if resp.status_code >= 500:
            return {
                'provider': 'http',
                'status': 'provider_error',
                'http_status': resp.status_code,
                'error': resp.text[:300],
            }
        body = resp.json() if resp.content else {}
        score = body.get('face_match_score')
        status = body.get('status') or _status_from_score(score)
        ref = (body.get('liveness_ref') or '')[:80]
        if not ref:
            ref = 'http-' + hashlib.sha256(selfie_bytes or b'empty').hexdigest()[:16]
        return {
            'provider': 'http',
            'status': status,
            'face_match_score': score,
            'liveness_ref': ref,
            'url': urljoin(url, ''),
        }
    except Exception as exc:
        logger.warning('Biometric verify HTTP failed: %s', exc)
        return {
            'provider': 'http',
            'status': 'provider_error',
            'error': str(exc)[:300],
        }


def verify_biometric(
    party,
    *,
    selfie_bytes: bytes = None,
    selfie_filename: str = '',
    id_portrait_bytes: bytes = None,
    id_ext: str = '',
    selfie_ref: str = '',
    face_match_score=None,
) -> Dict[str, Any]:
    """Run face/liveness. Persist score + vendor ref only — never a raw template."""
    from django.utils import timezone
    from loans.models import KycParty

    mode = biometric_provider_mode()
    captured = bool(selfie_bytes) or bool(selfie_ref) or bool(getattr(party, 'selfie', None))
    if mode == 'off' or not captured:
        party.biometric_status = KycParty.BIOMETRIC_NONE
        if not selfie_ref:
            party.liveness_ref = ''
        payload = {'provider': 'off', 'status': 'skipped', 'reason': 'Biometric provider off or no selfie.'}
        party.biometric_payload = payload
        party.save(update_fields=[
            'biometric_status', 'liveness_ref', 'biometric_payload', 'updated_at',
        ])
        return payload

    if selfie_ref and not selfie_bytes and face_match_score is not None:
        result = {
            'provider': mode,
            'status': _status_from_score(face_match_score),
            'face_match_score': face_match_score,
            'liveness_ref': (selfie_ref or '')[:80],
        }
    elif mode == 'http' and selfie_bytes:
        result = _http_biometric(
            party, selfie_bytes, selfie_filename, id_portrait_bytes or b'', id_ext,
        )
    else:
        result = _mock_biometric(
            party, selfie_bytes or b'', selfie_filename, id_portrait_bytes or b'', id_ext,
        )
        if selfie_ref:
            result['liveness_ref'] = (selfie_ref or '')[:80]

    status = result.get('status') or 'pending'
    mapping = {
        'matched': KycParty.BIOMETRIC_MATCHED,
        'failed': KycParty.BIOMETRIC_FAILED,
        'pending': KycParty.BIOMETRIC_PENDING,
        'provider_error': KycParty.BIOMETRIC_PENDING,
        'skipped': KycParty.BIOMETRIC_NONE,
    }
    party.biometric_status = mapping.get(status, KycParty.BIOMETRIC_PENDING)
    score = result.get('face_match_score')
    if score is not None:
        try:
            from decimal import Decimal
            party.face_match_score = Decimal(str(score))
        except Exception:
            party.face_match_score = None
    party.liveness_ref = (result.get('liveness_ref') or '')[:80]
    payload = dict(result)
    payload['checked_at'] = timezone.now().isoformat()
    # Never persist image bytes in JSON.
    payload.pop('image', None)
    payload.pop('template', None)
    party.biometric_payload = payload
    party.save(update_fields=[
        'liveness_ref', 'biometric_status', 'face_match_score',
        'biometric_payload', 'updated_at',
    ])
    return payload
