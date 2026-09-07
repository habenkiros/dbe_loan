"""Sanctions / PEP name screening (mock list or HTTP provider).

Results feed the same Fraud/AML compliance case desk — not a separate product.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Demo entries for offline UAT. Prefer customer_number hits so normal mock catalog
# customers are not poisoned. Names are for explicit test strings.
_DEFAULT_WATCHLIST: List[Dict[str, Any]] = [
    {
        'list_name': 'Demo sanctions list',
        'match_type': 'sanctions',
        'customer_number': 'SANCTIONED001',
        'name': 'Sanctioned Demo Person',
        'score': 98,
        'notes': 'Offline demo hit — replace with bank watchlist / vendor API.',
    },
    {
        'list_name': 'Demo PEP list',
        'match_type': 'pep',
        'customer_number': 'PEP0000001',
        'name': 'PEP Demo Official',
        'score': 92,
        'notes': 'Offline demo PEP hit.',
    },
    {
        'list_name': 'Demo sanctions list',
        'match_type': 'sanctions',
        'name': 'Aliased Sanction Subject',
        'score': 88,
        'notes': 'Name-only demo match.',
    },
]


def _normalize_name(value: str) -> str:
    text = (value or '').strip().lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _extra_watchlist_from_settings() -> List[Dict[str, Any]]:
    raw = (getattr(settings, 'SANCTIONS_DEMO_EXTRA_NAMES', '') or '').strip()
    if not raw:
        return []
    out = []
    for part in raw.split(','):
        name = part.strip()
        if len(name) < 3:
            continue
        out.append({
            'list_name': 'Configured demo list',
            'match_type': 'sanctions',
            'name': name,
            'score': 95,
            'notes': 'From SANCTIONS_DEMO_EXTRA_NAMES',
        })
    return out


def _watchlist() -> List[Dict[str, Any]]:
    return list(_DEFAULT_WATCHLIST) + _extra_watchlist_from_settings()


def provider_mode() -> str:
    """off | mock | http"""
    mode = (getattr(settings, 'SANCTIONS_PROVIDER', 'mock') or 'mock').strip().lower()
    if mode in ('0', 'false', 'no', 'disabled', 'off'):
        return 'off'
    if mode == 'http' and not (getattr(settings, 'SANCTIONS_HTTP_URL', '') or '').strip():
        return 'mock'
    if getattr(settings, 'SANCTIONS_FORCE_MOCK', False):
        return 'mock'
    return mode if mode in ('mock', 'http', 'off') else 'mock'


def _mock_screen(
    *,
    name: str,
    customer_number: str = '',
    date_of_birth: str = '',
) -> Dict[str, Any]:
    cn = (customer_number or '').strip()
    norm = _normalize_name(name)
    matches: List[Dict[str, Any]] = []
    for entry in _watchlist():
        entry_cn = (entry.get('customer_number') or '').strip()
        entry_name = _normalize_name(entry.get('name') or '')
        hit = False
        if cn and entry_cn and cn == entry_cn:
            hit = True
        elif norm and entry_name and (norm == entry_name or entry_name in norm or norm in entry_name):
            hit = True
        if not hit:
            continue
        matches.append({
            'list_name': entry.get('list_name') or 'watchlist',
            'match_type': entry.get('match_type') or 'sanctions',
            'score': int(entry.get('score') or 80),
            'matched_name': entry.get('name') or '',
            'matched_customer_number': entry_cn,
            'notes': entry.get('notes') or '',
            'date_of_birth': date_of_birth or '',
        })
    best = max((m['score'] for m in matches), default=0)
    hit_types = sorted({m['match_type'] for m in matches})
    return {
        'provider': 'mock',
        'hit': bool(matches),
        'score': best,
        'match_types': hit_types,
        'matches': matches,
        'subject': {
            'name': name,
            'customer_number': cn,
            'date_of_birth': date_of_birth or '',
        },
    }


def _http_screen(
    *,
    name: str,
    customer_number: str = '',
    date_of_birth: str = '',
) -> Dict[str, Any]:
    base = (getattr(settings, 'SANCTIONS_HTTP_URL', '') or '').rstrip('/')
    path = (getattr(settings, 'SANCTIONS_HTTP_PATH', '') or '').strip() or '/'
    url = urljoin(base + '/', path.lstrip('/')) if path != '/' else base
    timeout = int(getattr(settings, 'SANCTIONS_HTTP_TIMEOUT', 8) or 8)
    headers = {'Accept': 'application/json'}
    api_key = (getattr(settings, 'SANCTIONS_HTTP_API_KEY', '') or '').strip()
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    payload = {
        'name': name,
        'customer_number': customer_number,
        'date_of_birth': date_of_birth,
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
    except Exception as exc:
        logger.warning('Sanctions HTTP screen failed: %s', exc)
        if getattr(settings, 'SANCTIONS_HTTP_FALLBACK_MOCK', True):
            result = _mock_screen(
                name=name, customer_number=customer_number, date_of_birth=date_of_birth,
            )
            result['provider'] = 'mock_fallback'
            result['live_error'] = str(exc)[:200]
            return result
        return {
            'provider': 'http',
            'hit': False,
            'score': 0,
            'match_types': [],
            'matches': [],
            'error': str(exc)[:200],
            'subject': {
                'name': name,
                'customer_number': customer_number,
                'date_of_birth': date_of_birth or '',
            },
        }

    matches = data.get('matches') or []
    if not isinstance(matches, list):
        matches = []
    hit = bool(data.get('hit')) or bool(matches)
    score = int(data.get('score') or 0)
    if not score and matches:
        score = max(int(m.get('score') or 0) for m in matches)
    match_types = data.get('match_types') or [
        m.get('match_type') for m in matches if m.get('match_type')
    ]
    return {
        'provider': 'http',
        'hit': hit,
        'score': score,
        'match_types': list(dict.fromkeys(match_types)),
        'matches': matches,
        'subject': {
            'name': name,
            'customer_number': customer_number,
            'date_of_birth': date_of_birth or '',
        },
        'raw': data if getattr(settings, 'SANCTIONS_KEEP_RAW', False) else {},
    }


def screen_subject(
    *,
    name: str = '',
    customer_number: str = '',
    date_of_birth: str = '',
) -> Dict[str, Any]:
    """Screen a person. Always returns a structured result dict."""
    mode = provider_mode()
    name = (name or '').strip()
    customer_number = (customer_number or '').strip()
    date_of_birth = (date_of_birth or '').strip()
    if mode == 'off':
        return {
            'provider': 'off',
            'hit': False,
            'score': 0,
            'match_types': [],
            'matches': [],
            'subject': {
                'name': name,
                'customer_number': customer_number,
                'date_of_birth': date_of_birth,
            },
        }
    if not name and not customer_number:
        return {
            'provider': mode,
            'hit': False,
            'score': 0,
            'match_types': [],
            'matches': [],
            'subject': {
                'name': name,
                'customer_number': customer_number,
                'date_of_birth': date_of_birth,
            },
            'skipped': 'no_subject',
        }
    if mode == 'http':
        return _http_screen(
            name=name, customer_number=customer_number, date_of_birth=date_of_birth,
        )
    return _mock_screen(
        name=name, customer_number=customer_number, date_of_birth=date_of_birth,
    )


def subject_from_loan(loan_request) -> Dict[str, str]:
    profile = getattr(loan_request, 'customer_profile_snapshot', None) or {}
    if not isinstance(profile, dict):
        profile = {}
    dob = (
        profile.get('date_of_birth')
        or profile.get('dateOfBirth')
        or ''
    )
    return {
        'name': (loan_request.applicant_name or profile.get('name') or '').strip(),
        'customer_number': (
            loan_request.customer_number or profile.get('customer_number') or ''
        ).strip(),
        'date_of_birth': str(dob or '').strip(),
    }


def screen_loan_request(loan_request) -> Dict[str, Any]:
    subject = subject_from_loan(loan_request)
    subjects = [subject]
    seen = {(subject.get('name') or '').strip().lower()}
    try:
        from loans.kyc_identity import get_identity_case

        case = get_identity_case(loan_request=loan_request)
        if case is not None:
            for party in case.parties.all():
                name = (party.legal_name_en or party.legal_name_am or '').strip()
                key = name.lower()
                if not name or key in seen:
                    continue
                seen.add(key)
                subjects.append({
                    'name': name,
                    'customer_number': '',
                    'date_of_birth': str(party.date_of_birth or ''),
                })
    except Exception:
        pass
    combined = screen_subject(**subjects[0])
    extra_hits = []
    for extra in subjects[1:]:
        result = screen_subject(**extra)
        if result.get('hit'):
            extra_hits.append(result)
            combined['hit'] = True
            combined['score'] = max(int(combined.get('score') or 0), int(result.get('score') or 0))
            combined['matches'] = list(combined.get('matches') or []) + list(result.get('matches') or [])
            types = list(combined.get('match_types') or []) + list(result.get('match_types') or [])
            combined['match_types'] = list(dict.fromkeys(types))
    if extra_hits:
        combined['party_hits'] = len(extra_hits)
    combined['subjects_screened'] = len(subjects)
    return combined


def persist_screening(loan_request, result: Dict[str, Any], *, opened_case=None):
    from loans.models import SanctionsScreeningResult

    return SanctionsScreeningResult.objects.create(
        loan_request=loan_request,
        hit=bool(result.get('hit')),
        score=int(result.get('score') or 0),
        match_types=list(result.get('match_types') or []),
        matches=list(result.get('matches') or []),
        provider=(result.get('provider') or '')[:24],
        subject=result.get('subject') or {},
        metadata={
            k: result.get(k)
            for k in ('error', 'live_error', 'skipped')
            if result.get(k)
        },
        compliance_case=opened_case,
    )
