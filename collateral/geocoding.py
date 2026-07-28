"""Geocode declared addresses from Sheet 1 for map verification.

Providers:
  - Gebeta Maps (preferred when GEBETA_MAPS_API_KEY is set) — Ethiopia-local data
    Docs: https://docs.gebeta.app/docs
  - Nominatim / OSM (fallback)
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
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


def _gebeta_api_key() -> str:
    return (getattr(settings, 'GEBETA_MAPS_API_KEY', None) or '').strip()


def gebeta_maps_configured() -> bool:
    return bool(_gebeta_api_key())


def _extract_lat_lon(item: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    if not isinstance(item, dict):
        return None
    lat = item.get('lat')
    if lat is None:
        lat = item.get('latitude')
    lon = item.get('lng')
    if lon is None:
        lon = item.get('lon')
    if lon is None:
        lon = item.get('longitude')
    if lat is None or lon is None:
        return None
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def _normalize_geocode_payload(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ('data', 'results', 'items', 'places'):
            nested = data.get(key)
            if isinstance(nested, list):
                return [x for x in nested if isinstance(x, dict)]
        if _extract_lat_lon(data):
            return [data]
    return []


def geocode_address_gebeta(address: str) -> Optional[Tuple[float, float]]:
    """Forward geocode via Gebeta Maps. Returns (lat, lon) or None."""
    api_key = _gebeta_api_key()
    if not api_key:
        return None
    address = (address or '').strip()
    if len(address) < 3:
        return None
    base = (
        getattr(settings, 'GEBETA_MAPS_GEOCODE_URL', None)
        or 'https://mapapi.gebeta.app/api/v1/route/geocoding'
    ).rstrip('/')
    params = urllib.parse.urlencode({'name': address, 'apiKey': api_key})
    req = urllib.request.Request(
        f'{base}?{params}',
        headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'},
    )
    timeout = int(getattr(settings, 'GEBETA_MAPS_TIMEOUT', 8) or 8)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8')
        data = json.loads(raw) if raw else None
        for item in _normalize_geocode_payload(data):
            coords = _extract_lat_lon(item)
            if coords:
                return coords
        logger.info('Gebeta geocode returned no coords for: %s', address[:80])
        return None
    except urllib.error.HTTPError as exc:
        body = ''
        try:
            body = exc.read().decode('utf-8', errors='replace')[:200]
        except Exception:
            pass
        logger.warning('Gebeta geocode HTTP %s for %s: %s', exc.code, address[:60], body)
        return None
    except Exception:
        logger.exception('Gebeta geocoding failed for address: %s', address[:80])
        return None


def geocode_address_nominatim(address: str, *, country: str = 'Ethiopia') -> Optional[Tuple[float, float]]:
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
        logger.exception('Nominatim geocoding failed for address: %s', address[:80])
        return None


def geocode_address(address: str, *, country: str = 'Ethiopia') -> Optional[Tuple[float, float]]:
    """
    Forward geocode. Prefers Gebeta Maps when configured, then Nominatim.
    Returns (lat, lon) or None.
    """
    provider = (getattr(settings, 'GEBETA_MAPS_GEOCODE_PROVIDER', None) or 'auto').strip().lower()
    if provider in ('gebeta', 'auto') and gebeta_maps_configured():
        coords = geocode_address_gebeta(address)
        if coords:
            return coords
        if provider == 'gebeta':
            return None
    if provider in ('nominatim', 'osm', 'auto', ''):
        return geocode_address_nominatim(address, country=country)
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


def resolve_map_tiles_provider() -> str:
    """
    Effective map UI provider for collateral canvases.
    - gebeta: MapLibre GL + Gebeta vector/raster styles (needs API key)
    - leaflet_osm: Leaflet + OpenStreetMap / Esri (fallback)
    """
    configured = gebeta_maps_configured()
    setting = (getattr(settings, 'GEBETA_MAPS_TILES_PROVIDER', None) or 'auto').strip().lower()
    if setting in ('auto', ''):
        return 'gebeta' if configured else 'leaflet_osm'
    if setting == 'gebeta':
        return 'gebeta' if configured else 'leaflet_osm'
    return 'leaflet_osm'


def map_provider_context() -> Dict[str, Any]:
    """Template/JS config for collateral maps (Gebeta/MapLibre or Leaflet/OSM)."""
    configured = gebeta_maps_configured()
    geocode_setting = (getattr(settings, 'GEBETA_MAPS_GEOCODE_PROVIDER', None) or 'auto').strip().lower()
    tiles_provider = resolve_map_tiles_provider()
    return {
        'gebeta_maps_configured': configured,
        'geocode_provider': (
            'gebeta' if configured and geocode_setting != 'nominatim' else 'nominatim'
        ),
        'map_tiles_provider': tiles_provider,
        'map_tiles_setting': (getattr(settings, 'GEBETA_MAPS_TILES_PROVIDER', None) or 'auto'),
        'gebeta_maps_api_key': _gebeta_api_key() if configured else '',
        'gebeta_style_standard': getattr(
            settings, 'GEBETA_MAPS_STYLE_STANDARD',
            'https://tiles.gebeta.app/styles/standard/style.json',
        ),
        'gebeta_style_satellite': getattr(
            settings, 'GEBETA_MAPS_STYLE_SATELLITE',
            'https://tiles.gebeta.app/styles/raster/raster.json',
        ),
        'gebeta_style_terrain': getattr(
            settings, 'GEBETA_MAPS_STYLE_TERRAIN',
            'https://tiles.gebeta.app/styles/standard/terrain/terrain.json',
        ),
        'gebeta_maps_docs': 'https://docs.gebeta.app/docs',
    }
