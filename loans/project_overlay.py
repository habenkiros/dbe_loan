"""DBE project-finance overlay on the live factory.

DECSI general files never hit these gates. Appraisal stays MSME/corporate.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from loans.product_family import FAMILY_PROJECT, resolve_product_family

MAX_GRACE_MONTHS = 60
MAX_ENVELOPE_MONTHS = 240
DEBT_SHARE = {
    '75_25': Decimal('0.75'),
    '50_50': Decimal('0.50'),
    '70_30': Decimal('0.70'),
}
PROGRESS_LAG_POINTS = Decimal('15')
DRAW_PURPOSES = ('civil', 'machinery', 'working_capital', 'insurance', 'other')


PURPOSE_LABELS = {
    'promoter_cash': 'Promoter cash / in-kind',
    'dbe_loan': 'DBE loan',
    'other_bank': 'Other bank / tripartite WC',
    'grant': 'Grant / donor',
    'civil': 'Civil works',
    'machinery': 'Machinery / equipment',
    'working_capital': 'Working capital',
    'insurance': 'Insurance / ancillary',
    'other': 'Other',
}


def is_project_file(loan_request) -> bool:
    return resolve_product_family(loan_request) == FAMILY_PROJECT


def get_project_profile(loan_request):
    from django.core.exceptions import ObjectDoesNotExist

    try:
        return loan_request.project_profile
    except ObjectDoesNotExist:
        return None


def sources_uses_totals(profile) -> Dict[str, Decimal]:
    sources = Decimal('0')
    uses = Decimal('0')
    if profile is None:
        return {'sources': sources, 'uses': uses, 'gap': Decimal('0'), 'balanced': True}
    for line in profile.lines.all():
        amt = line.amount or Decimal('0')
        if line.side == line.SIDE_SOURCE:
            sources += amt
        else:
            uses += amt
    gap = sources - uses
    return {
        'sources': sources,
        'uses': uses,
        'gap': gap,
        'balanced': abs(gap) <= Decimal('1.00') and sources > 0 and uses > 0,
    }


def profile_blockers(loan_request) -> List[str]:
    if not is_project_file(loan_request):
        return []
    profile = get_project_profile(loan_request)
    if profile is None:
        return ['Open the project file: title, cost, promoter equity, and sources & uses.']
    blockers = []
    if not (profile.project_title or '').strip():
        blockers.append('Project title is required.')
    if profile.total_project_cost is None or profile.total_project_cost <= 0:
        blockers.append('Total project cost is required.')
    if profile.promoter_equity is None or profile.promoter_equity <= 0:
        blockers.append('Promoter equity is required.')
    totals = sources_uses_totals(profile)
    if totals['sources'] <= 0 or totals['uses'] <= 0:
        blockers.append('Enter at least one source and one use on the project file.')
    elif not totals['balanced']:
        blockers.append(
            f'Sources ({totals["sources"]}) and uses ({totals["uses"]}) must balance '
            f'within ETB 1.'
        )
    return blockers


def has_released_draw(loan_request) -> bool:
    if loan_request.disbursement_status in (
        loan_request.DISBURSE_PARTIAL,
        loan_request.DISBURSE_DISBURSED,
    ):
        return True
    return loan_request.disbursement_tranches.filter(status='disbursed').exists()


def unused_unlocking_visits(loan_request):
    return loan_request.monitoring_visits.filter(
        unlocks_next_tranche=True,
        unlocked_tranche__isnull=True,
        percent_complete__isnull=False,
    ).order_by('visited_at', 'id')


def facility_for_progress(loan_request) -> Decimal:
    profile = get_project_profile(loan_request)
    for amt in (
        getattr(loan_request, 'committee_final_amount', None),
        getattr(profile, 'requested_debt', None) if profile else None,
        getattr(loan_request, 'amount_requested', None),
    ):
        if amt is not None and amt > 0:
            return Decimal(amt)
    return Decimal('0')


def released_draw_total(loan_request) -> Decimal:
    total = Decimal('0')
    for tranche in loan_request.disbursement_tranches.filter(status='disbursed'):
        total += tranche.amount or Decimal('0')
    return total


def next_pending_draw_amount(loan_request) -> Decimal:
    pending = (
        loan_request.disbursement_tranches.exclude(status='disbursed')
        .order_by('sequence', 'id')
        .first()
    )
    if pending is None:
        return Decimal('0')
    return pending.amount or Decimal('0')


def progress_vs_draw_blockers(loan_request, visit) -> List[str]:
    facility = facility_for_progress(loan_request)
    nxt = next_pending_draw_amount(loan_request)
    if facility <= 0 or nxt <= 0:
        return []
    after = released_draw_total(loan_request) + nxt
    share = (after / facility) * Decimal('100')
    required = share - PROGRESS_LAG_POINTS
    if required < 0:
        required = Decimal('0')
    pct = visit.percent_complete or Decimal('0')
    if pct + Decimal('0.01') >= required:
        return []
    return [
        f'Physical progress is {pct}%; next draw would take cumulative disbursement to '
        f'{share.quantize(Decimal("1"))}% of the DBE facility. '
        f'Progress may lag by at most {PROGRESS_LAG_POINTS} points.'
    ]


def tranche_visit_blockers(loan_request) -> List[str]:
    if not is_project_file(loan_request):
        return []
    if not has_released_draw(loan_request):
        return []
    visit = unused_unlocking_visits(loan_request).first()
    if visit is None:
        return [
            'Record an implementation visit (percent complete + purpose) to unlock the next tranche.',
        ]
    return progress_vs_draw_blockers(loan_request, visit)


def consume_unlocking_visit(loan_request, tranche) -> None:
    if not is_project_file(loan_request) or tranche is None:
        return
    visit = unused_unlocking_visits(loan_request).first()
    if visit is None:
        return
    visit.unlocked_tranche = tranche
    visit.save(update_fields=['unlocked_tranche'])


def parse_decimal(raw) -> Optional[Decimal]:
    if raw is None or raw == '':
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None


def record_implementation_visit(
    loan_request,
    user,
    *,
    notes: str,
    visited_at,
    percent_complete=None,
    purpose_code: str = '',
    unlocks_next_tranche: bool = False,
    gps_lat=None,
    gps_lon=None,
):
    from loans.models import LoanMonitoringVisit

    return LoanMonitoringVisit.objects.create(
        loan_request=loan_request,
        visited_at=visited_at,
        notes=notes,
        visit_kind=LoanMonitoringVisit.KIND_IMPLEMENTATION,
        percent_complete=percent_complete,
        purpose_code=(purpose_code or '').strip(),
        unlocks_next_tranche=bool(unlocks_next_tranche),
        gps_lat=gps_lat,
        gps_lon=gps_lon,
        recorded_by=user,
    )


def equity_structure(profile) -> Dict[str, Any]:
    cost = (profile.total_project_cost if profile else None) or Decimal('0')
    equity = (profile.promoter_equity if profile else None) or Decimal('0')
    debt = (profile.requested_debt if profile else None) or Decimal('0')
    equity_pct = ((equity / cost) * 100).quantize(Decimal('0.1')) if cost > 0 else None
    debt_pct = ((debt / cost) * 100).quantize(Decimal('0.1')) if cost > 0 else None
    return {
        'cost': cost,
        'equity': equity,
        'debt': debt,
        'equity_pct': equity_pct,
        'debt_pct': debt_pct,
        'policy_blockers': debt_equity_blockers(profile),
    }


def journey_steps(loan_request, profile, totals, metrics, desks) -> List[Dict[str, Any]]:
    from loans.models import ProjectTechnicalReview

    desks = desks or []
    desks_cleared = bool(desks) and all(
        d.status == ProjectTechnicalReview.STATUS_CLEARED for d in desks
    )
    title_ok = bool(profile and (profile.project_title or '').strip() and (profile.location or '').strip())
    structure_ok = bool(
        profile
        and profile.total_project_cost
        and profile.promoter_equity
        and profile.requested_debt
        and not debt_equity_blockers(profile)
    )
    viability_ok = not viability_blockers(profile) if profile else False
    account_ok = bool(profile and profile.current_account_opened)
    return [
        {'key': 'identity', 'label': 'Identity', 'done': title_ok},
        {'key': 'structure', 'label': 'Cost & equity', 'done': structure_ok},
        {'key': 'sources', 'label': 'Sources & uses', 'done': bool(totals.get('balanced'))},
        {'key': 'viability', 'label': 'Viability', 'done': viability_ok},
        {'key': 'desks', 'label': 'Plant desks', 'done': desks_cleared},
        {'key': 'account', 'label': 'DBE account', 'done': account_ok},
    ]


def seed_lines_from_profile(profile) -> int:
    """Create a first sources & uses draft from the cost / equity / debt on the profile."""
    if profile is None or profile.lines.exists():
        return 0
    created = 0
    seq = 1
    from loans.models import ProjectSourceUseLine

    if profile.promoter_equity and profile.promoter_equity > 0:
        ProjectSourceUseLine.objects.create(
            profile=profile, side=ProjectSourceUseLine.SIDE_SOURCE,
            purpose=ProjectSourceUseLine.PURPOSE_PROMOTER,
            label='Promoter equity', amount=profile.promoter_equity, sequence=seq,
        )
        seq += 1
        created += 1
    if profile.requested_debt and profile.requested_debt > 0:
        ProjectSourceUseLine.objects.create(
            profile=profile, side=ProjectSourceUseLine.SIDE_SOURCE,
            purpose=ProjectSourceUseLine.PURPOSE_DBE,
            label='DBE loan', amount=profile.requested_debt, sequence=seq,
        )
        seq += 1
        created += 1
    if profile.other_bank_amount and profile.other_bank_amount > 0:
        ProjectSourceUseLine.objects.create(
            profile=profile, side=ProjectSourceUseLine.SIDE_SOURCE,
            purpose=ProjectSourceUseLine.PURPOSE_OTHER_BANK,
            label=profile.other_bank_name or 'Other bank',
            amount=profile.other_bank_amount, sequence=seq,
        )
        created += 1
    cost = profile.total_project_cost
    if cost and cost > 0:
        ProjectSourceUseLine.objects.create(
            profile=profile, side=ProjectSourceUseLine.SIDE_USE,
            purpose=ProjectSourceUseLine.PURPOSE_OTHER,
            label='Project investment (split on the desks later)',
            amount=cost, sequence=1,
        )
        created += 1
    return created


def project_file_summary(loan_request) -> Optional[Dict[str, Any]]:
    if not is_project_file(loan_request):
        return None
    profile = get_project_profile(loan_request)
    totals = sources_uses_totals(profile) if profile is not None else sources_uses_totals(None)
    metrics = compute_project_metrics(profile) if profile is not None else {
        'npv': None, 'irr_pct': None, 'dscr': None,
    }
    return {
        'is_project': True,
        'profile': profile,
        'totals': totals,
        'metrics': metrics,
        'profile_blockers': profile_blockers(loan_request),
        'committee_blockers': project_committee_blockers(loan_request),
        'disbursement_blockers': project_disbursement_blockers(loan_request),
        'tranche_blockers': tranche_visit_blockers(loan_request),
        'has_released_draw': has_released_draw(loan_request),
        'unused_visits': list(unused_unlocking_visits(loan_request)[:5]),
    }


def ensure_plant_desks(profile) -> None:
    from loans.models import ProjectTechnicalReview

    for desk, _ in ProjectTechnicalReview.DESK_CHOICES:
        ProjectTechnicalReview.objects.get_or_create(profile=profile, desk=desk)


def _npv(rate: Decimal, cashflows) -> Decimal:
    total = Decimal('0')
    one = Decimal('1')
    for t, cf in enumerate(cashflows):
        total += cf / ((one + rate) ** t)
    return total.quantize(Decimal('0.01'))


def _irr_pct(cashflows) -> Optional[Decimal]:
    if not cashflows or cashflows[0] >= 0:
        return None
    lo, hi = Decimal('-0.90'), Decimal('5.00')
    if _npv(lo, cashflows) * _npv(hi, cashflows) > 0:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if _npv(mid, cashflows) >= 0:
            lo = mid
        else:
            hi = mid
    return (lo * Decimal('100')).quantize(Decimal('0.01'))


def compute_project_metrics(profile) -> Dict[str, Optional[Decimal]]:
    years = list(profile.cashflows.order_by('year_number')) if profile else []
    cost = (profile.total_project_cost if profile else None) or Decimal('0')
    if not years or cost <= 0:
        return {'npv': None, 'irr_pct': None, 'dscr': None}
    rate_pct = profile.discount_rate_pct or Decimal('12')
    rate = (rate_pct / Decimal('100'))
    nets = [y.operating_cf - (y.debt_service or Decimal('0')) for y in years]
    cashflows = [-cost] + nets
    ocf = sum((y.operating_cf for y in years), Decimal('0'))
    ds = sum((y.debt_service or Decimal('0') for y in years), Decimal('0'))
    dscr = (ocf / ds).quantize(Decimal('0.01')) if ds > 0 else None
    return {
        'npv': _npv(rate, cashflows),
        'irr_pct': _irr_pct(cashflows),
        'dscr': dscr,
    }


def debt_equity_blockers(profile) -> List[str]:
    if profile is None:
        return []
    cap = DEBT_SHARE.get(profile.debt_equity_policy)
    if cap is None:
        return []
    cost = profile.total_project_cost or Decimal('0')
    debt = profile.requested_debt or Decimal('0')
    if cost <= 0 or debt <= 0:
        return []
    share = debt / cost
    if share > cap + Decimal('0.01'):
        pct = (cap * 100).quantize(Decimal('1'))
        return [
            f'Debt is { (share * 100).quantize(Decimal("0.1")) }% of project cost; '
            f'{profile.get_debt_equity_policy_display()} allows at most {pct}%.'
        ]
    return []


def tenor_blockers(profile) -> List[str]:
    if profile is None:
        return []
    blockers = []
    if profile.grace_months is not None and profile.grace_months > MAX_GRACE_MONTHS:
        blockers.append(f'Grace cannot exceed {MAX_GRACE_MONTHS} months (5 years).')
    impl = profile.implementation_months or 0
    grace = profile.grace_months or 0
    if impl + grace > MAX_ENVELOPE_MONTHS:
        blockers.append(
            f'Implementation plus grace cannot exceed {MAX_ENVELOPE_MONTHS} months (20 years).'
        )
    return blockers


def viability_blockers(profile) -> List[str]:
    if profile is None:
        return ['Enter project NPV, IRR, and project DSCR (or annual cashflows to compute them).']
    computed = compute_project_metrics(profile)
    npv = profile.npv if profile.npv is not None else computed['npv']
    irr = profile.irr_pct if profile.irr_pct is not None else computed['irr_pct']
    dscr = profile.project_dscr if profile.project_dscr is not None else computed['dscr']
    missing = []
    if npv is None:
        missing.append('NPV')
    if irr is None:
        missing.append('IRR')
    if dscr is None:
        missing.append('project DSCR')
    if missing:
        return [f'Enter {", ".join(missing)} — or add annual project cashflows to compute them.']
    if dscr is not None and dscr < Decimal('1.00'):
        return ['Project DSCR is below 1.00 — file cannot go to committee.']
    return []


def plant_desk_blockers(profile) -> List[str]:
    if profile is None:
        return ['Civil, mechanical, and electrical plant desks must be cleared.']
    from loans.models import ProjectTechnicalReview

    reviews = list(profile.technical_reviews.all())
    open_desks = [
        r.get_desk_display()
        for r in reviews
        if r.status != ProjectTechnicalReview.STATUS_CLEARED
    ]
    existing = {r.desk for r in reviews}
    for desk, label in ProjectTechnicalReview.DESK_CHOICES:
        if desk not in existing:
            open_desks.append(label)
    if open_desks:
        return [f'Plant desks not cleared: {", ".join(open_desks)}.']
    return []


def project_committee_blockers(loan_request) -> List[str]:
    if not is_project_file(loan_request):
        return []
    blockers = list(profile_blockers(loan_request))
    profile = get_project_profile(loan_request)
    blockers.extend(debt_equity_blockers(profile))
    blockers.extend(tenor_blockers(profile))
    blockers.extend(viability_blockers(profile))
    blockers.extend(plant_desk_blockers(profile))
    return blockers


def _required_equity_stage(loan_request) -> int:
    profile = get_project_profile(loan_request)
    if profile is None or profile.equity_plan != profile.EQUITY_STAGGERED:
        return 0
    released = loan_request.disbursement_tranches.filter(status='disbursed').count()
    return min(3, released + 1)


def project_disbursement_blockers(loan_request) -> List[str]:
    if not is_project_file(loan_request):
        return []
    blockers = list(profile_blockers(loan_request))
    profile = get_project_profile(loan_request)
    if profile and not profile.current_account_opened:
        blockers.append('Open a current account at DBE before the first equity or loan release.')
    if not loan_request.own_contribution_verified_at:
        blockers.append(
            'Project files require promoter equity / own contribution verified before first release.'
        )
    if profile and profile.equity_plan == profile.EQUITY_STAGGERED:
        need = _required_equity_stage(loan_request)
        if profile.equity_stage < need:
            labels = {1: '1/3', 2: '2/3', 3: '100%'}
            blockers.append(
                f'Staggered equity must reach {labels.get(need, need)} before this loan draw.'
            )
    next_t = (
        loan_request.disbursement_tranches.filter(status='pending')
        .order_by('sequence', 'id')
        .first()
    )
    if next_t and not (next_t.purpose_code or '').strip():
        blockers.append('Give the next tranche a purpose (civil, machinery, WC, insurance).')
    last_out = (
        loan_request.disbursement_tranches.filter(status='disbursed')
        .order_by('-sequence', '-id')
        .first()
    )
    if last_out and not (last_out.utilization_note or '').strip():
        blockers.append(
            'Record utilization evidence of the last draw before the next release.'
        )
    blockers.extend(tranche_visit_blockers(loan_request))
    return blockers


def can_view_project_file(user, loan_request) -> bool:
    if not is_project_file(loan_request):
        return False
    role = getattr(user, 'role', None)
    if getattr(user, 'is_superuser', False) or role in (
        'admin', 'superadmin', 'credit_head', 'branch_manager',
        'finance_manager', 'risk_compliance', 'auditor',
    ):
        return True
    if role in ('loan_officer', 'credit_loan_officer') and loan_request.assigned_loan_officer_id == user.id:
        return True
    from loans.delegation import can_access_loan_as_officer
    ok, _ = can_access_loan_as_officer(user, loan_request)
    return ok


def can_edit_project_file(user, loan_request) -> bool:
    if not can_view_project_file(user, loan_request):
        return False
    role = getattr(user, 'role', None)
    if getattr(user, 'is_superuser', False) or role in (
        'admin', 'superadmin', 'credit_head', 'branch_manager',
    ):
        return True
    if role in ('loan_officer', 'credit_loan_officer') and loan_request.assigned_loan_officer_id == user.id:
        return True
    from loans.delegation import can_access_loan_as_officer
    ok, _ = can_access_loan_as_officer(user, loan_request)
    return ok
