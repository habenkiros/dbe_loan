"""
Appraisal product vision lock (Cashflow MSME V1.8.3).

Bible: presentation/Cashflow based MSME loan appraisal.xlsx
Out of scope: automating decsi loan new revised rate 2016(ReV).xls
"""

from __future__ import annotations

SAMPLE_BIBLE = 'Cashflow based MSME loan appraisal.xlsx (V1.8.3)'
RATE_WORKBOOK_EXCLUDED = 'decsi loan new revised rate 2016(ReV).xls'

# Explainable scorecard pillars (points sum to 100)
PILLAR_QUALITATIVE = 'qualitative'
PILLAR_FINANCIAL = 'financial'
PILLAR_ES = 'es'
PILLAR_COLLATERAL = 'collateral'

PILLAR_MAX = {
    PILLAR_QUALITATIVE: 25,
    PILLAR_FINANCIAL: 35,
    PILLAR_ES: 15,
    PILLAR_COLLATERAL: 25,
}

PILLAR_LABELS = {
    PILLAR_QUALITATIVE: 'Qualitative / character',
    PILLAR_FINANCIAL: 'Financial / cashflow',
    PILLAR_ES: 'Environmental & social',
    PILLAR_COLLATERAL: 'Collateral coverage',
}

SCORE_BAND_STRONG = 'strong'
SCORE_BAND_ACCEPTABLE = 'acceptable'
SCORE_BAND_WEAK = 'weak'
SCORE_BAND_UNACCEPTABLE = 'unacceptable'

SCORE_BAND_CHOICES = [
    (SCORE_BAND_STRONG, 'Strong'),
    (SCORE_BAND_ACCEPTABLE, 'Acceptable'),
    (SCORE_BAND_WEAK, 'Weak'),
    (SCORE_BAND_UNACCEPTABLE, 'Unacceptable'),
]

FEATURE_SCHEMA_VERSION = 'appraisal_features_v1'
QUALITATIVE_PASS_THRESHOLD = 75  # percent, Excel Sheet 2

# Honest gap map vs Excel / product vision (for engineers + tests)
GAP_MAP = {
    'sheet1_basic_info': {
        'status': 'good',
        'notes': 'Present; OCR/prefill available.',
    },
    'sheet2_per_factor_dropdowns': {
        'status': 'done',
        'notes': 'QUALITATIVE_RATING_CHOICES_BY_FACTOR matches Excel lists.',
    },
    'sheet2_score_math': {
        'status': 'implemented_here',
        'notes': 'Rating → weight/earned → total → ≥75% pass.',
    },
    'sheet3_pnl_dscr': {
        'status': 'good',
        'notes': 'Phase 0–2 P&L + monthly/annual DSCR + stress.',
    },
    'sheet3_max_capacity': {
        'status': 'implemented_here',
        'notes': 'Max loan capacity + suggested installment from Sheet 1 terms.',
    },
    'sheet3_monthly_grid': {
        'status': 'deferred',
        'notes': '12-month cashflow grid only if pilot requires Excel depth.',
    },
    'sheet4_es': {
        'status': 'wired',
        'notes': 'Checklist + eligibility; view must seed/save formset.',
    },
    'sheet5_collateral': {
        'status': 'good',
        'notes': 'Prefill from collateral module.',
    },
    'sheet6_scorecard': {
        'status': 'implemented_here',
        'notes': 'Four-pillar explainable scorecard + policy blockers.',
    },
    'feature_snapshot': {
        'status': 'implemented_here',
        'notes': f'{FEATURE_SCHEMA_VERSION} JSON on appraisal complete.',
    },
    'rate_workbook': {
        'status': 'excluded',
        'notes': RATE_WORKBOOK_EXCLUDED,
    },
}
