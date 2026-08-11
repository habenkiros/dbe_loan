"""Customer-facing repayment schedule (read-only from staff amortization)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass
class ScheduleView:
    available: bool
    message: str = ''
    amount_approved: str = ''
    term_months: str = ''
    annual_rate: str = ''
    rows: List[Dict[str, Any]] = field(default_factory=list)
    total_payment: str = ''
    total_principal: str = ''
    total_interest: str = ''


def _fmt_money(value) -> str:
    if value is None:
        return '—'
    try:
        return f'{Decimal(str(value)):,.2f} ETB'
    except Exception:
        return f'{value} ETB'


def _fmt_date(value) -> str:
    if not value:
        return '—'
    try:
        return value.strftime('%d %b %Y')
    except Exception:
        return str(value)


def can_show_schedule(loan) -> bool:
    """Schedule is customer-visible after credit approval (committee)."""
    from loans.models import LoanRequest

    if not loan:
        return False
    if loan.committee_status == LoanRequest.COMMITTEE_APPROVED:
        return True
    if loan.disbursement_status == LoanRequest.DISBURSE_DISBURSED or loan.disbursed_at:
        return True
    return False


def build_repayment_schedule(application) -> ScheduleView:
    """Read amortization entries created by staff (Sheet 7 / post-approval)."""
    from loans.committee import get_appraisal_for_loan
    from loans.disbursement import final_annual_rate_pct, final_loan_amount, final_term_months
    from loans.models import LoanRequest

    loan = getattr(application, 'loan_request', None)
    if not loan:
        return ScheduleView(
            available=False,
            message='Submit your application first. A repayment schedule appears after credit approval.',
        )
    if not can_show_schedule(loan):
        if loan.committee_status == LoanRequest.COMMITTEE_DECLINED:
            return ScheduleView(
                available=False,
                message='This application was not approved, so there is no repayment schedule.',
            )
        return ScheduleView(
            available=False,
            message=(
                'Your repayment schedule will appear here after credit approval, '
                'once the branch prepares the amortization plan.'
            ),
            amount_approved='',
        )

    appraisal = get_appraisal_for_loan(loan)
    amount = final_loan_amount(loan, appraisal)
    term = final_term_months(loan, appraisal)
    rate = final_annual_rate_pct(loan, appraisal)

    entries = []
    if appraisal is not None:
        entries = list(appraisal.amortization_entries.order_by('period_number'))

    if not entries:
        return ScheduleView(
            available=False,
            message=(
                'Your loan was approved, but the repayment schedule is not ready yet. '
                'Your branch is preparing installment dates and amounts.'
            ),
            amount_approved=_fmt_money(amount),
            term_months=f'{term} months' if term else '—',
            annual_rate=f'{rate}%' if rate is not None else '—',
        )

    rows: List[Dict[str, Any]] = []
    sum_pay = Decimal('0')
    sum_prin = Decimal('0')
    sum_int = Decimal('0')
    for e in entries:
        pay = e.payment_amount
        prin = e.principal
        interest = e.interest
        try:
            if pay is not None:
                sum_pay += Decimal(str(pay))
            if prin is not None:
                sum_prin += Decimal(str(prin))
            if interest is not None:
                sum_int += Decimal(str(interest))
        except Exception:
            pass
        rows.append({
            'period': e.period_number,
            'date': _fmt_date(e.payment_date),
            'payment': _fmt_money(pay),
            'principal': _fmt_money(prin),
            'interest': _fmt_money(interest),
            'balance': _fmt_money(e.balance_after),
        })

    return ScheduleView(
        available=True,
        message='Official provisional schedule from branch credit prep. Confirm with your branch if anything differs at disbursement.',
        amount_approved=_fmt_money(amount),
        term_months=f'{term} months' if term else '—',
        annual_rate=f'{rate}% p.a.' if rate is not None else '—',
        rows=rows,
        total_payment=_fmt_money(sum_pay),
        total_principal=_fmt_money(sum_prin),
        total_interest=_fmt_money(sum_int),
    )
