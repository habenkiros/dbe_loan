"""Appraisal modality: 7-sheet wizard vs product desk."""

from __future__ import annotations

from typing import List, Optional, Tuple

from loans.product_family import (
    FAMILY_CONSUMER,
    FAMILY_GENERAL,
    FAMILY_IDEA_EQUITY,
    FAMILY_IFB_IJARAH,
    FAMILY_IFB_MURABAHA,
    FAMILY_LEASE,
    FAMILY_PROJECT,
    FAMILY_WHOLESALE,
    suggested_appraisal_mode,
)

MODE_MSME = 'msme'
MODE_CORPORATE = 'corporate'
MODE_PROJECT = FAMILY_PROJECT
MODE_WHOLESALE = FAMILY_WHOLESALE
MODE_LEASE = FAMILY_LEASE
MODE_MURABAHA = FAMILY_IFB_MURABAHA
MODE_IJARAH = FAMILY_IFB_IJARAH
MODE_IDEA = FAMILY_IDEA_EQUITY
MODE_CONSUMER = FAMILY_CONSUMER

SHEET_MODES = frozenset({MODE_MSME, MODE_CORPORATE})

MODE_CHOICES = [
    (MODE_MSME, 'MSME / cashflow sheets'),
    (MODE_CORPORATE, 'Corporate / financial statements'),
    (MODE_PROJECT, 'Project desk'),
    (MODE_WHOLESALE, 'Wholesale / PFI desk'),
    (MODE_LEASE, 'Lease desk'),
    (MODE_MURABAHA, 'Murabaha desk'),
    (MODE_IJARAH, 'Ijarah desk'),
    (MODE_IDEA, 'Idea / quasi-equity desk'),
    (MODE_CONSUMER, 'Consumer / HRM scorecard'),
]

ALL_MODES = frozenset(code for code, _ in MODE_CHOICES)

CORPORATE_QUALITATIVE_PASS_THRESHOLD = 75  # same gate scale 0–100


def locked_appraisal_mode(family: Optional[str]) -> Optional[str]:
    """Policy default for a family. None = General (MSME vs corporate)."""
    from loans.family_policy import default_appraisal_for_family

    return default_appraisal_for_family(family or FAMILY_GENERAL)


def uses_sheet_wizard(mode: Optional[str]) -> bool:
    return (mode or MODE_MSME) in SHEET_MODES


def resolve_appraisal_mode(loan_request, appraisal=None) -> str:
    """Prefer persisted mode, else category, else family desk, else MSME."""
    if appraisal is not None:
        mode = getattr(appraisal, 'appraisal_mode', None) or ''
        if mode in ALL_MODES:
            return mode
    category = getattr(loan_request, 'category', None)
    if category is not None:
        mode = getattr(category, 'appraisal_mode', None) or ''
        if mode in ALL_MODES:
            return mode
        from loans.product_family import resolve_product_family
        suggested = suggested_appraisal_mode(resolve_product_family(loan_request))
        if suggested in ALL_MODES:
            return suggested
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
    if not uses_sheet_wizard(mode):
        return []
    return list(QUALITATIVE_FACTOR_KEYS)


def mode_label(mode: str) -> str:
    return dict(MODE_CHOICES).get(mode, mode)
