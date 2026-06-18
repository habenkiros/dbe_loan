# loans/appraisal_pack.py
"""Read-only appraisal data bundle for committee reviewers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .models import (
    AppraisalCreditHistoryEntry,
    AppraisalQualitativeFactor,
    LoanAppraisal,
    LoanRequest,
    LoanRequestBasicInfo,
    LoanRequestDocument,
    QUALITATIVE_FACTOR_KEYS,
)


def _display(instance, field_name: str, default='—'):
    if not instance:
        return default
    val = getattr(instance, field_name, None)
    if val is None or val == '':
        return default
    if hasattr(val, 'strftime'):
        return val.strftime('%Y-%m-%d')
    if isinstance(val, bool):
        return 'Yes' if val else 'No'
    field = instance._meta.get_field(field_name)
    if field.choices:
        return dict(field.choices).get(val, val)
    return val


def build_committee_appraisal_pack(loan_request: LoanRequest) -> Dict[str, Any]:
    basic_info = LoanRequestBasicInfo.objects.filter(loan_request=loan_request).first()
    appraisal = (
        LoanAppraisal.objects.filter(loan_request=loan_request)
        .select_related('created_by', 'es_screened_by', 'es_checked_by', 'es_approved_by')
        .first()
    )

    credit_entries = []
    qualitative = []
    es_items = []
    risks = []
    conditions = []
    amortization = []
    documents = []

    if appraisal:
        credit_entries = list(
            AppraisalCreditHistoryEntry.objects.filter(appraisal=appraisal).order_by('id')
        )
        qualitative = list(
            AppraisalQualitativeFactor.objects.filter(appraisal=appraisal).order_by('factor_key')
        )
        es_items = list(appraisal.es_checklist_items.order_by('display_order', 'id'))
        risks = list(appraisal.risk_mitigations.order_by('display_order', 'id'))
        conditions = list(appraisal.conditions.order_by('display_order', 'id'))
        amortization = list(appraisal.amortization_entries.order_by('period_number'))

    documents = list(
        loan_request.application_documents.select_related('document_type', 'uploaded_by').order_by('uploaded_at')
    )

    qual_labels = dict(QUALITATIVE_FACTOR_KEYS)

    return {
        'loan_request': loan_request,
        'basic_info': basic_info,
        'appraisal': appraisal,
        'credit_entries': credit_entries,
        'qualitative': qualitative,
        'qual_labels': qual_labels,
        'es_items': es_items,
        'risks': risks,
        'conditions': conditions,
        'amortization': amortization,
        'documents': documents,
        'display': _display,
    }
