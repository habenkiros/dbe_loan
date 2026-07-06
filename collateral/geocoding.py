"""Geocode declared addresses from Sheet 1 for map verification (Nominatim / OSM)."""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Optional, Tuple

from django.utils import timezone

logger = logging.getLogger(__name__)

NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
USER_AGENT = 'DECSI-Loan-Collateral/1.0 (collateral verification)'


def _pick_declared_address(loan_request) -> Tuple[str, str]:
    """Return (address_text, source) where source is business|home|empty."""
    try:
        bi = loan_request.basic_info
    except Exception:
        return '', ''
    business = (bi.business_address or '').strip()
    home = (bi.home_address or '').strip()
    if business:
        return business, 'business'
    if home:
        return home, 'home'
    return '', ''


def geocode_address(address: str, *, country: str = 'Ethiopia') -> Optional[Tuple[float, float]]:
    """Forward geocode via Nominatim. Returns (lat, lon) or None."""
    address = (address or '').strip()
    if len(address) < 5:
        return None
    query = f'{address}, {country}' if country and country.lower() not in address.lower() else address
    params = urllib.parse.urlencode({
        'q': query,
        'format': 'json',
        'limit': 1,
        'countrycodes': 'et',
    })
    req = urllib.request.Request(
        f'{NOMINATIM_URL}?{params}',
        headers={'User-Agent': USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        if not data:
            return None
        lat = float(data[0]['lat'])
        lon = float(data[0]['lon'])
        return lat, lon
    except Exception:
        logger.exception('Geocoding failed for address: %s', address[:80])
        return None


def resolve_declared_address_coords(loan_request, *, force: bool = False) -> Optional[Tuple[Decimal, Decimal]]:
    """
    Return geocoded declared address coords, caching on LoanRequest.
    Skips network call when cached text matches current Sheet 1 address.
    """
    text, source = _pick_declared_address(loan_request)
    if not text:
        return None

    if (
        not force
        and loan_request.declared_address_text == text
        and loan_request.declared_address_lat is not None
        and loan_request.declared_address_lon is not None
    ):
        return loan_request.declared_address_lat, loan_request.declared_address_lon

    coords = geocode_address(text)
    if not coords:
        return None

    lat, lon = coords
    loan_request.declared_address_text = text
    loan_request.declared_address_lat = Decimal(str(lat)).quantize(Decimal('0.00000001'))
    loan_request.declared_address_lon = Decimal(str(lon)).quantize(Decimal('0.00000001'))
    loan_request.declared_address_geocoded_at = timezone.now()
    loan_request.declared_address_source = source
    loan_request.save(update_fields=[
        'declared_address_text', 'declared_address_lat', 'declared_address_lon',
        'declared_address_geocoded_at', 'declared_address_source',
    ])
    return loan_request.declared_address_lat, loan_request.declared_address_lon


def declared_address_for_loan(loan_request) -> str:
    text, _ = _pick_declared_address(loan_request)
    return text
