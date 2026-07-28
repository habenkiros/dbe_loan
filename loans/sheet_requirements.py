# loans/sheet_requirements.py
"""
Excel-aligned sheet requirements for the 7-step loan appraisal.
Used for completeness panels, step-7 gate, and AI snapshots (must match workbook sections).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


def _filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


@dataclass(frozen=True)
class SheetFieldRequirement:
    """One required field on a sheet (maps to a model attribute or custom check)."""
    label: str
    check: Callable[[dict], bool]


@dataclass(frozen=True)
class SheetRequirementSpec:
    step: int
    title: str
    excel_sheet_name: str
    required: tuple[SheetFieldRequirement, ...]
    # Excel fields not yet captured in Django (informational for officers + AI)
    excel_only_notes: tuple[str, ...] = ()


def _ctx(loan_request, appraisal, basic_info) -> dict:
    return {
        'loan_request': loan_request,
        'appraisal': appraisal,
        'basic_info': basic_info,
    }


# ----- Per-step requirements (aligned with LOAN_APPRAISAL_EXCEL_STRUCTURE.md) -----

SHEET_1 = SheetRequirementSpec(
    step=1,
    title='Basic Info & loan request',
    excel_sheet_name='(1) Basic Info and loan request',
    required=(
        SheetFieldRequirement('Applicant name', lambda c: _filled(c['loan_request'].applicant_name)),
        SheetFieldRequirement('Phone number', lambda c: _filled(c['loan_request'].phone_number)),
        SheetFieldRequirement('Loan amount requested', lambda c: _filled(c['loan_request'].amount_requested)),
        SheetFieldRequirement('Business name', lambda c: _filled(c['basic_info'].business_name)),
        SheetFieldRequirement('Economic sector', lambda c: _filled(c['basic_info'].economic_sector)),
        SheetFieldRequirement('Term (months)', lambda c: _filled(c['basic_info'].term_months)),
        SheetFieldRequirement('Repayment frequency', lambda c: _filled(c['basic_info'].repayment_frequency)),
        SheetFieldRequirement('Interest rate', lambda c: _filled(c['basic_info'].interest_rate)),
    ),
    excel_only_notes=(),
)

SHEET_2 = SheetRequirementSpec(
    step=2,
    title='Business & character assessment',
    excel_sheet_name='(2) Bus. and Character Assess.',
    required=(
        SheetFieldRequirement(
            'NBE credit report obtained (Y/N)',
            lambda c: c['appraisal'].nbe_credit_report_obtained is not None,
        ),
        SheetFieldRequirement(
            'All 10 qualitative factors rated',
            lambda c: (
                c['appraisal'].qualitative_factors.count() >= 10
                and all(
                    _filled(f.rating)
                    for f in c['appraisal'].qualitative_factors.all()
                )
            ),
        ),
        SheetFieldRequirement(
            'Qualitative total score / pass status',
            lambda c: c['appraisal'].qualitative_total_score is not None,
        ),
    ),
    excel_only_notes=(
        'Per-factor Weight / Earned score columns (partially in app via earned_score)',
        'Credit history table: at least one row recommended when borrower has other loans',
    ),
)

SHEET_3 = SheetRequirementSpec(
    step=3,
    title='Cashflow analysis',
    excel_sheet_name='(3) Cashflow Analysis',
    required=(
        SheetFieldRequirement(
            'Proposed monthly installment',
            lambda c: _filled(c['appraisal'].proposed_monthly_installment),
        ),
        SheetFieldRequirement(
            'Monthly business income or Phase-1 sales',
            lambda c: _filled(c['appraisal'].monthly_business_income)
            or _filled(c['appraisal'].cf_monthly_sales),
        ),
        SheetFieldRequirement(
            'Monthly business expenses or Phase-1 expense lines',
            lambda c: _filled(c['appraisal'].monthly_business_expenses)
            or any(
                _filled(getattr(c['appraisal'], f, None))
                for f in (
                    'cf_monthly_cogs', 'cf_monthly_salaries', 'cf_monthly_rent',
                    'cf_monthly_utilities', 'cf_monthly_transport',
                    'cf_monthly_other_operating', 'cf_monthly_taxes',
                )
            ),
        ),
        SheetFieldRequirement(
            'Computed net monthly cashflow',
            lambda c: c['appraisal'].net_monthly_cashflow is not None,
        ),
        SheetFieldRequirement(
            'Monthly or annual DSCR',
            lambda c: c['appraisal'].dscr is not None or c['appraisal'].dscr_annual is not None,
        ),
    ),
    excel_only_notes=(
        'Sales/purchases cash vs credit % (optional deeper P&L detail)',
    ),
)

SHEET_4 = SheetRequirementSpec(
    step=4,
    title='E&S assessment',
    excel_sheet_name='(4) E&S Assessment',
    required=(
        SheetFieldRequirement(
            'E&S checklist rows present (21 questions)',
            lambda c: c['appraisal'].es_checklist_items.count() >= 21,
        ),
        SheetFieldRequirement(
            'E&S risk category',
            lambda c: _filled(c['appraisal'].es_risk_category),
        ),
        SheetFieldRequirement(
            'Eligibility decision (PASS / PASS WITH ACTION / REJECT)',
            lambda c: _filled(c['appraisal'].es_eligibility_decision),
        ),
        SheetFieldRequirement(
            'Assessment date',
            lambda c: _filled(c['appraisal'].es_assessment_date),
        ),
    ),
    excel_only_notes=('Screened / checked / approved signatures on printed form',),
)

SHEET_5 = SheetRequirementSpec(
    step=5,
    title='Collateral worksheet',
    excel_sheet_name='(5) Collateral Worksheet',
    required=(
        SheetFieldRequirement(
            'Total collateral value',
            lambda c: _filled(c['appraisal'].collateral_total_value)
            and c['appraisal'].collateral_total_value > 0,
        ),
        SheetFieldRequirement(
            'Collateral coverage ratio',
            lambda c: c['appraisal'].collateral_coverage_ratio is not None,
        ),
    ),
    excel_only_notes=(
        'Breakdown: immovable, moveable, intangible, guarantors (fields on Sheet 5 form)',
        'Collateral BOQ / building valuation in Collateral module should support Sheet 5 totals',
    ),
)

SHEET_6 = SheetRequirementSpec(
    step=6,
    title='Summary & decision',
    excel_sheet_name='(6) Summary and Decision Sheet',
    required=(
        SheetFieldRequirement(
            'Credit recommendation (approve / decline / escalate)',
            lambda c: _filled(c['appraisal'].recommendation),
        ),
        SheetFieldRequirement('Strengths', lambda c: _filled(c['appraisal'].strengths)),
        SheetFieldRequirement('Weaknesses', lambda c: _filled(c['appraisal'].weaknesses)),
    ),
    excel_only_notes=(
        'Key indicators before/after loan with rating/weight/earned score matrix',
        'Summary of decision factors (qualitative, financial, E&S, collateral) with norms',
    ),
)

SHEET_7 = SheetRequirementSpec(
    step=7,
    title='Repayment & amortization',
    excel_sheet_name='(7) Repayment Schedule / Loan Amortization Schedule',
    required=(
        SheetFieldRequirement(
            'Amortization schedule generated (≥1 payment row)',
            lambda c: c['appraisal'].amortization_entries.exists(),
        ),
    ),
    excel_only_notes=(),
)

APPRAISAL_SHEET_SPECS: tuple[SheetRequirementSpec, ...] = (
    SHEET_1, SHEET_2, SHEET_3, SHEET_4, SHEET_5, SHEET_6, SHEET_7,
)


def _collateral_boq_status(loan_request) -> Dict[str, Any]:
    """
    Collateral module requirements that feed Sheet (5).

    Excel Sheet 5 accepts immovable (building and/or land), moveable, etc.
    Require at least one registered collateral evidence path — not building-only.
    """
    from collateral.models import Building, BuildingValuation, LandValuation, OtherCollateralItem

    buildings = list(Building.objects.filter(loan_request=loan_request))
    has_land = LandValuation.objects.filter(loan_request=loan_request).exists()
    has_other = OtherCollateralItem.objects.filter(loan_request=loan_request).exists()

    missing = []
    total_rows = 0
    for b in buildings:
        rows = BuildingValuation.objects.filter(building=b).count()
        total_rows += rows
        if not b.city_id:
            missing.append(f'Building "{b.name}": city/woreda not set (required for unit prices)')
        if rows == 0:
            missing.append(f'Building "{b.name}": no valuation line items')

    if buildings:
        return {
            'complete': len(missing) == 0,
            'missing': missing,
            'building_count': len(buildings),
            'valuation_row_count': total_rows,
            'has_land': has_land,
            'has_other': has_other,
        }

    if has_land or has_other:
        return {
            'complete': True,
            'missing': [],
            'building_count': 0,
            'valuation_row_count': 0,
            'has_land': has_land,
            'has_other': has_other,
        }

    return {
        'complete': False,
        'missing': [
            'Register at least one building valuation, land valuation, or other collateral item',
        ],
        'building_count': 0,
        'valuation_row_count': 0,
        'has_land': False,
        'has_other': False,
    }


def evaluate_sheet(spec: SheetRequirementSpec, ctx: dict) -> Dict[str, Any]:
    missing = [req.label for req in spec.required if not req.check(ctx)]
    return {
        'step': spec.step,
        'title': spec.title,
        'excel_sheet_name': spec.excel_sheet_name,
        'complete': len(missing) == 0,
        'missing': missing,
        'excel_only_notes': list(spec.excel_only_notes),
    }


def get_appraisal_sheet_status(
    loan_request,
    appraisal,
    basic_info,
    max_step: int = 7,
) -> Dict[int, Dict[str, Any]]:
    """Status for sheets 1–max_step keyed by step number."""
    ctx = _ctx(loan_request, appraisal, basic_info)
    specs = [s for s in APPRAISAL_SHEET_SPECS if s.step <= max_step]
    status = {spec.step: evaluate_sheet(spec, ctx) for spec in specs}

    # Corporate Sheet 1: require legal registration when mode is corporate
    from .appraisal_mode import is_corporate
    if is_corporate(loan_request, appraisal) and 1 in status:
        if not _filled(getattr(basic_info, 'legal_registration_number', None)):
            status[1]['complete'] = False
            status[1]['missing'] = list(status[1]['missing']) + [
                'Legal registration / CR number (corporate)',
            ]
        if status[1].get('title'):
            status[1]['title'] = 'Entity & loan request (corporate)'

    # Attach collateral BOQ detail under sheet 5
    boq = _collateral_boq_status(loan_request)
    status[5]['collateral_boq'] = boq
    if not boq['complete']:
        status[5]['complete'] = False
        status[5]['missing'] = list(status[5]['missing']) + [
            f'Collateral estimation: {m}' for m in boq['missing']
        ]
    return status


def sheets_blocking_completion(
    sheet_status: Dict[int, Dict[str, Any]],
    max_step: Optional[int] = None,
) -> List[str]:
    """Human-readable list of incomplete sheets (for hard block on finish)."""
    blocks = []
    steps = sorted(sheet_status.keys())
    if max_step is not None:
        steps = [s for s in steps if s <= max_step]
    for step in steps:
        info = sheet_status[step]
        if not info.get('complete'):
            missing = ', '.join(info.get('missing') or ['incomplete'])
            blocks.append(f'Sheet {step} ({info.get("title")}): {missing}')
    return blocks


def build_appraisal_ai_snapshot(loan_request, appraisal, basic_info) -> dict:
    """
    Full workbook-shaped payload for AI credit analysis.
    Includes completeness gaps so the model knows what is missing on each sheet.
    """
    sheet_status = get_appraisal_sheet_status(loan_request, appraisal, basic_info)
    return {
        'loan_request_id': loan_request.loan_request_id,
        'sheets': sheet_status,
        'blocking_gaps': sheets_blocking_completion(sheet_status),
        'sheet_1_basic': {
            'applicant_name': loan_request.applicant_name,
            'amount_requested': str(loan_request.amount_requested) if loan_request.amount_requested else None,
            'purpose': loan_request.purpose,
            'business_name': basic_info.business_name,
            'economic_sector': basic_info.economic_sector,
            'term_months': basic_info.term_months,
            'repayment_frequency': basic_info.repayment_frequency,
            'interest_rate': str(basic_info.interest_rate) if basic_info.interest_rate else None,
        },
        'sheet_2_credit_character': {
            'nbe_obtained': appraisal.nbe_credit_report_obtained,
            'bureau_score': str(appraisal.bureau_score) if appraisal.bureau_score else None,
            'bureau_score_band': appraisal.bureau_score_band,
            'qualitative_total': str(appraisal.qualitative_total_score) if appraisal.qualitative_total_score else None,
            'qualitative_passed': appraisal.qualitative_passed,
            'credit_history_rows': list(
                appraisal.credit_history_entries.values(
                    'lender', 'loan_amount', 'current_balance', 'status', 'score',
                )[:20]
            ),
            'qualitative_factors': list(
                appraisal.qualitative_factors.values(
                    'factor_key', 'factor_name', 'rating', 'earned_score', 'notes',
                )
            ),
        },
        'sheet_3_cashflow': {
            'net_monthly_cashflow': str(appraisal.net_monthly_cashflow) if appraisal.net_monthly_cashflow else None,
            'dscr': str(appraisal.dscr) if appraisal.dscr else None,
            'dscr_annual': str(appraisal.dscr_annual) if appraisal.dscr_annual else None,
            'stressed_dscr': str(appraisal.stressed_dscr) if appraisal.stressed_dscr else None,
            'proposed_installment': str(appraisal.proposed_monthly_installment)
            if appraisal.proposed_monthly_installment else None,
        },
        'sheet_4_es': {
            'risk_category': appraisal.es_risk_category,
            'eligibility': appraisal.es_eligibility_decision,
            'checklist_count': appraisal.es_checklist_items.count(),
        },
        'sheet_5_collateral': {
            'total_value': str(appraisal.collateral_total_value) if appraisal.collateral_total_value else None,
            'coverage_ratio': str(appraisal.collateral_coverage_ratio)
            if appraisal.collateral_coverage_ratio else None,
            'boq': sheet_status.get(5, {}).get('collateral_boq'),
        },
        'sheet_6_decision': {
            'recommendation': appraisal.recommendation,
            'strengths': appraisal.strengths,
            'weaknesses': appraisal.weaknesses,
        },
        'sheet_7_amortization': {
            'entry_count': appraisal.amortization_entries.count(),
        },
    }
