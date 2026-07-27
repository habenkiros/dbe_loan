"""Helpers for Sheet 3 cashflow / repayment capacity (Phase 2+)."""
from decimal import Decimal, InvalidOperation


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


def suggested_installment_declining(principal, annual_rate_pct, term_months, payments_per_year=12):
    """
    Approximate level payment per period (annuity). Rate from Sheet 1 annual %.
    Does not use the excluded 2016 rate workbook.
    """
    if not principal or principal <= 0 or not term_months or term_months <= 0:
        return None
    try:
        p = Decimal(str(principal))
        n = int(term_months)
        ppy = int(payments_per_year or 12)
        periods = max(1, int(round(n * ppy / 12)))
        rate = Decimal(str(annual_rate_pct or 0)) / Decimal('100')
        if rate <= 0:
            return (p / Decimal(periods)).quantize(Decimal('0.01'))
        r = rate / Decimal(ppy)
        one_plus = (Decimal('1') + r)
        factor = one_plus ** periods
        payment = (r * p * factor) / (factor - Decimal('1'))
        return payment.quantize(Decimal('0.01'))
    except (InvalidOperation, ZeroDivisionError, ValueError):
        return None


def max_loan_capacity_from_cashflow(
    annual_net_cashflow,
    annual_rate_pct,
    term_months,
    target_dscr=Decimal('1.2'),
    payments_per_year=12,
):
    """Max principal such that annual debt service ≤ annual_net / target_dscr."""
    if not annual_net_cashflow or annual_net_cashflow <= 0:
        return None
    if not term_months or term_months <= 0:
        return None
    try:
        target = Decimal(str(target_dscr or '1.2'))
        if target <= 0:
            target = Decimal('1.2')
        max_annual_ds = (Decimal(str(annual_net_cashflow)) / target).quantize(Decimal('0.01'))
        ppy = int(payments_per_year or 12)
        max_period_payment = (max_annual_ds / Decimal(ppy)).quantize(Decimal('0.01'))
        n = int(term_months)
        periods = max(1, int(round(n * ppy / 12)))
        rate = Decimal(str(annual_rate_pct or 0)) / Decimal('100')
        if rate <= 0:
            return (max_period_payment * Decimal(periods)).quantize(Decimal('0.01'))
        r = rate / Decimal(ppy)
        one_plus = Decimal('1') + r
        factor = one_plus ** periods
        principal = max_period_payment * (factor - Decimal('1')) / (r * factor)
        return principal.quantize(Decimal('0.01'))
    except (InvalidOperation, ZeroDivisionError, ValueError):
        return None


def compute_balance_sheet_ratios(
    current_assets=None,
    current_liabilities=None,
    inventory=None,
    total_liabilities=None,
    equity=None,
):
    """Return current ratio, acid test, and debt/equity when inputs allow."""
    ratios = {'ratio_current': None, 'ratio_acid_test': None, 'ratio_debt_equity': None}
    try:
        ca = Decimal(str(current_assets)) if current_assets is not None else None
        cl = Decimal(str(current_liabilities)) if current_liabilities is not None else None
        inv = Decimal(str(inventory or 0))
        tl = Decimal(str(total_liabilities)) if total_liabilities is not None else None
        eq = Decimal(str(equity)) if equity is not None else None
        if ca is not None and cl is not None and cl > 0:
            ratios['ratio_current'] = (ca / cl).quantize(Decimal('0.01'))
            ratios['ratio_acid_test'] = ((ca - inv) / cl).quantize(Decimal('0.01'))
        if tl is not None and eq is not None and eq > 0:
            ratios['ratio_debt_equity'] = (tl / eq).quantize(Decimal('0.01'))
    except (InvalidOperation, ZeroDivisionError, ValueError, TypeError):
        pass
    return ratios


def parse_monthly_cashflow_grid_from_post(post_data):
    """Build a 12-row grid from POST keys grid_sales_1..12, grid_expenses_1..12."""
    rows = []
    for month in range(1, 13):
        sales_raw = (post_data.get(f'grid_sales_{month}') or '').strip()
        exp_raw = (post_data.get(f'grid_expenses_{month}') or '').strip()
        sales = None
        expenses = None
        try:
            if sales_raw:
                sales = Decimal(sales_raw)
            if exp_raw:
                expenses = Decimal(exp_raw)
        except (InvalidOperation, ValueError):
            sales = None
            expenses = None
        net = None
        if sales is not None or expenses is not None:
            net = (Decimal(sales or 0) - Decimal(expenses or 0)).quantize(Decimal('0.01'))
        rows.append({
            'month': month,
            'sales': str(sales) if sales is not None else None,
            'expenses': str(expenses) if expenses is not None else None,
            'net': str(net) if net is not None else None,
        })
    return rows


def seed_monthly_grid_from_averages(monthly_sales=None, monthly_expenses=None):
    """Pre-fill 12 equal months from average monthly sales/expenses."""
    rows = []
    for month in range(1, 13):
        sales = Decimal(str(monthly_sales)) if monthly_sales is not None else None
        expenses = Decimal(str(monthly_expenses)) if monthly_expenses is not None else None
        net = None
        if sales is not None or expenses is not None:
            net = (Decimal(sales or 0) - Decimal(expenses or 0)).quantize(Decimal('0.01'))
        rows.append({
            'month': month,
            'sales': str(sales) if sales is not None else None,
            'expenses': str(expenses) if expenses is not None else None,
            'net': str(net) if net is not None else None,
        })
    return rows
