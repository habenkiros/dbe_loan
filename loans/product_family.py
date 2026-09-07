"""Financing product families for the shared credit lifecycle.

MSME / corporate 7-sheet wizard is only for FAMILY_GENERAL (and the
external-fund *category* until Credit gives that window its own pack).
Project, wholesale, lease, IFB, idea, and consumer use product desks —
see loans.dbe_desks. DECSI products stay FAMILY_GENERAL.
"""

from __future__ import annotations

from typing import Optional

FAMILY_GENERAL = 'general'
FAMILY_PROJECT = 'project'
FAMILY_LEASE = 'lease'
FAMILY_WHOLESALE = 'wholesale'
FAMILY_CONSUMER = 'consumer'
FAMILY_IFB_MURABAHA = 'ifb_murabaha'
FAMILY_IFB_IJARAH = 'ifb_ijarah'
FAMILY_EXTERNAL_FUND = 'external_fund'
FAMILY_IDEA_EQUITY = 'idea_equity'

FAMILY_CHOICES = [
    (FAMILY_GENERAL, 'General (MSME / corporate)'),
    (FAMILY_PROJECT, 'Project financing'),
    (FAMILY_LEASE, 'Lease financing'),
    (FAMILY_WHOLESALE, 'Wholesale / PFI facility'),
    (FAMILY_CONSUMER, 'Consumer (housing / vehicle)'),
    (FAMILY_IFB_MURABAHA, 'IFB — Murabaha'),
    (FAMILY_IFB_IJARAH, 'IFB — Ijarah'),
    (FAMILY_EXTERNAL_FUND, 'External fund window'),
    (FAMILY_IDEA_EQUITY, 'Idea / quasi-equity'),
]

# None = officer chooses MSME vs corporate. Other values are product desks.
SUGGESTED_APPRAISAL_MODE = {
    FAMILY_GENERAL: None,
    FAMILY_PROJECT: FAMILY_PROJECT,
    FAMILY_LEASE: FAMILY_LEASE,
    FAMILY_WHOLESALE: FAMILY_WHOLESALE,
    FAMILY_CONSUMER: FAMILY_CONSUMER,
    FAMILY_IFB_MURABAHA: FAMILY_IFB_MURABAHA,
    FAMILY_IFB_IJARAH: FAMILY_IFB_IJARAH,
    FAMILY_EXTERNAL_FUND: 'msme',
    FAMILY_IDEA_EQUITY: FAMILY_IDEA_EQUITY,
}

FAMILY_ALIASES = {
    'general': FAMILY_GENERAL,
    'msme': FAMILY_GENERAL,
    'corporate': FAMILY_GENERAL,
    'project': FAMILY_PROJECT,
    'project_finance': FAMILY_PROJECT,
    'project_financing': FAMILY_PROJECT,
    'project financing': FAMILY_PROJECT,
    'lease': FAMILY_LEASE,
    'lease_finance': FAMILY_LEASE,
    'hire_purchase': FAMILY_LEASE,
    'wholesale': FAMILY_WHOLESALE,
    'pfi': FAMILY_WHOLESALE,
    'consumer': FAMILY_CONSUMER,
    'housing': FAMILY_CONSUMER,
    'murabaha': FAMILY_IFB_MURABAHA,
    'ifb_murabaha': FAMILY_IFB_MURABAHA,
    'ijarah': FAMILY_IFB_IJARAH,
    'ifb_ijarah': FAMILY_IFB_IJARAH,
    'external_fund': FAMILY_EXTERNAL_FUND,
    'external fund': FAMILY_EXTERNAL_FUND,
    'donor': FAMILY_EXTERNAL_FUND,
    'idea': FAMILY_IDEA_EQUITY,
    'equity': FAMILY_IDEA_EQUITY,
    'idea_equity': FAMILY_IDEA_EQUITY,
}


def parse_product_family(raw: Optional[str]) -> str:
    if not raw:
        return FAMILY_GENERAL
    key = ' '.join(str(raw).strip().lower().replace('-', '_').split())
    key = key.replace(' ', '_')
    if key in dict(FAMILY_CHOICES):
        return key
    return FAMILY_ALIASES.get(key, FAMILY_GENERAL)


def family_label(family: str) -> str:
    return dict(FAMILY_CHOICES).get(family or FAMILY_GENERAL, family or FAMILY_GENERAL)


def suggested_appraisal_mode(family: str) -> Optional[str]:
    return SUGGESTED_APPRAISAL_MODE.get(family or FAMILY_GENERAL)


def resolve_product_family(loan_request) -> str:
    category = getattr(loan_request, 'category', None)
    family = getattr(category, 'product_family', None) or FAMILY_GENERAL
    if family in dict(FAMILY_CHOICES):
        return family
    return FAMILY_GENERAL
