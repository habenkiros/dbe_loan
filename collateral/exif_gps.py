"""Extract GPS from image EXIF for consistency checks against browser capture GPS."""

from __future__ import annotations

import io
import logging
from decimal import Decimal
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _to_degrees(value) -> Optional[float]:
    """Convert EXIF GPS rational triples to decimal degrees."""
    try:
        d, m, s = value
        def _rat(x):
            if hasattr(x, 'numerator'):
                return float(x.numerator) / float(x.denominator or 1)
            if isinstance(x, (tuple, list)) and len(x) == 2:
                return float(x[0]) / float(x[1] or 1)
            return float(x)
        return _rat(d) + _rat(m) / 60.0 + _rat(s) / 3600.0
    except Exception:
        return None


def extract_exif_gps(file_obj) -> Optional[Tuple[float, float]]:
    """
    Return (lat, lon) from image EXIF if present.
    Accepts Django UploadedFile, file path, or bytes-like.
    Does not rewind caller-owned streams inconsistently — seeks back to 0 when possible.
    """
    try:
        from PIL import Image
        from PIL.ExifTags import GPSTAGS, TAGS
    except ImportError:
        return None

    img = None
    try:
        if hasattr(file_obj, 'read'):
            pos = file_obj.tell() if hasattr(file_obj, 'tell') else None
            data = file_obj.read()
            if hasattr(file_obj, 'seek') and pos is not None:
                file_obj.seek(pos)
            elif hasattr(file_obj, 'seek'):
                file_obj.seek(0)
            img = Image.open(io.BytesIO(data))
        else:
            img = Image.open(file_obj)

        exif = img._getexif() if hasattr(img, '_getexif') else None
        if not exif:
            # Pillow 10+ getexif()
            exif_obj = img.getexif()
            if not exif_obj:
                return None
            # GPS IFD
            gps_ifd = exif_obj.get_ifd(0x8825) if hasattr(exif_obj, 'get_ifd') else None
            if not gps_ifd:
                return None
            gps = {GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
        else:
            gps_info = None
            for tag, value in exif.items():
                decoded = TAGS.get(tag, tag)
                if decoded == 'GPSInfo':
                    gps_info = value
                    break
            if not gps_info:
                return None
            gps = {GPSTAGS.get(k, k): v for k, v in gps_info.items()}

        lat = _to_degrees(gps.get('GPSLatitude'))
        lon = _to_degrees(gps.get('GPSLongitude'))
        if lat is None or lon is None:
            return None
        if gps.get('GPSLatitudeRef') == 'S':
            lat = -lat
        if gps.get('GPSLongitudeRef') == 'W':
            lon = -lon
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        return lat, lon
    except Exception:
        logger.debug('EXIF GPS extract failed', exc_info=True)
        return None
    finally:
        if img is not None:
            try:
                img.close()
            except Exception:
                pass


def apply_exif_gps_to_image(img_instance, upload) -> Optional[str]:
    """
    Populate EXIF GPS fields on image instance from upload.
    Returns optional warning message (does not block save).
    """
    from collateral.map_utils import haversine_m
    from collateral.policy import get_collateral_policy

    coords = extract_exif_gps(upload)
    if not coords:
        img_instance.exif_gps_lat = None
        img_instance.exif_gps_lon = None
        img_instance.browser_vs_exif_distance_m = None
        return None

    lat, lon = coords
    img_instance.exif_gps_lat = Decimal(str(round(lat, 8)))
    img_instance.exif_gps_lon = Decimal(str(round(lon, 8)))

    if img_instance.gps_lat is None or img_instance.gps_lon is None:
        img_instance.browser_vs_exif_distance_m = None
        return 'Photo has EXIF GPS but no browser capture GPS.'

    dist = haversine_m(
        img_instance.gps_lat, img_instance.gps_lon,
        img_instance.exif_gps_lat, img_instance.exif_gps_lon,
    )
    if dist is None:
        img_instance.browser_vs_exif_distance_m = None
        return None

    img_instance.browser_vs_exif_distance_m = Decimal(str(round(dist, 1)))
    threshold = get_collateral_policy().exif_gps_mismatch_warn_m
    if dist > threshold:
        return (
            f'Photo EXIF GPS is {round(dist)} m from browser GPS '
            f'(warn threshold {threshold} m). Verify location integrity.'
        )
    return None
