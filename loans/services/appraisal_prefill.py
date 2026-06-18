"""Pull registration, uploaded documents, and collateral into loan appraisal sheets."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from django.db import models

from loans.models import (
    AppraisalCreditHistoryEntry,
    LoanAppraisal,
    LoanRequest,
    LoanRequestBasicInfo,
    LoanRequestDocument,
)


# Sheet 1 (LoanRequestBasicInfo) + Sheet 2 (LoanAppraisal) fields officers may auto-fill.
BASIC_INFO_EXTRACT_FIELDS = {
    'tin_number', 'gender', 'age', 'marital_status', 'education_level', 'home_address',
    'spouse_name', 'spouse_occupation', 'father_name', 'grandfather_name',
    'business_name', 'business_description', 'business_address', 'date_business_started',
    'form_of_ownership', 'economic_sector', 'subsector_activity',
    'employees_full_time', 'employees_part_time', 'employees_seasonal',
    'family_members_employed', 'number_business_owners', 'peak_sales_months', 'lowest_sales_months',
    'term_months', 'repayment_frequency', 'interest_rate', 'interest_basis',
    'grace_period_months', 'interest_only_months', 'instalments_per_year', 'cash_contribution',
}

APPRAISAL_EXTRACT_FIELDS = {
    'nbe_credit_report_obtained', 'nbe_report_date_received', 'total_number_repaid_loans',
    'credit_history_max_score', 'bureau_score', 'bureau_score_band', 'bureau_report_date',
    'bureau_active_loans_count', 'bureau_total_outstanding', 'bureau_total_monthly_debt_service',
    'bureau_inquiries_6m', 'bureau_defaults_ever', 'bureau_restructured_ever', 'bureau_thin_file',
    'business_assessment', 'character_assessment',
}


def parse_extraction_mappings(raw: str) -> List[Tuple[str, str]]:
    """
    Lines: field_name=Label in document
    Or:    field_name=regex:pattern  (first capture group = value)
  """
    mappings: List[Tuple[str, str]] = []
    for line in (raw or '').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        field, pattern = line.split('=', 1)
        field = field.strip()
        pattern = pattern.strip()
        if field and pattern:
            mappings.append((field, pattern))
    return mappings


def _normalize_ws(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').strip())


def _value_after_label(text: str, label: str) -> Optional[str]:
    if not label:
        return None
    pattern = re.compile(
        re.escape(label) + r'\s*[:\-]?\s*([^\n\r]{1,300})',
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if match:
        return match.group(1).strip(' .:;-')
    return None


def extract_fields_from_text(mappings: List[Tuple[str, str]], text: str) -> Dict[str, str]:
    if not text or not mappings:
        return {}
    found: Dict[str, str] = {}
    for field, pattern in mappings:
        if field in found and found[field]:
            continue
        value: Optional[str] = None
        if pattern.lower().startswith('regex:'):
            regex = pattern[6:].strip()
            try:
                match = re.search(regex, text, re.IGNORECASE | re.MULTILINE)
                if match:
                    value = (match.group(1) if match.lastindex else match.group(0)).strip()
            except re.error:
                continue
        else:
            value = _value_after_label(text, pattern)
        if value:
            found[field] = value
    return found


def _coerce_basic_info_value(field: str, raw: str):
    model_field = LoanRequestBasicInfo._meta.get_field(field)
    raw = (raw or '').strip()
    if not raw:
        return None
    if isinstance(model_field, models.PositiveIntegerField):
        digits = re.sub(r'\D', '', raw)
        return int(digits) if digits else None
    if isinstance(model_field, models.DecimalField):
        cleaned = re.sub(r'[^\d.\-]', '', raw.replace(',', ''))
        return Decimal(cleaned) if cleaned else None
    if isinstance(model_field, models.DateField):
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y', '%d %b %Y', '%d %B %Y'):
            try:
                return datetime.strptime(raw[:30].strip(), fmt).date()
            except ValueError:
                continue
        return None
    if field == 'gender':
        low = raw.lower()
        if 'female' in low or low.startswith('f'):
            return 'Female'
        if 'male' in low or low.startswith('m'):
            return 'Male'
    if field == 'form_of_ownership':
        return _normalize_ownership(raw)
    if field == 'economic_sector':
        return _normalize_sector(raw)
    if field == 'marital_status':
        return _normalize_marital(raw)
    if field == 'education_level':
        return _normalize_education(raw)
    if field == 'repayment_frequency':
        return _normalize_repayment_frequency(raw)
    if field == 'interest_basis':
        low = raw.lower()
        if 'flat' in low:
            return LoanRequestBasicInfo.INTEREST_FLAT
        if 'declin' in low:
            return LoanRequestBasicInfo.INTEREST_DECLINING
    return raw[: model_field.max_length] if hasattr(model_field, 'max_length') and model_field.max_length else raw


def _coerce_appraisal_value(field: str, raw: str):
    model_field = LoanAppraisal._meta.get_field(field)
    raw = (raw or '').strip()
    if not raw:
        return None
    if isinstance(model_field, models.BooleanField):
        low = raw.lower()
        if low in ('yes', 'y', 'true', '1', 'obtained'):
            return True
        if low in ('no', 'n', 'false', '0'):
            return False
        return None
    if isinstance(model_field, models.PositiveIntegerField):
        digits = re.sub(r'\D', '', raw)
        return int(digits) if digits else None
    if isinstance(model_field, models.DecimalField):
        cleaned = re.sub(r'[^\d.\-]', '', raw.replace(',', ''))
        return Decimal(cleaned) if cleaned else None
    if isinstance(model_field, models.DateField):
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
            try:
                return datetime.strptime(raw[:30].strip(), fmt).date()
            except ValueError:
                continue
        return None
    return raw


def _normalize_ownership(raw: str) -> Optional[str]:
    low = raw.lower()
    choices = dict(LoanRequestBasicInfo.OWNERSHIP_CHOICES)
    for key, label in choices.items():
        if label.lower() in low or key.lower() in low:
            return key
    if 'sole' in low:
        return LoanRequestBasicInfo.OWNERSHIP_SOLE
    if 'plc' in low:
        return LoanRequestBasicInfo.OWNERSHIP_PLC
    if 'partner' in low:
        return LoanRequestBasicInfo.OWNERSHIP_PARTNERSHIP
    return None


def _normalize_sector(raw: str) -> Optional[str]:
    low = raw.lower()
    for key, label in LoanRequestBasicInfo.SECTOR_CHOICES:
        if label.lower() in low or key.lower() in low:
            return key
    if 'trade' in low or 'retail' in low:
        return LoanRequestBasicInfo.SECTOR_TRADE
    if 'agri' in low:
        return LoanRequestBasicInfo.SECTOR_AGRICULTURE
    if 'construct' in low:
        return LoanRequestBasicInfo.SECTOR_CONSTRUCTION
    if 'manufact' in low:
        return LoanRequestBasicInfo.SECTOR_MANUFACTURING
    if 'service' in low:
        return LoanRequestBasicInfo.SECTOR_SERVICE
    return None


def _normalize_marital(raw: str) -> Optional[str]:
    low = raw.lower()
    for key, label in LoanRequestBasicInfo.MARITAL_CHOICES:
        if label.lower() in low:
            return key
    return None


def _normalize_education(raw: str) -> Optional[str]:
    low = raw.lower()
    for key, label in LoanRequestBasicInfo.EDUCATION_CHOICES:
        if label.lower() in low:
            return key
    return None


def _normalize_repayment_frequency(raw: str) -> Optional[str]:
    low = raw.lower()
    for key, label in LoanRequestBasicInfo.REPAYMENT_FREQUENCY_CHOICES:
        if label.lower() in low:
            return key
    return None


def _guess_sector_from_category(category_name: str) -> Optional[str]:
    return _normalize_sector(category_name or '')


def _set_if_empty(instance, field: str, value, only_empty: bool) -> bool:
    if value is None or value == '':
        return False
    current = getattr(instance, field, None)
    if only_empty and current not in (None, ''):
        return False
    setattr(instance, field, value)
    return True


def prefill_basic_info_from_registration(
    loan_request: LoanRequest,
    basic_info: LoanRequestBasicInfo,
    *,
    only_empty: bool = True,
) -> List[str]:
    filled: List[str] = []
    if _set_if_empty(basic_info, 'business_name', loan_request.applicant_name, only_empty):
        filled.append('business_name ← applicant name')
    if loan_request.reason and _set_if_empty(
        basic_info, 'business_description', loan_request.reason[:4000], only_empty,
    ):
        filled.append('business_description ← loan reason')
    sector = _guess_sector_from_category(getattr(loan_request.category, 'name', '') or '')
    if sector and _set_if_empty(basic_info, 'economic_sector', sector, only_empty):
        filled.append(f'economic_sector ← loan category ({sector})')
    if _set_if_empty(basic_info, 'form_of_ownership', LoanRequestBasicInfo.OWNERSHIP_SOLE, only_empty):
        filled.append('form_of_ownership ← default (Sole Proprietorship)')
    if filled:
        basic_info.save()
    return filled


def _document_extracted_text(doc: LoanRequestDocument) -> str:
    checks = doc.automated_checks or {}
    preview = checks.get('extracted_text_preview') or ''
    if preview:
        return preview
    content = checks.get('content_validation') or {}
    preview = content.get('extracted_text_preview') or ''
    return preview


def _ensure_document_text(doc: LoanRequestDocument) -> str:
    from loans.services.document_auth import _extract_text_best_effort

    text = _document_extracted_text(doc)
    if text:
        return text
    if not doc.file:
        return ''
    ext = doc.get_file_extension()
    extraction = _extract_text_best_effort(doc.file, ext)
    text = extraction.get('text') or ''
    if text:
        checks = dict(doc.automated_checks or {})
        checks['extracted_text_preview'] = text[:12000]
        doc.automated_checks = checks
        doc.save(update_fields=['automated_checks'])
    return text


def extract_fields_for_document(doc: LoanRequestDocument) -> Dict[str, str]:
    doc_type = doc.document_type
    mappings = parse_extraction_mappings(doc_type.content_extraction_mappings)
    if not mappings:
        checks = doc.automated_checks or {}
        cached = checks.get('extracted_fields')
        if isinstance(cached, dict):
            return {k: str(v) for k, v in cached.items()}
        return {}
    text = _ensure_document_text(doc)
    fields = extract_fields_from_text(mappings, text)
    if fields:
        checks = dict(doc.automated_checks or {})
        checks['extracted_fields'] = fields
        doc.automated_checks = checks
        doc.save(update_fields=['automated_checks'])
    return fields


def apply_document_extractions(
    loan_request: LoanRequest,
    basic_info: LoanRequestBasicInfo,
    appraisal: LoanAppraisal,
    *,
    only_empty: bool = True,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    docs = loan_request.application_documents.select_related('document_type').order_by('uploaded_at')
    for doc in docs:
        if not doc.document_type.content_extraction_mappings.strip():
            continue
        fields = extract_fields_for_document(doc)
        if not fields:
            continue
        applied: Dict[str, str] = {}
        for field, raw in fields.items():
            if field in BASIC_INFO_EXTRACT_FIELDS:
                value = _coerce_basic_info_value(field, raw)
                if value is not None and _set_if_empty(basic_info, field, value, only_empty):
                    applied[field] = str(value)
            elif field in APPRAISAL_EXTRACT_FIELDS:
                value = _coerce_appraisal_value(field, raw)
                if value is not None and _set_if_empty(appraisal, field, value, only_empty):
                    applied[field] = str(value)
        if applied:
            results.append({
                'document_type': doc.document_type.name,
                'document_id': doc.id,
                'fields': applied,
            })
    if results:
        basic_info.save()
        appraisal.save()
    return results


def compute_collateral_totals(loan_request: LoanRequest) -> Dict[str, Decimal]:
    from collateral.models import Building, BuildingValuation, LandValuation, OtherCollateralItem

    buildings = Building.objects.filter(loan_request=loan_request)
    total_buildings = Decimal('0')
    for building in buildings:
        rows = BuildingValuation.objects.filter(building=building)
        total_buildings += sum((r.total or Decimal('0')) for r in rows)
    try:
        land = LandValuation.objects.get(loan_request=loan_request)
        land_value = land.total_value or Decimal('0')
    except LandValuation.DoesNotExist:
        land_value = Decimal('0')
    other_items = OtherCollateralItem.objects.filter(loan_request=loan_request)
    total_other = sum((item.estimated_value or Decimal('0')) for item in other_items)
    ct = (loan_request.collateral.name or '').lower()
    if 'building' in ct or 'house' in ct or 'construction' in ct:
        grand_total = total_buildings
        immovable = total_buildings
        moveable = Decimal('0')
    elif 'land' in ct:
        grand_total = land_value
        immovable = land_value
        moveable = Decimal('0')
    elif any(x in ct for x in ('vehicle', 'machinery', 'equipment', 'other')):
        grand_total = total_other
        immovable = Decimal('0')
        moveable = total_other
    else:
        grand_total = total_buildings + land_value + total_other
        immovable = total_buildings + land_value
        moveable = total_other
    return {
        'total_buildings': total_buildings,
        'land_value': land_value,
        'total_other': total_other,
        'grand_total': grand_total,
        'collateral_immovable_value': immovable,
        'collateral_moveable_value': moveable,
    }


def sync_collateral_to_appraisal(
    loan_request: LoanRequest,
    appraisal: LoanAppraisal,
    *,
    only_empty: bool = True,
) -> List[str]:
    totals = compute_collateral_totals(loan_request)
    if totals['grand_total'] <= 0:
        return []
    filled: List[str] = []
    if _set_if_empty(appraisal, 'collateral_immovable_value', totals['collateral_immovable_value'], only_empty):
        filled.append('collateral_immovable_value ← collateral module')
    if _set_if_empty(appraisal, 'collateral_moveable_value', totals['collateral_moveable_value'], only_empty):
        filled.append('collateral_moveable_value ← collateral module')
    if _set_if_empty(appraisal, 'collateral_total_value', totals['grand_total'], only_empty):
        filled.append('collateral_total_value ← collateral module')
    amount = loan_request.amount_requested or Decimal('0')
    if amount > 0 and (
        not only_empty or not appraisal.collateral_coverage_ratio
    ):
        ratio = (totals['grand_total'] / amount).quantize(Decimal('0.01'))
        if _set_if_empty(appraisal, 'collateral_coverage_ratio', ratio, only_empty):
            filled.append('collateral_coverage_ratio ← computed')
    if filled:
        appraisal.save()
    return filled


def apply_nbe_document_hints(
    loan_request: LoanRequest,
    appraisal: LoanAppraisal,
    *,
    only_empty: bool = True,
) -> List[str]:
    """If an NBE/credit document type name matches, mark report obtained."""
    filled: List[str] = []
    for doc in loan_request.application_documents.select_related('document_type'):
        name = (doc.document_type.name or '').lower()
        if any(k in name for k in ('nbe', 'credit report', 'bureau')):
            if doc.auth_status in (
                LoanRequestDocument.AUTH_AUTO_PASSED,
                LoanRequestDocument.AUTH_VERIFIED,
            ):
                if _set_if_empty(appraisal, 'nbe_credit_report_obtained', True, only_empty):
                    filled.append('nbe_credit_report_obtained ← uploaded credit document')
                break
    if filled:
        appraisal.save()
    return filled


def sync_appraisal_from_sources(
    loan_request: LoanRequest,
    *,
    only_empty: bool = True,
    include_collateral: bool = True,
) -> Dict[str, Any]:
    """Registration + documents + collateral → Sheet 1 / 2 / 5 fields (empty only by default)."""
    basic_info, _ = LoanRequestBasicInfo.objects.get_or_create(loan_request=loan_request)
    appraisal, _ = LoanAppraisal.objects.get_or_create(loan_request=loan_request)
    report: Dict[str, Any] = {
        'registration': prefill_basic_info_from_registration(loan_request, basic_info, only_empty=only_empty),
        'documents': apply_document_extractions(loan_request, basic_info, appraisal, only_empty=only_empty),
        'nbe_hints': apply_nbe_document_hints(loan_request, appraisal, only_empty=only_empty),
        'collateral': [],
    }
    if include_collateral:
        report['collateral'] = sync_collateral_to_appraisal(loan_request, appraisal, only_empty=only_empty)
    report['total_fields'] = (
        len(report['registration'])
        + sum(len(d['fields']) for d in report['documents'])
        + len(report['nbe_hints'])
        + len(report['collateral'])
    )
    return report
