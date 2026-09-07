"""Versioned appraisal feature snapshot for AI-ready credit scoring."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from django.utils import timezone

from .appraisal_vision import FEATURE_SCHEMA_VERSION, SAMPLE_BIBLE


def _num(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_appraisal_features(loan_request, appraisal=None, basic_info=None) -> Dict[str, Any]:
    from .models import LoanAppraisal, LoanRequestBasicInfo

    appraisal = appraisal or getattr(loan_request, 'appraisal', None)
    if appraisal is None:
        appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    basic_info = basic_info or LoanRequestBasicInfo.objects.filter(loan_request=loan_request).first()

    features: Dict[str, Any] = {
        'schema_version': FEATURE_SCHEMA_VERSION,
        'captured_at': timezone.now().isoformat(),
        'sample_bible': SAMPLE_BIBLE,
        'appraisal_mode': getattr(appraisal, 'appraisal_mode', None) if appraisal else None,
        'loan': {
            'id': loan_request.pk,
            'loan_request_id': loan_request.loan_request_id,
            'applicant_name': loan_request.applicant_name,
            'amount_requested': _num(loan_request.amount_requested),
            'branch_id': loan_request.branch_id,
            'collateral_type': getattr(getattr(loan_request, 'collateral', None), 'name', None),
            'category': getattr(getattr(loan_request, 'category', None), 'name', None),
        },
        'basic_info': {},
        'qualitative': {},
        'cashflow': {},
        'es': {},
        'collateral': {},
        'bureau': {},
        'banking': {},
        'scorecard': {},
        'outcomes': {},
        'product_desk': {},
    }

    try:
        from loans.product_intel import compact_product_desk
        features['product_desk'] = compact_product_desk(loan_request)
    except Exception:
        features['product_desk'] = {}

    if basic_info:
        features['basic_info'] = {
            'term_months': basic_info.term_months,
            'interest_rate': _num(basic_info.interest_rate),
            'repayment_frequency': basic_info.repayment_frequency,
            'interest_basis': getattr(basic_info, 'interest_basis', None),
            'economic_sector': getattr(basic_info, 'economic_sector', None),
            'loan_purpose': getattr(basic_info, 'purpose_of_loan', None) or getattr(basic_info, 'loan_purpose', None),
            'peak_sales_months': getattr(basic_info, 'peak_sales_months', None),
            'lowest_sales_months': getattr(basic_info, 'lowest_sales_months', None),
            'legal_registration_number': getattr(basic_info, 'legal_registration_number', None),
            'form_of_ownership': getattr(basic_info, 'form_of_ownership', None),
        }

    if not appraisal:
        return features

    factors = []
    for f in appraisal.qualitative_factors.all().order_by('display_order'):
        factors.append({
            'key': f.factor_key,
            'rating': f.rating,
            'weight': _num(f.weight),
            'earned_score': _num(f.earned_score),
        })
    features['qualitative'] = {
        'total_score': _num(appraisal.qualitative_total_score),
        'passed': appraisal.qualitative_passed,
        'factors': factors,
        'nbe_report': appraisal.nbe_credit_report_obtained,
    }
    features['cashflow'] = {
        'net_monthly_cashflow': _num(appraisal.net_monthly_cashflow),
        'dscr_monthly': _num(appraisal.dscr),
        'dscr_annual': _num(appraisal.dscr_annual),
        'annual_net': _num(appraisal.cf_annual_net_cashflow),
        'annual_debt_service': _num(appraisal.cf_annual_debt_service),
        'stressed_dscr': _num(appraisal.stressed_dscr),
        'max_loan_capacity': _num(getattr(appraisal, 'max_loan_capacity', None)),
        'suggested_monthly_installment': _num(getattr(appraisal, 'suggested_monthly_installment', None)),
        'proposed_monthly_installment': _num(appraisal.proposed_monthly_installment),
        'corp_annual_revenue': _num(getattr(appraisal, 'corp_annual_revenue', None)),
        'corp_operating_profit': _num(getattr(appraisal, 'corp_operating_profit', None)),
        'ratio_current': _num(getattr(appraisal, 'ratio_current', None)),
        'ratio_acid_test': _num(getattr(appraisal, 'ratio_acid_test', None)),
        'ratio_debt_equity': _num(getattr(appraisal, 'ratio_debt_equity', None)),
    }
    features['es'] = {
        'risk_category': appraisal.es_risk_category,
        'eligibility': appraisal.es_eligibility_decision,
    }
    features['collateral'] = {
        'total_value': _num(appraisal.collateral_total_value),
        'coverage_ratio': _num(appraisal.collateral_coverage_ratio),
    }
    features['bureau'] = {
        'score': _num(appraisal.bureau_score),
        'band': appraisal.bureau_score_band,
        'thin_file': appraisal.bureau_thin_file,
        'defaults_ever': appraisal.bureau_defaults_ever,
        'restructured_ever': appraisal.bureau_restructured_ever,
        'inquiries_6m': appraisal.bureau_inquiries_6m,
    }
    bb = getattr(appraisal, 'banking_behavior', None) or {}
    features['banking'] = {
        'provider': bb.get('provider'),
        'refreshed_at': (
            appraisal.banking_refreshed_at.isoformat()
            if getattr(appraisal, 'banking_refreshed_at', None) else bb.get('refreshed_at')
        ),
        'tx_count': bb.get('tx_count'),
        'avg_monthly_credit': bb.get('avg_monthly_credit'),
        'avg_monthly_debit': bb.get('avg_monthly_debit'),
        'inflow_cv': bb.get('inflow_cv'),
        'nsf_count': bb.get('nsf_count'),
        'negative_balance_days': bb.get('negative_balance_days'),
        'credit_months': bb.get('credit_months'),
        'turnover_vs_installment': bb.get('turnover_vs_installment'),
        'ending_balance': bb.get('ending_balance'),
    }
    features['scorecard'] = appraisal.scorecard_detail if getattr(appraisal, 'scorecard_detail', None) else {}
    features['outcomes'] = {
        'officer_recommendation': appraisal.recommendation,
        'amount_approved': _num(appraisal.amount_approved),
        'term_approved_months': appraisal.term_approved_months,
        'appraisal_completed_at': (
            loan_request.appraisal_completed_at.isoformat()
            if loan_request.appraisal_completed_at else None
        ),
        'committee_status': getattr(loan_request, 'committee_status', None),
    }
    return features


def persist_feature_snapshot(loan_request, appraisal=None, basic_info=None) -> Dict[str, Any]:
    snap = build_appraisal_features(loan_request, appraisal=appraisal, basic_info=basic_info)
    if appraisal is None:
        appraisal = getattr(loan_request, 'appraisal', None)
    if appraisal is not None:
        appraisal.feature_snapshot = snap
        appraisal.save(update_fields=['feature_snapshot', 'updated_at'])
    return snap
