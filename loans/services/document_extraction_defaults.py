"""Default OCR → Sheet 1 field mappings when a document type has none configured.

Officers can still override mappings in Settings → Document types.
"""

from __future__ import annotations

from typing import Optional

# field_name=Label (or regex:…) — see appraisal_prefill.parse_extraction_mappings
_DEFAULTS = {
    'id': """# National / Kebele ID
applicant_name=Full Name
applicant_name=Name
gender=Sex
gender=Gender
tin_number=TIN
tin_number=Tax Identification
home_address=Address
home_address=Place of Residence
home_address=Region
father_name=Father
grandfather_name=Grandfather
tin_number=regex:(?:ID\\s*(?:No\\.?|Number)|Kebele\\s*ID)[:\\s]*([A-Za-z0-9\\-/]{4,})
""",
    'tin': """# TIN certificate
tin_number=TIN
tin_number=Tax Identification Number
tin_number=Taxpayer Identification
business_name=Taxpayer Name
business_name=Name of Taxpayer
business_name=Registered Name
home_address=Address
business_address=Business Address
tin_number=regex:(?:TIN|Tax\\s*ID)[:\\s#]*([0-9]{8,15})
""",
    'license': """# Business / trade license
business_name=Business Name
business_name=Trade Name
business_name=Company Name
tin_number=TIN
tin_number=Tax Identification
business_address=Address
business_address=Registered Address
business_description=Business Activity
business_description=Nature of Business
form_of_ownership=Form of Ownership
form_of_ownership=Legal Form
""",
    'bank': """# Bank statement header
business_name=Account Name
business_name=Account Holder
business_name=Customer Name
tin_number=TIN
home_address=Address
""",
    'collateral': """# Title / ownership
home_address=Property Address
home_address=Location
home_address=Site Address
home_address=Plot
home_address=Title Deed No
home_address=Parcel
""",
    'income': """# Proof of income
business_name=Employer
business_name=Business Name
home_address=Address
""",
}


def _bucket_for_name(name: str) -> Optional[str]:
    n = (name or '').lower()
    if any(k in n for k in ('national id', 'kebele', 'passport', 'id card', 'identity')):
        return 'id'
    if 'tin' in n or 'tax identification' in n:
        return 'tin'
    if any(k in n for k in ('license', 'licence', 'trade registration', 'business regist')):
        return 'license'
    if 'bank statement' in n or (n.startswith('bank') and 'statement' in n):
        return 'bank'
    if any(k in n for k in ('title', 'ownership', 'collateral', 'deed')):
        return 'collateral'
    if 'income' in n or 'salary' in n:
        return 'income'
    return None


def default_mappings_text_for_name(name: str) -> str:
    bucket = _bucket_for_name(name)
    if not bucket:
        return ''
    return _DEFAULTS[bucket].strip() + '\n'


def ensure_document_type_extraction_defaults(doc_type, *, force: bool = False) -> bool:
    """
    If content_extraction_mappings is empty, seed bank-standard defaults.
    Also turns on enable_ocr_match when we seed mappings (so identity OCR runs).
    Returns True when the type was updated.
    """
    if doc_type is None:
        return False
    existing = (doc_type.content_extraction_mappings or '').strip()
    if existing and not force:
        return False
    text = default_mappings_text_for_name(getattr(doc_type, 'name', '') or '')
    if not text:
        return False
    doc_type.content_extraction_mappings = text
    update = ['content_extraction_mappings']
    if not getattr(doc_type, 'enable_ocr_match', False):
        doc_type.enable_ocr_match = True
        update.append('enable_ocr_match')
    # Sensible identity fields for ID/TIN types
    bucket = _bucket_for_name(doc_type.name)
    if bucket in ('id', 'tin') and not (getattr(doc_type, 'identity_match_fields', None) or '').strip():
        doc_type.identity_match_fields = 'applicant_name,phone_number,tin_number'
        update.append('identity_match_fields')
    doc_type.save(update_fields=update)
    return True


def ensure_all_document_extraction_defaults(*, force: bool = False) -> int:
    from loans.models import LoanApplicationDocumentType

    n = 0
    for dt in LoanApplicationDocumentType.objects.all():
        if ensure_document_type_extraction_defaults(dt, force=force):
            n += 1
    return n


def sync_sheet1_from_documents(loan_request, *, only_empty: bool = True) -> dict:
    """Ensure defaults on types, then pull document extractions into Sheet 1."""
    from loans.models import LoanAppraisal, LoanRequestBasicInfo
    from loans.services.appraisal_prefill import apply_document_extractions

    for doc in loan_request.application_documents.select_related('document_type'):
        ensure_document_type_extraction_defaults(doc.document_type)

    basic, _ = LoanRequestBasicInfo.objects.get_or_create(loan_request=loan_request)
    appraisal, _ = LoanAppraisal.objects.get_or_create(
        loan_request=loan_request,
        defaults={'created_by': getattr(loan_request, 'assigned_loan_officer', None)},
    )
    return apply_document_extractions(
        loan_request, basic, appraisal, only_empty=only_empty, basic_info_only=True,
    )
