"""Bank-wide collateral field-work policy (singleton config with code defaults)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from collateral import constants


@dataclass(frozen=True)
class CollateralPolicy:
    min_images_per_building: int
    min_images_per_land: int
    min_images_per_other_item: int
    gps_accuracy_weak_threshold_m: int
    photo_max_distance_from_site_m: int
    block_submit_on_far_photos: bool
    block_submit_on_missing_photo_gps: bool
    min_coverage_ratio: Decimal
    flag_coverage_below_ratio: Decimal
    declared_address_max_distance_from_site_m: int
    block_submit_on_declared_address_mismatch: bool
    require_movable_photo_types: bool
    exif_gps_mismatch_warn_m: int
    block_submit_on_exif_gps_mismatch: bool


_DEFAULT = CollateralPolicy(
    min_images_per_building=constants.MIN_IMAGES_PER_BUILDING,
    min_images_per_land=constants.MIN_IMAGES_PER_LAND,
    min_images_per_other_item=constants.MIN_IMAGES_PER_OTHER_ITEM,
    gps_accuracy_weak_threshold_m=constants.GPS_ACCURACY_WEAK_THRESHOLD_M,
    photo_max_distance_from_site_m=200,
    block_submit_on_far_photos=False,
    block_submit_on_missing_photo_gps=False,
    min_coverage_ratio=Decimal('1.00'),
    flag_coverage_below_ratio=Decimal('1.00'),
    declared_address_max_distance_from_site_m=3000,
    block_submit_on_declared_address_mismatch=False,
    require_movable_photo_types=True,
    exif_gps_mismatch_warn_m=constants.EXIF_GPS_MISMATCH_WARN_M,
    block_submit_on_exif_gps_mismatch=False,
)

_cache: Optional[CollateralPolicy] = None


def get_collateral_policy(*, refresh: bool = False) -> CollateralPolicy:
    global _cache
    if _cache is not None and not refresh:
        return _cache
    try:
        from collateral.models import CollateralPolicyConfig

        row = CollateralPolicyConfig.objects.first()
        if row:
            _cache = CollateralPolicy(
                min_images_per_building=row.min_images_per_building,
                min_images_per_land=row.min_images_per_land,
                min_images_per_other_item=row.min_images_per_other_item,
                gps_accuracy_weak_threshold_m=row.gps_accuracy_weak_threshold_m,
                photo_max_distance_from_site_m=row.photo_max_distance_from_site_m,
                block_submit_on_far_photos=row.block_submit_on_far_photos,
                block_submit_on_missing_photo_gps=row.block_submit_on_missing_photo_gps,
                min_coverage_ratio=row.min_coverage_ratio,
                flag_coverage_below_ratio=row.flag_coverage_below_ratio,
                declared_address_max_distance_from_site_m=row.declared_address_max_distance_from_site_m,
                block_submit_on_declared_address_mismatch=row.block_submit_on_declared_address_mismatch,
                require_movable_photo_types=row.require_movable_photo_types,
                exif_gps_mismatch_warn_m=row.exif_gps_mismatch_warn_m,
                block_submit_on_exif_gps_mismatch=row.block_submit_on_exif_gps_mismatch,
            )
            return _cache
    except Exception:
        pass
    _cache = _DEFAULT
    return _cache


def clear_policy_cache():
    global _cache
    _cache = None
