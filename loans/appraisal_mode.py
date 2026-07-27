"""Appraisal product mode: MSME vs Corporate."""

from __future__ import annotations

from typing import List, Optional, Tuple

MODE_MSME = 'msme'
MODE_CORPORATE = 'corporate'

MODE_CHOICES = [
    (MODE_MSME, 'MSME / cashflow'),
    (MODE_CORPORATE, 'Corporate'),
]

CORPORATE_QUALITATIVE_PASS_THRESHOLD = 75  # same gate scale 0–100


def resolve_appraisal_mode(loan_request, appraisal=None) -> str:
    """Prefer persisted appraisal mode, else category, else MSME."""
    if appraisal is not None:
        mode = getattr(appraisal, 'appraisal_mode', None) or ''
        if mode in (MODE_MSME, MODE_CORPORATE):
            return mode
    category = getattr(loan_request, 'category', None)
    if category is not None:
        mode = getattr(category, 'appraisal_mode', None) or ''
        if mode in (MODE_MSME, MODE_CORPORATE):
            return mode
    return MODE_MSME


def ensure_appraisal_mode(appraisal, loan_request) -> str:
    """Stamp appraisal.appraisal_mode once from category if empty."""
    mode = resolve_appraisal_mode(loan_request, appraisal)
    if getattr(appraisal, 'appraisal_mode', None) != mode:
        appraisal.appraisal_mode = mode
        if appraisal.pk:
            appraisal.save(update_fields=['appraisal_mode', 'updated_at'])
    return mode


def is_corporate(loan_request, appraisal=None) -> bool:
    return resolve_appraisal_mode(loan_request, appraisal) == MODE_CORPORATE


def qualitative_factor_keys_for_mode(mode: str) -> List[Tuple[str, str]]:
    from .models import CORPORATE_QUALITATIVE_FACTOR_KEYS, QUALITATIVE_FACTOR_KEYS

    if mode == MODE_CORPORATE:
        return list(CORPORATE_QUALITATIVE_FACTOR_KEYS)
    return list(QUALITATIVE_FACTOR_KEYS)


def mode_label(mode: str) -> str:
    return dict(MODE_CHOICES).get(mode, mode)
