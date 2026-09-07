"""Who this instance belongs to. The factory was built at DECSI; this copy is DBE."""

from __future__ import annotations

from django.conf import settings


def institution_name() -> str:
    return (getattr(settings, 'INSTITUTION_NAME', None) or 'Development Bank of Ethiopia').strip()


def institution_short() -> str:
    return (getattr(settings, 'INSTITUTION_SHORT', None) or 'DBE').strip()


def product_name() -> str:
    return (getattr(settings, 'PRODUCT_NAME', None) or 'Credit Intelligence').strip()


def mfa_issuer_default() -> str:
    return f'{institution_short()} {product_name()}'
