"""Aggregate observations → MarketPriceBand; lookup for engineering unit-price suggest."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from statistics import median
from typing import Any, Dict, List, Optional, Sequence, Tuple

from django.db.models import Q
from django.utils import timezone

from partners.models import MarketObservation, MarketPriceBand


def _percentile(sorted_vals: Sequence[Decimal], p: float) -> Optional[Decimal]:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    d0 = sorted_vals[f] * Decimal(str(c - k))
    d1 = sorted_vals[c] * Decimal(str(k - f))
    return d0 + d1


def normalize_item_key(label: str) -> str:
    return ' '.join((label or '').strip().lower().split())[:255]


def band_group_key(obs: MarketObservation) -> Tuple:
    unit = (obs.unit or '').strip().lower()[:40]
    if obs.sub_sub_work_id:
        return (obs.city_id, obs.asset_class, obs.sub_work_id or None,
                obs.sub_sub_work_id, '', unit)
    if obs.sub_work_id:
        return (obs.city_id, obs.asset_class, obs.sub_work_id, None, '', unit)
    return (
        obs.city_id,
        obs.asset_class,
        None,
        None,
        normalize_item_key(obs.item_label),
        unit,
    )


def recompute_all_bands(window_days: int = MarketPriceBand.WINDOW_DAYS_DEFAULT) -> int:
    """Rebuild all bands from active observations in the rolling window. Returns band count."""
    since = timezone.localdate() - timedelta(days=window_days)
    qs = (
        MarketObservation.objects.filter(
            status=MarketObservation.STATUS_ACTIVE,
            observed_at__gte=since,
        )
        .select_related('city', 'sub_work', 'sub_sub_work')
        .order_by('id')
    )
    groups: Dict[Tuple, List[MarketObservation]] = {}
    for obs in qs:
        key = band_group_key(obs)
        if key[0] is None:
            continue
        # skip empty free-text keys with no catalog
        if not key[2] and not key[3] and not key[4]:
            continue
        groups.setdefault(key, []).append(obs)

    # Drop old bands then recreate (simple, correct)
    MarketPriceBand.objects.all().delete()
    created = 0
    for key, rows in groups.items():
        city_id, asset_class, sw_id, ssw_id, item_key, unit = key
        prices = sorted(Decimal(str(r.unit_price_etb)) for r in rows if r.unit_price_etb)
        if not prices:
            continue
        med = Decimal(str(median(prices)))
        last_date = max(r.observed_at for r in rows)
        MarketPriceBand.objects.create(
            city_id=city_id,
            asset_class=asset_class,
            sub_work_id=sw_id,
            sub_sub_work_id=ssw_id,
            item_key=item_key or '',
            unit=unit or '',
            sample_count=len(prices),
            median_price=med.quantize(Decimal('0.01')),
            p25_price=_percentile(prices, 0.25),
            p75_price=_percentile(prices, 0.75),
            min_price=prices[0],
            max_price=prices[-1],
            last_observed_at=last_date,
            window_days=window_days,
        )
        created += 1
    return created


def find_band_for_unit_price(
    *,
    city_id: int,
    sub_work_id: Optional[int] = None,
    sub_sub_work_id: Optional[int] = None,
) -> Optional[MarketPriceBand]:
    """Lookup band matching unit-price catalog row (prefer sub_sub, then sub work)."""
    if not city_id:
        return None
    qs = MarketPriceBand.objects.filter(city_id=city_id, asset_class=MarketObservation.ASSET_BUILDING)
    if sub_sub_work_id:
        band = qs.filter(sub_sub_work_id=sub_sub_work_id).order_by('-sample_count').first()
        if band:
            return band
    if sub_work_id:
        return (
            qs.filter(sub_work_id=sub_work_id, sub_sub_work__isnull=True)
            .order_by('-sample_count')
            .first()
            or qs.filter(sub_work_id=sub_work_id).order_by('-sample_count').first()
        )
    return None


def find_band_for_land(*, city_id: Optional[int] = None, item_key: str = '') -> Optional[MarketPriceBand]:
    """Land ETB/m² band — prefer city + key, then city-wide land, then key-only."""
    qs = MarketPriceBand.objects.filter(asset_class=MarketObservation.ASSET_LAND)
    key = normalize_item_key(item_key)
    if city_id and key:
        band = qs.filter(city_id=city_id, item_key=key).order_by('-sample_count').first()
        if band:
            return band
    if city_id:
        band = qs.filter(city_id=city_id).order_by('-sample_count').first()
        if band:
            return band
    if key:
        return qs.filter(item_key=key).order_by('-sample_count').first()
    return None


def find_band_for_movable(
    *,
    city_id: Optional[int] = None,
    asset_class: str = '',
    item_key: str = '',
) -> Optional[MarketPriceBand]:
    """Vehicle / machinery / other movable estimated-value band."""
    from partners.models import MarketObservation

    classes = []
    ac = (asset_class or '').strip().lower()
    if ac in (
        MarketObservation.ASSET_VEHICLE,
        MarketObservation.ASSET_MACHINERY,
        MarketObservation.ASSET_OTHER,
    ):
        classes = [ac]
    else:
        classes = [
            MarketObservation.ASSET_VEHICLE,
            MarketObservation.ASSET_MACHINERY,
            MarketObservation.ASSET_OTHER,
        ]
    qs = MarketPriceBand.objects.filter(asset_class__in=classes)
    key = normalize_item_key(item_key)
    if city_id and key:
        band = qs.filter(city_id=city_id, item_key=key).order_by('-sample_count').first()
        if band:
            return band
    if key:
        band = qs.filter(item_key=key).order_by('-sample_count').first()
        if band:
            return band
    if city_id:
        return qs.filter(city_id=city_id).order_by('-sample_count').first()
    return None


def suggest_payload(band: Optional[MarketPriceBand]) -> Optional[Dict[str, Any]]:
    if not band:
        return None
    return {
        'band_id': band.pk,
        'median': band.median_price,
        'p25': band.p25_price,
        'p75': band.p75_price,
        'sample_count': band.sample_count,
        'last_observed_at': band.last_observed_at,
        'freshness_days': band.freshness_days,
        'is_suggestible': band.is_suggestible,
        'unit': band.unit,
        'min_samples': MarketPriceBand.MIN_SAMPLES_SUGGEST,
    }


def attach_bands_to_unit_prices(prices) -> list:
    """Annotate unit-price rows with .market_band / .market_suggest for templates."""
    out = []
    for p in prices:
        sw_id = p.sub_work_id
        ssw_id = p.sub_sub_work_id
        if ssw_id and not sw_id and getattr(p, 'sub_sub_work', None):
            sw_id = p.sub_sub_work.sub_work_id
        band = find_band_for_unit_price(
            city_id=p.city_id,
            sub_work_id=sw_id,
            sub_sub_work_id=ssw_id,
        )
        p.market_band = band
        p.market_suggest = suggest_payload(band)
        out.append(p)
    return out
