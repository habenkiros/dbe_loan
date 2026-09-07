"""External-fund covenants. Any family can sit on a window.

Question: which donor / MoF line, and are envelope + cuts held?
DECSI files with no financing_fund never hit these gates.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.db.models import Q

from loans.product_family import FAMILY_WHOLESALE, resolve_product_family


def tokens(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [t.strip().lower() for t in str(raw).replace(';', ',').split(',') if t.strip()]


def tokens_overlap(have: Optional[str], required: Optional[str]) -> bool:
    need = set(tokens(required))
    if not need:
        return True
    have_set = set(tokens(have))
    if have_set & need:
        return True
    blob = (have or '').lower()
    return any(item in blob for item in need)


def get_fund(loan_request):
    return getattr(loan_request, 'financing_fund', None)


def get_fund_tag(loan_request):
    from django.core.exceptions import ObjectDoesNotExist

    try:
        return loan_request.fund_tag
    except ObjectDoesNotExist:
        return None


def file_amount(loan_request) -> Decimal:
    if loan_request.committee_final_amount:
        return loan_request.committee_final_amount
    from django.core.exceptions import ObjectDoesNotExist

    try:
        profile = loan_request.pfi_profile
        if profile and profile.facility_amount:
            return profile.facility_amount
    except ObjectDoesNotExist:
        pass
    return loan_request.amount_requested or Decimal('0')


def _committed_qs(fund, exclude_pk=None):
    qs = fund.loan_requests.exclude(
        Q(committee_status='committee_declined') | Q(status='Rejected')
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs


def fund_book(fund, *, exclude_pk=None) -> Dict[str, Any]:
    if fund is None:
        return {
            'envelope': None, 'committed': Decimal('0'), 'remaining': None,
            'file_count': 0, 'women_pct': None, 'youth_pct': None, 'climate_pct': None,
        }
    qs = _committed_qs(fund, exclude_pk=exclude_pk)
    committed = Decimal('0')
    women = youth = climate = tagged = 0
    rows = list(qs.select_related('fund_tag', 'pfi_profile'))
    for loan in rows:
        committed += file_amount(loan)
        tag = get_fund_tag(loan)
        if tag:
            tagged += 1
            women += 1 if tag.women_owned else 0
            youth += 1 if tag.youth_owned else 0
            climate += 1 if tag.climate_tagged else 0
        else:
            try:
                pfi = loan.pfi_profile
            except Exception:
                pfi = None
            if pfi and (pfi.target_women_pct or pfi.target_youth_pct):
                tagged += 1
                if (pfi.target_women_pct or 0) >= (fund.women_min_pct or 0):
                    women += 1
                if (pfi.target_youth_pct or 0) >= (fund.youth_min_pct or 0):
                    youth += 1
    envelope = fund.envelope_amount
    remaining = (envelope - committed) if envelope is not None else None
    n = len(rows) or tagged
    def _pct(num, den):
        if not den:
            return None
        return (Decimal(num) * Decimal('100') / Decimal(den)).quantize(Decimal('0.1'))
    return {
        'envelope': envelope,
        'committed': committed,
        'remaining': remaining,
        'file_count': len(rows),
        'women_pct': _pct(women, n),
        'youth_pct': _pct(youth, n),
        'climate_pct': _pct(climate, n),
    }


def fund_utilization_blockers(loan_request) -> List[str]:
    fund = get_fund(loan_request)
    if fund is None or fund.envelope_amount is None:
        return []
    book = fund_book(fund, exclude_pk=loan_request.pk)
    need = file_amount(loan_request)
    remaining = book['remaining']
    if remaining is not None and need > remaining + Decimal('0.01'):
        return [
            f'{fund.code} envelope is ETB {fund.envelope_amount}; '
            f'{book["committed"]} already committed and this file needs {need}.'
        ]
    return []


def fund_eligibility_blockers(loan_request) -> List[str]:
    fund = get_fund(loan_request)
    if fund is None:
        return []
    blockers = []
    tag = get_fund_tag(loan_request)
    region = (tag.region if tag else '') or ''
    sector = (tag.sector if tag else '') or ''
    from django.core.exceptions import ObjectDoesNotExist

    try:
        pfi = loan_request.pfi_profile
    except ObjectDoesNotExist:
        pfi = None
    if pfi:
        region = region or pfi.footprint_regions or pfi.target_regions
        sector = sector or pfi.target_sectors
    if fund.eligible_regions and not tokens_overlap(region, fund.eligible_regions):
        blockers.append(
            f'{fund.code} is limited to {fund.eligible_regions}. '
            'Record the file region / PFI footprint.'
        )
    if fund.eligible_sectors and not tokens_overlap(sector, fund.eligible_sectors):
        blockers.append(
            f'{fund.code} is limited to sectors: {fund.eligible_sectors}.'
        )
    return blockers


def fund_covenant_blockers(loan_request) -> List[str]:
    """Portfolio cuts bind wholesale facilities. Single MSME files are tagged, not refused."""
    fund = get_fund(loan_request)
    if fund is None:
        return []
    if resolve_product_family(loan_request) != FAMILY_WHOLESALE:
        return []
    from django.core.exceptions import ObjectDoesNotExist

    try:
        pfi = loan_request.pfi_profile
    except ObjectDoesNotExist:
        return []
    blockers = []
    if fund.women_min_pct is not None:
        got = pfi.target_women_pct
        if got is None or got + Decimal('0.01') < fund.women_min_pct:
            blockers.append(
                f'{fund.code} requires at least {fund.women_min_pct}% women on-lending.'
            )
    if fund.youth_min_pct is not None:
        got = pfi.target_youth_pct
        if got is None or got + Decimal('0.01') < fund.youth_min_pct:
            blockers.append(
                f'{fund.code} requires at least {fund.youth_min_pct}% youth on-lending.'
            )
    if fund.max_end_user_rate_pct is not None and pfi.end_user_rate_ceiling_pct is not None:
        if pfi.end_user_rate_ceiling_pct > fund.max_end_user_rate_pct + Decimal('0.01'):
            blockers.append(
                f'End-user rate ceiling {pfi.end_user_rate_ceiling_pct}% exceeds '
                f'{fund.code} maximum {fund.max_end_user_rate_pct}%.'
            )
    if fund.dbe_to_pfi_rate_pct is not None and pfi.dbe_to_pfi_rate_pct is not None:
        if pfi.dbe_to_pfi_rate_pct > fund.dbe_to_pfi_rate_pct + Decimal('0.01'):
            blockers.append(
                f'DBE→PFI rate {pfi.dbe_to_pfi_rate_pct}% exceeds '
                f'{fund.code} {fund.dbe_to_pfi_rate_pct}%.'
            )
    if fund.max_tenor_months and pfi.tenor_months and pfi.tenor_months > fund.max_tenor_months:
        blockers.append(
            f'Facility tenor {pfi.tenor_months} months exceeds {fund.code} '
            f'maximum {fund.max_tenor_months}.'
        )
    cap = fund.par90_max_pct
    if cap is not None and pfi.par90_pct is not None and pfi.par90_pct > cap + Decimal('0.01'):
        blockers.append(
            f'PFI PAR>90 is {pfi.par90_pct}%; {fund.code} allows at most {cap}%.'
        )
    return blockers


def fund_committee_blockers(loan_request) -> List[str]:
    if get_fund(loan_request) is None:
        return []
    blockers = []
    blockers.extend(fund_eligibility_blockers(loan_request))
    blockers.extend(fund_utilization_blockers(loan_request))
    blockers.extend(fund_covenant_blockers(loan_request))
    return blockers


def fund_disbursement_blockers(loan_request) -> List[str]:
    if get_fund(loan_request) is None:
        return []
    return list(fund_utilization_blockers(loan_request))


def fund_file_summary(loan_request) -> Optional[Dict[str, Any]]:
    fund = get_fund(loan_request)
    if fund is None:
        return None
    book = fund_book(fund)
    return {
        'is_fund': True,
        'is_project': False,
        'is_wholesale': False,
        'fund': fund,
        'tag': get_fund_tag(loan_request),
        'book': book,
        'committee_blockers': fund_committee_blockers(loan_request),
        'disbursement_blockers': fund_disbursement_blockers(loan_request),
    }


def fund_export_rows(fund) -> List[Dict[str, Any]]:
    rows = []
    for loan in fund.loan_requests.select_related(
        'category', 'branch', 'fund_tag', 'pfi_profile',
    ).order_by('loan_request_id'):
        tag = get_fund_tag(loan)
        try:
            pfi = loan.pfi_profile
        except Exception:
            pfi = None
        rows.append({
            'loan_request_id': loan.loan_request_id,
            'applicant': loan.applicant_name,
            'family': getattr(loan.category, 'product_family', ''),
            'amount': str(file_amount(loan)),
            'committee_status': loan.committee_status or '',
            'disbursement_status': loan.disbursement_status or '',
            'women_owned': bool(tag and tag.women_owned),
            'youth_owned': bool(tag and tag.youth_owned),
            'climate': bool(tag and tag.climate_tagged),
            'region': (tag.region if tag else '') or (pfi.footprint_regions if pfi else ''),
            'women_target_pct': str(pfi.target_women_pct) if pfi and pfi.target_women_pct is not None else '',
            'youth_target_pct': str(pfi.target_youth_pct) if pfi and pfi.target_youth_pct is not None else '',
        })
    return rows
