"""Helpers for Sheet 3 cashflow / repayment capacity (Phase 2)."""
from decimal import Decimal


def payments_per_year_from_repayment_frequency(frequency):
    """
    Map Sheet 1 repayment frequency to number of payments per year.
    Returns 12 if unknown or empty.
    """
    if not frequency:
        return 12
    f = str(frequency).strip().lower()
    if 'bi-week' in f or 'biweek' in f:
        return 26
    if 'quarter' in f:
        return 4
    if 'semi' in f and 'annual' in f:
        return 2
    if f == 'annual' or (f.startswith('annual') and 'semi' not in f):
        return 1
    if 'month' in f:
        return 12
    return 12


def annual_debt_service(proposed_installment_per_period, payments_per_year):
    """Annual total debt service from installment per period × payments per year."""
    if not proposed_installment_per_period or proposed_installment_per_period <= 0:
        return None
    if not payments_per_year or payments_per_year <= 0:
        payments_per_year = 12
    try:
        return (Decimal(str(proposed_installment_per_period)) * Decimal(payments_per_year)).quantize(Decimal('0.01'))
    except Exception:
        return None
