"""DBE staff / portal registration: party and intake follow the product family.

DECSI general files keep core-banking customer lookup. Other families collect
the DFI party (person, PFI, promoter) and the product file on the same form.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Type

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
    family_label,
    resolve_product_family,
)

PARTY_PERSON = 'person'
PARTY_INSTITUTION = 'institution'
PARTY_PROMOTER = 'promoter'

PARTY_BY_FAMILY = {
    FAMILY_GENERAL: PARTY_PERSON,
    FAMILY_CONSUMER: PARTY_PERSON,
    FAMILY_LEASE: PARTY_PERSON,
    FAMILY_IFB_IJARAH: PARTY_PERSON,
    FAMILY_IFB_MURABAHA: PARTY_PERSON,
    FAMILY_EXTERNAL_FUND: PARTY_PERSON,
    FAMILY_WHOLESALE: PARTY_INSTITUTION,
    FAMILY_PROJECT: PARTY_PROMOTER,
    FAMILY_IDEA_EQUITY: PARTY_PROMOTER,
}

INTAKE_PREFIX = {
    FAMILY_PROJECT: 'intake_project',
    FAMILY_WHOLESALE: 'intake_wholesale',
    FAMILY_LEASE: 'intake_lease',
    FAMILY_IFB_IJARAH: 'intake_lease',
    FAMILY_IFB_MURABAHA: 'intake_murabaha',
    FAMILY_IDEA_EQUITY: 'intake_idea',
    FAMILY_CONSUMER: 'intake_consumer',
}

OVERLAY_URL = {
    FAMILY_PROJECT: 'project_file',
    FAMILY_WHOLESALE: 'wholesale_file',
    FAMILY_LEASE: 'lease_file',
    FAMILY_IFB_IJARAH: 'lease_file',
    FAMILY_IFB_MURABAHA: 'murabaha_file',
    FAMILY_IDEA_EQUITY: 'idea_file',
    FAMILY_CONSUMER: 'consumer_file',
}

FAMILY_GUIDES = {
    FAMILY_GENERAL: (
        'Ordinary MSME / corporate working-capital or term file. '
        'Look up the customer on core banking, then amount and security.'
    ),
    FAMILY_CONSUMER: (
        'Housing / vehicle consumer line. HRM scorecard: employer, salary, DTI, LTV. '
        'Not MSME Sheet 3 cashflow.'
    ),
    FAMILY_PROJECT: (
        'DBE project financing. Viability first: sector, location, debt–equity '
        '(typically 75:25 domestic, 50:50 FDI / park), promoter equity, then requested debt. '
        'Equity before first loan release. Tenor can run to 20 years including grace.'
    ),
    FAMILY_LEASE: (
        'Hire-purchase of new capital goods only. DBE owns the asset until the last installment. '
        'Lessee contribution ≥ 20%. Insurance / transport / install ≤ 15% of asset price. '
        'Extra working capital belongs on another bank, not inside the lease.'
    ),
    FAMILY_IFB_IJARAH: (
        'TA’AWUN Ijarah — same asset register as lease, plus rental and a Sharia trail. '
        'Not Sheet 7 interest. New goods; bank holds title until the last rent.'
    ),
    FAMILY_IFB_MURABAHA: (
        'TA’AWUN Murabaha is a cost-plus sale, not an interest loan. '
        'Enter goods, supplier, cost, and markup. Project-scale files route to IFB HO.'
    ),
    FAMILY_WHOLESALE: (
        'The borrower is a licensed PFI (bank, MFI, RUSACCO, leasing company). '
        'DBE takes institution risk and the PFI on-lends. Not MSME Sheet 3. '
        'Usually booked on a funding window (KfW, RUFIP, SMEFP).'
    ),
    FAMILY_EXTERNAL_FUND: (
        'Same credit file as the product, tagged to a donor or government envelope. '
        'Pick the funding window and keep covenant cuts (women / youth / region) in view.'
    ),
    FAMILY_IDEA_EQUITY: (
        'Idea / quasi-equity: start-up ≤ 5 years, implement in Ethiopia, DBE takes a share. '
        'Need IP, MoLS training, or a start-up label — not an installment table.'
    ),
}


def party_for_family(family: str) -> str:
    return PARTY_BY_FAMILY.get(family or FAMILY_GENERAL, PARTY_PERSON)


def requires_cbs_customer(family: str) -> bool:
    return (family or FAMILY_GENERAL) == FAMILY_GENERAL


def collateral_required(category_or_family=None) -> bool:
    """Per loan type when a category is passed; otherwise family policy default."""
    from loans.family_policy import category_requires_collateral, family_requires_collateral
    from loans.models import LoanCategory

    if category_or_family is None:
        return True
    if isinstance(category_or_family, LoanCategory):
        return category_requires_collateral(category_or_family)
    if not isinstance(category_or_family, str) and hasattr(category_or_family, 'product_family'):
        return category_requires_collateral(category_or_family)
    family = category_or_family if isinstance(category_or_family, str) else family_of_category(category_or_family)
    return family_requires_collateral(family)


def family_of_category(category) -> str:
    if category is None:
        return FAMILY_GENERAL
    return getattr(category, 'product_family', None) or FAMILY_GENERAL


def overlay_url_name(family: str) -> Optional[str]:
    return OVERLAY_URL.get(family)


def intake_form_class(family: str):
    from loans.forms import (
        IdeaIntakeForm,
        LeaseIntakeForm,
        MurabahaIntakeForm,
        PfiIntakeForm,
        ProjectIntakeForm,
        ConsumerIntakeForm,
    )

    mapping: Dict[str, Type] = {
        FAMILY_PROJECT: ProjectIntakeForm,
        FAMILY_WHOLESALE: PfiIntakeForm,
        FAMILY_LEASE: LeaseIntakeForm,
        FAMILY_IFB_IJARAH: LeaseIntakeForm,
        FAMILY_IFB_MURABAHA: MurabahaIntakeForm,
        FAMILY_IDEA_EQUITY: IdeaIntakeForm,
        FAMILY_CONSUMER: ConsumerIntakeForm,
    }
    return mapping.get(family)


def intake_prefix(family: str) -> str:
    return INTAKE_PREFIX.get(family, 'intake')


def empty_intake_forms() -> Dict[str, Any]:
    from loans.forms import (
        IdeaIntakeForm,
        LeaseIntakeForm,
        MurabahaIntakeForm,
        PfiIntakeForm,
        ProjectIntakeForm,
        ConsumerIntakeForm,
    )

    return {
        FAMILY_PROJECT: ProjectIntakeForm(prefix=INTAKE_PREFIX[FAMILY_PROJECT]),
        FAMILY_WHOLESALE: PfiIntakeForm(prefix=INTAKE_PREFIX[FAMILY_WHOLESALE]),
        FAMILY_LEASE: LeaseIntakeForm(prefix=INTAKE_PREFIX[FAMILY_LEASE]),
        FAMILY_IFB_MURABAHA: MurabahaIntakeForm(prefix=INTAKE_PREFIX[FAMILY_IFB_MURABAHA]),
        FAMILY_IDEA_EQUITY: IdeaIntakeForm(prefix=INTAKE_PREFIX[FAMILY_IDEA_EQUITY]),
        FAMILY_CONSUMER: ConsumerIntakeForm(prefix=INTAKE_PREFIX[FAMILY_CONSUMER]),
    }


def bind_intake_form(family: str, data=None):
    cls = intake_form_class(family)
    if cls is None:
        return None
    return cls(data, prefix=intake_prefix(family))


def save_intake(loan_request, family: str, form, user=None):
    if form is None or not form.is_valid():
        return None
    from loans.models import (
        ConsumerProfile,
        IdeaProfile,
        LeaseAssetProfile,
        MurabahaContract,
        PfiInstitutionProfile,
        ProjectProfile,
    )

    model = {
        FAMILY_PROJECT: ProjectProfile,
        FAMILY_WHOLESALE: PfiInstitutionProfile,
        FAMILY_LEASE: LeaseAssetProfile,
        FAMILY_IFB_IJARAH: LeaseAssetProfile,
        FAMILY_IFB_MURABAHA: MurabahaContract,
        FAMILY_IDEA_EQUITY: IdeaProfile,
        FAMILY_CONSUMER: ConsumerProfile,
    }.get(family)
    if model is None:
        return None
    obj, _ = model.objects.get_or_create(loan_request=loan_request)
    for name, value in form.cleaned_data.items():
        setattr(obj, name, value)
    if family == FAMILY_IFB_IJARAH:
        obj.monthly_rent = form.cleaned_data.get('monthly_rent') or obj.monthly_rent
    if hasattr(obj, 'updated_by') and user is not None:
        obj.updated_by = user
    obj.save()
    return obj


def suggest_applicant_name(family: str, form) -> str:
    if form is None or not getattr(form, 'cleaned_data', None):
        return ''
    data = form.cleaned_data
    if family == FAMILY_WHOLESALE:
        return (data.get('institution_name') or '')[:255]
    if family == FAMILY_PROJECT:
        return (data.get('project_title') or '')[:255]
    if family == FAMILY_IDEA_EQUITY:
        return (data.get('venture_name') or '')[:255]
    return ''


def suggest_amount(family: str, form):
    if form is None or not getattr(form, 'cleaned_data', None):
        return None
    data = form.cleaned_data
    if family == FAMILY_PROJECT:
        return data.get('requested_debt')
    if family == FAMILY_WHOLESALE:
        return data.get('facility_amount')
    if family in (FAMILY_LEASE, FAMILY_IFB_IJARAH):
        return data.get('asset_price')
    if family == FAMILY_IFB_MURABAHA:
        return data.get('cost_price')
    return None


def funds_for_category(category):
    """Own-book / untagged windows are universal. Donor lines attach to products."""
    from django.db.models import Count

    from loans.models import FinancingFund

    active = FinancingFund.objects.filter(is_active=True)
    unrestricted = active.annotate(n=Count('eligible_categories')).filter(n=0)
    if category is None or not getattr(category, 'pk', None):
        return unrestricted.order_by('name')
    restricted = active.filter(eligible_categories=category)
    return (unrestricted | restricted).distinct().order_by('name')


def collateral_for_category(category):
    """Family policy when M2M is empty. Restricted products never fall back to 'any'."""
    from loans.collateral_policy import collateral_queryset_for_category

    return collateral_queryset_for_category(category)


def category_family_payload(categories) -> list:
    rows = []
    for cat in categories:
        family = family_of_category(cat)
        rows.append({
            'id': cat.id,
            'name': cat.name,
            'family': family,
            'family_label': family_label(family),
            'party': party_for_family(family),
            'guide': FAMILY_GUIDES.get(family, ''),
            'needs_cbs': requires_cbs_customer(family),
            'needs_collateral': collateral_required(cat),
            'has_intake': family in INTAKE_PREFIX,
            'fund_ids': list(funds_for_category(cat).values_list('id', flat=True)),
            'collateral_ids': list(collateral_for_category(cat).values_list('id', flat=True)),
        })
    return rows


def family_from_loan(loan_request) -> str:
    return resolve_product_family(loan_request)
