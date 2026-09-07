"""DBE vs DECSI portal access.

Staff stay on CustomUser + hub roles. External parties stay on ApplicantAccount.
DECSI persons keep the CBS customer-number door. DBE institutions and promoters
see different products and fill the same overlay files the back office uses.
"""

from __future__ import annotations

from loans.product_family import (
    FAMILY_CHOICES,
    FAMILY_CONSUMER,
    FAMILY_EXTERNAL_FUND,
    FAMILY_GENERAL,
    FAMILY_IDEA_EQUITY,
    FAMILY_IFB_IJARAH,
    FAMILY_IFB_MURABAHA,
    FAMILY_LEASE,
    FAMILY_PROJECT,
    FAMILY_WHOLESALE,
)

ACTOR_PERSON = 'person'
ACTOR_INSTITUTION = 'institution'
ACTOR_PROMOTER = 'promoter'

ACTOR_CHOICES = [
    (ACTOR_PERSON, 'Customer (MSME / retail)'),
    (ACTOR_INSTITUTION, 'Institution (bank / MFI / PFI)'),
    (ACTOR_PROMOTER, 'Project / idea promoter'),
]

# What each external actor may apply for. DECSI deploy only has general → persons.
FAMILIES_FOR_ACTOR = {
    ACTOR_PERSON: (
        FAMILY_GENERAL, FAMILY_CONSUMER, FAMILY_LEASE,
        FAMILY_IFB_MURABAHA, FAMILY_IFB_IJARAH,
    ),
    ACTOR_INSTITUTION: (FAMILY_WHOLESALE, FAMILY_EXTERNAL_FUND),
    ACTOR_PROMOTER: (FAMILY_PROJECT, FAMILY_IDEA_EQUITY),
}

PRODUCT_FILE_FAMILIES = {
    FAMILY_PROJECT, FAMILY_WHOLESALE, FAMILY_LEASE,
    FAMILY_IFB_IJARAH, FAMILY_IFB_MURABAHA, FAMILY_IDEA_EQUITY,
}


def actor_kind_of(account) -> str:
    kind = getattr(account, 'actor_kind', None) or ACTOR_PERSON
    if kind not in FAMILIES_FOR_ACTOR:
        return ACTOR_PERSON
    return kind


def families_for_account(account) -> tuple:
    return FAMILIES_FOR_ACTOR[actor_kind_of(account)]


def categories_for_account(account):
    from loans.models import LoanCategory

    return LoanCategory.objects.filter(
        product_family__in=families_for_account(account),
    ).order_by('name')


def family_of(obj) -> str:
    if obj is None:
        return FAMILY_GENERAL
    category = getattr(obj, 'category', None)
    if category is None:
        loan = getattr(obj, 'loan_request', None)
        category = getattr(loan, 'category', None) if loan is not None else None
    if category is None:
        return FAMILY_GENERAL
    family = getattr(category, 'product_family', None) or FAMILY_GENERAL
    return family if family in dict(FAMILY_CHOICES) else FAMILY_GENERAL


def needs_applicant_product(obj) -> bool:
    return family_of(obj) in PRODUCT_FILE_FAMILIES


def is_queued(application) -> bool:
    return (
        application.status == application.STATUS_SUBMITTED
        and bool(application.loan_request_id)
    )


def applicant_can_edit_product(application) -> bool:
    """Applicants keep the product file after submit; utilization after approval."""
    if application.status == application.STATUS_CANCELLED:
        return False
    loan = getattr(application, 'loan_request', None)
    if loan is None:
        return needs_applicant_product(application)
    if loan.disbursement_status in (loan.DISBURSE_DISBURSED,):
        return family_of(application) == FAMILY_WHOLESALE
    return True


def applicant_can_edit_profile(application) -> bool:
    """Main overlay form — lock after committee has decided."""
    if not applicant_can_edit_product(application):
        return False
    loan = getattr(application, 'loan_request', None)
    if loan is None:
        return True
    return loan.committee_status in (
        loan.COMMITTEE_NOT_SUBMITTED, loan.COMMITTEE_PENDING, loan.COMMITTEE_RETURNED, '',
    ) or not loan.committee_status


def portal_customer_number() -> str:
    from uuid import uuid4

    n = int(uuid4().hex[:12], 16) % (10 ** 12)
    return f'{n:012d}'
