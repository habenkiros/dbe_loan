"""DBE work units for the prototyping PDF.

Job stays on CustomUser.role (officer, VP, board, …). Desk stays on
Department.key. DECSI departments (cooperative, credit, management, board)
remain valid and are not replaced.

Same 8-stage spine for every product. Appraisal *content* is per family:
DECSI 7-sheet only for FAMILY_GENERAL. Project / lease / wholesale / IFB /
idea use product desks already in loans.engines.
"""

from __future__ import annotations

from typing import Optional

from loans.product_family import (
    FAMILY_CONSUMER,
    FAMILY_EXTERNAL_FUND,
    FAMILY_GENERAL,
    FAMILY_IDEA_EQUITY,
    FAMILY_IFB_IJARAH,
    FAMILY_IFB_MURABAHA,
    FAMILY_LEASE,
    FAMILY_PROJECT,
    FAMILY_WHOLESALE,
    resolve_product_family,
)

# --- Desk keys (Department.key). DECSI keys stay in models.Department. ---

DESK_CRM = 'crm'
DESK_APPRAISAL = 'appraisal'
DESK_ENGINEERING = 'engineering'
DESK_LEGAL = 'legal'
DESK_FINANCE = 'finance'
DESK_HRM = 'hrm'
DESK_ONGOING_CONCERN = 'ongoing_concern'
DESK_SCAN_ADMIN = 'scan_admin'
DESK_ITS = 'its'
DESK_MIS = 'mis'
DESK_EXTERNAL_FUND = 'external_fund'

# DECSI HO credit — not a DBE prototyping inbox.
DESK_CREDIT = 'credit'

DBE_DESK_SEED = (
    (DESK_CRM, 'Credit Relation Management (CRM)', 10),
    (DESK_APPRAISAL, 'Appraisal Directorate', 11),
    (DESK_ENGINEERING, 'Engineering Directorate', 12),
    (DESK_LEGAL, 'Legal Affairs Directorate', 13),
    (DESK_HRM, 'Human Resource Management', 14),
    (DESK_ONGOING_CONCERN, 'Ongoing Concern & Acquired Assets', 15),
    (DESK_SCAN_ADMIN, 'Scanning / Admin Unit', 16),
    (DESK_ITS, 'ITS Directorate', 17),
    (DESK_MIS, 'PM & MIS Directorate', 18),
    (DESK_EXTERNAL_FUND, 'External Fund & Wholesale Financing', 19),
)

# --- Appraisal mechanism (what the officer fills). Not the 8-stage spine. ---

MECH_SHEETS = 'sheets'
MECH_PROJECT = 'project'
MECH_LEASE = 'lease'
MECH_WHOLESALE = 'wholesale'
MECH_MURABAHA = 'ifb_murabaha'
MECH_IJARAH = 'ifb_ijarah'
MECH_IDEA = 'idea_equity'
MECH_CONSUMER = 'consumer'

FAMILY_APPRAISAL_MECHANISM = {
    FAMILY_GENERAL: MECH_SHEETS,
    FAMILY_PROJECT: MECH_PROJECT,
    FAMILY_LEASE: MECH_LEASE,
    FAMILY_WHOLESALE: MECH_WHOLESALE,
    FAMILY_IFB_MURABAHA: MECH_MURABAHA,
    FAMILY_IFB_IJARAH: MECH_IJARAH,
    FAMILY_IDEA_EQUITY: MECH_IDEA,
    FAMILY_CONSUMER: MECH_CONSUMER,
    # A file whose *category* is the fund window still uses sheets until Credit
    # gives that window its own pack. Donor covenants can also tag any family.
    FAMILY_EXTERNAL_FUND: MECH_SHEETS,
}

# Who originates the file (CRM spine from the PDF, except the two specials).
FAMILY_INTAKE_DESK = {
    FAMILY_GENERAL: DESK_CREDIT,
    FAMILY_PROJECT: DESK_CRM,
    FAMILY_LEASE: DESK_CRM,
    FAMILY_IFB_MURABAHA: DESK_CRM,
    FAMILY_IFB_IJARAH: DESK_CRM,
    FAMILY_IDEA_EQUITY: DESK_CRM,
    FAMILY_CONSUMER: DESK_HRM,
    FAMILY_WHOLESALE: DESK_EXTERNAL_FUND,
    FAMILY_EXTERNAL_FUND: DESK_EXTERNAL_FUND,
}

# PDF stage → owning work unit. Committees are config, not a Department.
STAGE_OWNERS = {
    'onboarding': (DESK_SCAN_ADMIN, DESK_CRM),
    'kyc': (DESK_CRM, DESK_ENGINEERING, DESK_LEGAL),
    'appraisal': (DESK_APPRAISAL, DESK_ENGINEERING, DESK_CRM),
    'review': (),  # Loan Review Committee
    'approval': (),  # District / Corporate Approval Committee
    'contracting': (DESK_CRM, DESK_LEGAL),
    'disbursement': (DESK_FINANCE,),
    'monitoring': (DESK_CRM,),
    'foreclosure': (DESK_ONGOING_CONCERN,),
}

COMMITTEE_STAGES = frozenset({'review', 'approval'})


def appraisal_mechanism(family_or_loan) -> str:
    family = _family(family_or_loan)
    return FAMILY_APPRAISAL_MECHANISM.get(family, MECH_SHEETS)


def uses_decsi_sheets(family_or_loan) -> bool:
    return appraisal_mechanism(family_or_loan) == MECH_SHEETS


def intake_desk(family_or_loan) -> str:
    family = _family(family_or_loan)
    return FAMILY_INTAKE_DESK.get(family, DESK_CRM)


def stage_owners(stage: str) -> tuple:
    return STAGE_OWNERS.get(stage, ())


def user_desk_key(user) -> Optional[str]:
    dept = getattr(user, 'department', None)
    if dept is None:
        return None
    return getattr(dept, 'key', None) or None


def _family(family_or_loan) -> str:
    if family_or_loan is None:
        return FAMILY_GENERAL
    if isinstance(family_or_loan, str):
        return family_or_loan
    return resolve_product_family(family_or_loan)
