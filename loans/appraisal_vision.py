"""
Appraisal product vision lock (Cashflow MSME V1.8.3 + Corporate mode).

Bible: presentation/Cashflow based MSME loan appraisal.xlsx
Out of scope: automating decsi loan new revised rate 2016(ReV).xls

Credit score algorithm (locked): CREDIT_SCORE_ALGORITHM_V2
"""

from __future__ import annotations

SAMPLE_BIBLE = 'Cashflow based MSME loan appraisal.xlsx (V1.8.3)'
RATE_WORKBOOK_EXCLUDED = 'decsi loan new revised rate 2016(ReV).xls'

# ---------------------------------------------------------------------------
# CREDIT_SCORE_ALGORITHM_V2 — explainable composite 0–100 (MSME + Corporate)
# ---------------------------------------------------------------------------
# Hard gates (policy) still block finish independently of this score.
# Soft features below feed the explainable scorecard only.
#
# Pillars (sum = 100):
#   qualitative  20  Sheet 2 character (MSME) / governance (Corporate)
#   financial    30  Sheet 3 DSCR, stress, capacity, BS ratios (+ corp FS)
#   banking      20  Live/mock account transactions + bureau conduct
#   es           15  Sheet 4 eligibility / risk
#   collateral   15  Sheet 5 coverage
#
# Banking feature keys (both modes):
#   bank.turnover_vs_installment   Avg monthly credit inflows vs installment
#   bank.inflow_stability          Lower month-to-month CV → higher points
#   bank.nsf_bounces               Returned items / NSF in window
#   bank.negative_balance_days     Days ending negative
#   bank.credit_months             Months with material credit inflow
#   bank.bureau_band               NBE/bureau band from Sheet 2
# Corporate extras (same pillar, additive caps inside max):
#   bank.audit_verified            Verified audited financials document
#   bank.corp_revenue_present      Annual revenue entered on Sheet 3
# ---------------------------------------------------------------------------

CREDIT_SCORE_ALGORITHM = 'CREDIT_SCORE_ALGORITHM_V2'
FEATURE_SCHEMA_VERSION = 'appraisal_features_v2'

PILLAR_QUALITATIVE = 'qualitative'
PILLAR_FINANCIAL = 'financial'
PILLAR_BANKING = 'banking'
PILLAR_ES = 'es'
PILLAR_COLLATERAL = 'collateral'

PILLAR_MAX = {
    PILLAR_QUALITATIVE: 20,
    PILLAR_FINANCIAL: 30,
    PILLAR_BANKING: 20,
    PILLAR_ES: 15,
    PILLAR_COLLATERAL: 15,
}

PILLAR_LABELS = {
    PILLAR_QUALITATIVE: 'Qualitative / character',
    PILLAR_FINANCIAL: 'Financial / cashflow',
    PILLAR_BANKING: 'Banking & bureau conduct',
    PILLAR_ES: 'Environmental & social',
    PILLAR_COLLATERAL: 'Collateral coverage',
}

# Mode-specific qualitative labels (same pillar key / max)
PILLAR_LABELS_BY_MODE = {
    'msme': {
        PILLAR_QUALITATIVE: 'Qualitative / character',
    },
    'corporate': {
        PILLAR_QUALITATIVE: 'Governance / character',
    },
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

QUALITATIVE_PASS_THRESHOLD = 75  # percent, Excel Sheet 2

# Honest gap map vs Excel / product vision (for engineers + tests)
GAP_MAP = {
    'sheet1_basic_info': {
        'status': 'good',
        'notes': 'Present; OCR/prefill + core banking lookup/conflicts available.',
    },
    'sheet1_banking_intake': {
        'status': 'implemented_here',
        'notes': 'Customer number lookup → Sheet 1; empty-fill + conflict accept; mock when DECSI_BASE_URL unset.',
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
        'status': 'implemented_here',
        'notes': '12-month sales/expenses/net grid on Sheet 3; seed from averages.',
    },
    'sheet3_balance_sheet': {
        'status': 'implemented_here',
        'notes': 'Current assets/liabilities, inventory, totals, equity + current/acid/D-E ratios.',
    },
    'banking_transactions': {
        'status': 'implemented_here',
        'notes': (
            f'{CREDIT_SCORE_ALGORITHM}: account transaction metrics (mock/live) '
            'feed banking pillar; refresh from Sheet 2.'
        ),
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
        'notes': f'Five-pillar explainable scorecard ({CREDIT_SCORE_ALGORITHM}) + policy blockers.',
    },
    'appraisal_lock': {
        'status': 'implemented_here',
        'notes': 'Sheets 1–7 + score inputs locked after finish / committee pending / final decision; unlock on return.',
    },
    'feature_snapshot': {
        'status': 'implemented_here',
        'notes': f'{FEATURE_SCHEMA_VERSION} JSON on appraisal complete (includes banking + appraisal_mode).',
    },
    'corporate_mode': {
        'status': 'implemented_here',
        'notes': 'appraisal_mode msme|corporate; corporate Sheet 1 entity KYC, Sheet 2 governance factors, FS/ratios.',
    },
    'rate_workbook': {
        'status': 'excluded',
        'notes': RATE_WORKBOOK_EXCLUDED,
    },
}
