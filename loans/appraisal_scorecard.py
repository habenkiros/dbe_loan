"""Four-pillar explainable credit scorecard + policy blockers/warnings."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .appraisal_policy import get_loan_analysis_policy
from .appraisal_vision import (
    PILLAR_COLLATERAL,
    PILLAR_ES,
    PILLAR_FINANCIAL,
    PILLAR_LABELS,
    PILLAR_MAX,
    PILLAR_QUALITATIVE,
    SCORE_BAND_ACCEPTABLE,
    SCORE_BAND_STRONG,
    SCORE_BAND_UNACCEPTABLE,
    SCORE_BAND_WEAK,
)
from .qualitative_scoring import qualitative_contributions


def _d(v) -> Optional[Decimal]:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _pillar_qualitative(appraisal) -> Tuple[Decimal, List[dict], str]:
    max_pts = Decimal(PILLAR_MAX[PILLAR_QUALITATIVE])
    total = _d(appraisal.qualitative_total_score)
    contrib = qualitative_contributions(appraisal)
    if total is None:
        return Decimal('0'), contrib, 'Qualitative score not computed yet (complete Sheet 2).'
    # qualitative_total_score is already 0–100
    earned = (total * max_pts / Decimal('100')).quantize(Decimal('0.01'))
    remark = f'Total character score {total}/100'
    if appraisal.qualitative_passed is False:
        remark += ' — below 75% gate'
    elif appraisal.qualitative_passed:
        remark += ' — passed ≥75% gate'
    return earned, contrib, remark


def _pillar_financial(appraisal, policy) -> Tuple[Decimal, List[dict], str]:
    max_pts = Decimal(PILLAR_MAX[PILLAR_FINANCIAL])
    contrib: List[dict] = []
    dscr = _d(appraisal.dscr_annual) or _d(appraisal.dscr)
    stressed = _d(appraisal.stressed_dscr)
    warn_min = _d(policy.warn_annual_dscr_min) or Decimal('1.2')

    points = Decimal('0')
    if dscr is not None:
        if dscr >= Decimal('1.5'):
            points += Decimal('20')
            band = 'strong DSCR'
        elif dscr >= warn_min:
            points += Decimal('14')
            band = 'adequate DSCR'
        elif dscr >= Decimal('1.0'):
            points += Decimal('8')
            band = 'thin DSCR'
        else:
            points += Decimal('2')
            band = 'DSCR below 1.0'
        contrib.append({
            'feature_key': 'fin.dscr',
            'value': float(dscr),
            'points': float(points),
            'reason': f'{band} (primary DSCR)',
        })
    else:
        contrib.append({
            'feature_key': 'fin.dscr',
            'value': None,
            'points': 0,
            'reason': 'DSCR not available — complete Sheet 3',
        })

    stress_pts = Decimal('0')
    if stressed is not None:
        stress_floor = _d(policy.warn_stressed_dscr_min) or Decimal('1.0')
        if stressed >= warn_min:
            stress_pts = Decimal('10')
        elif stressed >= stress_floor:
            stress_pts = Decimal('6')
        else:
            stress_pts = Decimal('2')
        contrib.append({
            'feature_key': 'fin.stressed_dscr',
            'value': float(stressed),
            'points': float(stress_pts),
            'reason': 'Stress-tested DSCR',
        })
    points += stress_pts

    # Capacity headroom vs ask
    cap = _d(getattr(appraisal, 'max_loan_capacity', None))
    ask = _d(getattr(appraisal.loan_request, 'amount_requested', None))
    if cap is not None and ask is not None and ask > 0:
        ratio = (cap / ask).quantize(Decimal('0.01'))
        if ratio >= Decimal('1.2'):
            cap_pts = Decimal('5')
        elif ratio >= Decimal('1.0'):
            cap_pts = Decimal('3')
        else:
            cap_pts = Decimal('1')
        points += cap_pts
        contrib.append({
            'feature_key': 'fin.max_capacity_vs_ask',
            'value': float(ratio),
            'points': float(cap_pts),
            'reason': f'Max capacity / ask = {ratio}',
        })

    earned = min(points, max_pts)
    remark = f'DSCR-focused financial pillar ({earned}/{max_pts})'
    return earned, contrib, remark


def _pillar_es(appraisal) -> Tuple[Decimal, List[dict], str]:
    max_pts = Decimal(PILLAR_MAX[PILLAR_ES])
    elig = appraisal.es_eligibility_decision
    risk = appraisal.es_risk_category
    contrib = []
    if elig == appraisal.ES_ELIGIBILITY_REJECT:
        earned = Decimal('0')
        remark = 'E&S REJECT — pillar zeroed'
    elif elig == appraisal.ES_ELIGIBILITY_PASS_ACTION:
        earned = Decimal('9')
        remark = 'PASS WITH ACTION POINTS'
    elif elig == appraisal.ES_ELIGIBILITY_PASS:
        earned = Decimal('15') if risk != appraisal.ES_RISK_HIGH else Decimal('11')
        remark = f'PASS (risk={risk or "—"})'
    else:
        earned = Decimal('5')
        remark = 'E&S eligibility not set'
    if risk == appraisal.ES_RISK_HIGH and elig != appraisal.ES_ELIGIBILITY_REJECT:
        earned = min(earned, Decimal('8'))
        remark += '; high risk capped'
    contrib.append({
        'feature_key': 'es.eligibility',
        'value': elig or '',
        'points': float(earned),
        'reason': remark,
    })
    return min(earned, max_pts), contrib, remark


def _pillar_collateral(appraisal, policy) -> Tuple[Decimal, List[dict], str]:
    max_pts = Decimal(PILLAR_MAX[PILLAR_COLLATERAL])
    cov = _d(appraisal.collateral_coverage_ratio)
    warn_min = _d(policy.warn_collateral_coverage_min) or Decimal('1.0')
    contrib = []
    if cov is None:
        # try compute
        total = _d(appraisal.collateral_total_value)
        ask = _d(appraisal.loan_request.amount_requested)
        if total is not None and ask and ask > 0:
            cov = (total / ask).quantize(Decimal('0.01'))
    if cov is None:
        return Decimal('0'), [{
            'feature_key': 'col.coverage',
            'value': None,
            'points': 0,
            'reason': 'Coverage missing — complete Sheet 5 / collateral',
        }], 'No collateral coverage'
    if cov >= Decimal('1.5'):
        earned = max_pts
        remark = 'Strong coverage'
    elif cov >= warn_min:
        earned = Decimal('18')
        remark = 'Adequate coverage'
    elif cov >= Decimal('0.8'):
        earned = Decimal('10')
        remark = 'Below policy minimum'
    else:
        earned = Decimal('4')
        remark = 'Weak coverage'
    contrib.append({
        'feature_key': 'col.coverage',
        'value': float(cov),
        'points': float(earned),
        'reason': remark,
    })
    return earned, contrib, remark


def band_for_total(total: Decimal) -> str:
    if total >= Decimal('80'):
        return SCORE_BAND_STRONG
    if total >= Decimal('60'):
        return SCORE_BAND_ACCEPTABLE
    if total >= Decimal('40'):
        return SCORE_BAND_WEAK
    return SCORE_BAND_UNACCEPTABLE


def build_credit_scorecard(appraisal) -> Dict[str, Any]:
    """Compute explainable 4-pillar scorecard (does not save)."""
    policy = get_loan_analysis_policy()
    pillars = []
    all_contrib: List[dict] = []
    total = Decimal('0')

    for key, fn in (
        (PILLAR_QUALITATIVE, lambda: _pillar_qualitative(appraisal)),
        (PILLAR_FINANCIAL, lambda: _pillar_financial(appraisal, policy)),
        (PILLAR_ES, lambda: _pillar_es(appraisal)),
        (PILLAR_COLLATERAL, lambda: _pillar_collateral(appraisal, policy)),
    ):
        earned, contrib, remark = fn()
        max_pts = Decimal(PILLAR_MAX[key])
        pillars.append({
            'key': key,
            'label': PILLAR_LABELS[key],
            'earned': float(earned),
            'max': float(max_pts),
            'remark': remark,
        })
        all_contrib.extend(contrib)
        total += earned

    total = total.quantize(Decimal('0.01'))
    band = band_for_total(total)
    return {
        'schema': 'credit_scorecard_v1',
        'total': float(total),
        'max_total': 100.0,
        'band': band,
        'band_label': {
            SCORE_BAND_STRONG: 'Strong',
            SCORE_BAND_ACCEPTABLE: 'Acceptable',
            SCORE_BAND_WEAK: 'Weak',
            SCORE_BAND_UNACCEPTABLE: 'Unacceptable',
        }.get(band, band),
        'pillars': pillars,
        'contributions': all_contrib,
        'sample_bible': 'Cashflow based MSME loan appraisal.xlsx',
    }


def persist_credit_scorecard(appraisal) -> Dict[str, Any]:
    card = build_credit_scorecard(appraisal)
    appraisal.credit_score_total = Decimal(str(card['total']))
    appraisal.credit_score_band = card['band']
    appraisal.scorecard_detail = card
    appraisal.save(update_fields=[
        'credit_score_total', 'credit_score_band', 'scorecard_detail', 'updated_at',
    ])
    return card


def evaluate_analysis_gates(appraisal, basic_info=None) -> Tuple[List[str], List[str]]:
    """Return (hard_blocks, warnings) using LoanAnalysisPolicyConfig."""
    policy = get_loan_analysis_policy()
    blocks: List[str] = []
    warnings: List[str] = []

    if policy.hard_block_qualitative_fail and appraisal.qualitative_passed is False:
        blocks.append('Qualitative assessment failed (<75%). Do not proceed without remediation.')

    if policy.hard_block_es_reject and appraisal.es_eligibility_decision == appraisal.ES_ELIGIBILITY_REJECT:
        blocks.append('E&S eligibility is REJECT.')

    if policy.hard_block_es_high_risk and appraisal.es_risk_category == appraisal.ES_RISK_HIGH:
        blocks.append('E&S risk category is High (hard block per policy).')

    dscr_a = _d(appraisal.dscr_annual)
    dscr_m = _d(appraisal.dscr)
    stressed = _d(appraisal.stressed_dscr)

    if policy.hard_block_annual_dscr and dscr_a is not None and dscr_a < (_d(policy.hard_annual_dscr_min) or Decimal('1')):
        blocks.append(f'Annual DSCR {dscr_a} below hard minimum {policy.hard_annual_dscr_min}.')
    if policy.hard_block_monthly_dscr and dscr_m is not None and dscr_m < (_d(policy.hard_monthly_dscr_min) or Decimal('1')):
        blocks.append(f'Monthly DSCR {dscr_m} below hard minimum {policy.hard_monthly_dscr_min}.')
    if policy.hard_block_stressed_dscr and stressed is not None and stressed < (_d(policy.hard_stressed_dscr_min) or Decimal('1')):
        blocks.append(f'Stressed DSCR {stressed} below hard minimum {policy.hard_stressed_dscr_min}.')

    if policy.hard_block_bureau_defaults and appraisal.bureau_defaults_ever:
        blocks.append('Bureau indicates prior defaults.')
    if policy.hard_block_bureau_restructured and appraisal.bureau_restructured_ever:
        blocks.append('Bureau indicates restructured loans.')
    if policy.hard_block_bureau_inquiries and appraisal.bureau_inquiries_6m is not None:
        if appraisal.bureau_inquiries_6m >= policy.hard_bureau_inquiries_count:
            blocks.append(f'Bureau inquiries in 6m ({appraisal.bureau_inquiries_6m}) exceed hard limit.')

    # Warnings
    warn_a = _d(policy.warn_annual_dscr_min) or Decimal('1.2')
    warn_m = _d(policy.warn_monthly_dscr_min) or Decimal('1.2')
    if dscr_a is not None and dscr_a < warn_a:
        warnings.append(f'Annual DSCR {dscr_a} below warning threshold {warn_a}.')
    if dscr_m is not None and dscr_m < warn_m:
        warnings.append(f'Monthly DSCR {dscr_m} below warning threshold {warn_m}.')
    cov = _d(appraisal.collateral_coverage_ratio)
    warn_c = _d(policy.warn_collateral_coverage_min) or Decimal('1')
    if cov is not None and cov < warn_c:
        warnings.append(f'Collateral coverage {cov} below warning minimum {warn_c}.')

    if policy.hard_block_incomplete_sheets:
        try:
            from .sheet_requirements import get_appraisal_sheet_status, sheets_blocking_completion
            status = get_appraisal_sheet_status(appraisal.loan_request, appraisal, basic_info)
            blockers = sheets_blocking_completion(status, max_step=6)
            if blockers:
                warnings.append('Incomplete sheets: ' + '; '.join(str(b) for b in blockers[:5]))
        except Exception:
            pass

    return blocks, warnings
