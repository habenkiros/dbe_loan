"""
Core-banking account transaction history → appraisal banking metrics.

Live path: DECSI_BASE_URL + /…/transactions (configurable).
Dev path: deterministic mock when URL unset (same pattern as customer lookup).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional, Tuple

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

BANKING_METRICS_VERSION = 'banking_metrics_v1'
DEFAULT_WINDOW_MONTHS = 6


def _d(v) -> Decimal:
    try:
        return Decimal(str(v or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')


def _month_key(d: date) -> str:
    return f'{d.year:04d}-{d.month:02d}'


def mock_fetch_account_transactions(
    customer_number: str,
    *,
    months: int = DEFAULT_WINDOW_MONTHS,
) -> List[Dict[str, Any]]:
    """
    Deterministic mock ledger for local/dev.
    Stronger patterns for higher customer-number hashes; DEMO/1001 are healthy.
    """
    cid = (customer_number or '').strip() or 'DEMO'
    seed = int(hashlib.sha256(cid.encode()).hexdigest()[:8], 16)
    today = timezone.now().date()
    rows: List[Dict[str, Any]] = []
    # Health tier 0–3 from seed
    tier = seed % 4
    base_credit = Decimal('180000') + Decimal(tier * 40000)
    for m in range(months):
        # Month end going backwards
        first = (today.replace(day=1) - timedelta(days=30 * m))
        month_end = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        # 4–8 credits / debits
        n = 4 + (seed + m) % 5
        for i in range(n):
            day = min(28, 3 + i * 3)
            tx_date = month_end.replace(day=min(day, month_end.day))
            is_credit = (i % 3) != 2
            amount = (base_credit / Decimal(n) * (Decimal('0.7') + Decimal((seed + i) % 5) / Decimal('10'))).quantize(
                Decimal('0.01')
            )
            if not is_credit:
                amount = (amount * Decimal('0.85')).quantize(Decimal('0.01'))
            # Inject stress for weak tiers
            nsf = False
            if tier == 0 and m == 1 and i == 0:
                nsf = True
            if tier <= 1 and m == 0 and i == 1 and not is_credit:
                amount = (amount * Decimal('1.4')).quantize(Decimal('0.01'))
            rows.append({
                'date': tx_date.isoformat(),
                'amount': float(amount if is_credit else -amount),
                'type': 'credit' if is_credit else 'debit',
                'description': 'Mock salary/trade credit' if is_credit else 'Mock supplier/expense',
                'nsf': nsf,
                'balance_after': None,
            })
    rows.sort(key=lambda r: r['date'])
    # Running balance
    bal = Decimal('50000') + Decimal(tier * 25000)
    for r in rows:
        bal += _d(r['amount'])
        if tier == 0 and r['date'].endswith('-05'):
            bal = Decimal('-1500')
        r['balance_after'] = float(bal.quantize(Decimal('0.01')))
        r['nsf'] = bool(r.get('nsf'))
    return rows


def live_fetch_account_transactions(
    customer_number: str,
    *,
    months: int = DEFAULT_WINDOW_MONTHS,
) -> Optional[List[Dict[str, Any]]]:
    """
    Fetch recent account movements from core banking.
    Expected JSON list or {transactions: [...]} with date, amount, type/nsf.
    """
    base = (getattr(settings, 'DECSI_BASE_URL', None) or '').rstrip('/')
    if not base:
        return None
    cid = (customer_number or '').strip()
    if not cid:
        return None
    path = getattr(
        settings,
        'DECSI_TRANSACTIONS_PATH',
        '/getCusByCusNo/api/v1.0.0/party/custid/{cid}/transactions',
    )
    url = f'{base}{path.format(cid=cid)}'
    timeout = getattr(settings, 'DECSI_CUSTOMER_TIMEOUT', 8)
    try:
        response = requests.get(url, params={'months': months}, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning('Banking transactions lookup failed for %s: %s', cid, exc)
        return None
    if response.status_code != 200:
        logger.info('Banking transactions HTTP %s for %s', response.status_code, cid)
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, list):
        raw_rows = payload
    elif isinstance(payload, dict):
        raw_rows = payload.get('transactions') or payload.get('data') or []
    else:
        raw_rows = []
    rows = []
    for item in raw_rows:
        if not isinstance(item, dict):
            continue
        amount = item.get('amount')
        tx_type = (item.get('type') or item.get('txnType') or '').lower()
        if amount is None:
            continue
        amt = _d(amount)
        if tx_type in ('debit', 'dr', 'withdrawal') and amt > 0:
            amt = -amt
        elif tx_type in ('credit', 'cr', 'deposit') and amt < 0:
            amt = abs(amt)
        rows.append({
            'date': str(item.get('date') or item.get('txnDate') or '')[:10],
            'amount': float(amt),
            'type': 'credit' if amt >= 0 else 'debit',
            'description': str(item.get('description') or item.get('narration') or '')[:255],
            'nsf': bool(item.get('nsf') or item.get('returned') or item.get('bounce')),
            'balance_after': float(item['balance_after']) if item.get('balance_after') is not None else None,
        })
    return rows


def fetch_account_transactions(
    customer_number: str,
    *,
    months: int = DEFAULT_WINDOW_MONTHS,
) -> Tuple[List[Dict[str, Any]], str]:
    """Return (rows, provider) where provider is live|mock|empty."""
    base = (getattr(settings, 'DECSI_BASE_URL', None) or '').strip()
    force_mock = getattr(settings, 'DECSI_CUSTOMER_FORCE_MOCK', False)
    if base and not force_mock:
        live = live_fetch_account_transactions(customer_number, months=months)
        if live is not None:
            return live, 'live'
        if not getattr(settings, 'DECSI_CUSTOMER_FALLBACK_MOCK', True):
            return [], 'empty'
        if not (customer_number or '').strip():
            return [], 'empty'
        return mock_fetch_account_transactions(customer_number, months=months), 'mock_fallback'
    if not (customer_number or '').strip():
        return [], 'empty'
    return mock_fetch_account_transactions(customer_number, months=months), 'mock'


def compute_banking_metrics(
    transactions: List[Dict[str, Any]],
    *,
    proposed_installment: Optional[Decimal] = None,
    window_months: int = DEFAULT_WINDOW_MONTHS,
) -> Dict[str, Any]:
    """Aggregate transaction rows into scorecard-ready metrics."""
    if not transactions:
        return {
            'schema': BANKING_METRICS_VERSION,
            'window_months': window_months,
            'tx_count': 0,
            'avg_monthly_credit': None,
            'avg_monthly_debit': None,
            'inflow_cv': None,
            'nsf_count': 0,
            'negative_balance_days': 0,
            'credit_months': 0,
            'turnover_vs_installment': None,
            'ending_balance': None,
        }

    by_month_credit: Dict[str, Decimal] = {}
    by_month_debit: Dict[str, Decimal] = {}
    nsf_count = 0
    neg_days = 0
    ending = None
    for row in transactions:
        try:
            d = date.fromisoformat(str(row.get('date'))[:10])
        except ValueError:
            continue
        mk = _month_key(d)
        amt = _d(row.get('amount'))
        if amt >= 0:
            by_month_credit[mk] = by_month_credit.get(mk, Decimal('0')) + amt
        else:
            by_month_debit[mk] = by_month_debit.get(mk, Decimal('0')) + abs(amt)
        if row.get('nsf'):
            nsf_count += 1
        bal = row.get('balance_after')
        if bal is not None:
            ending = _d(bal)
            if ending < 0:
                neg_days += 1

    credit_vals = [float(v) for v in by_month_credit.values()] or [0.0]
    debit_vals = [float(v) for v in by_month_debit.values()] or [0.0]
    avg_credit = Decimal(str(mean(credit_vals))).quantize(Decimal('0.01'))
    avg_debit = Decimal(str(mean(debit_vals))).quantize(Decimal('0.01'))
    if len(credit_vals) >= 2 and mean(credit_vals) > 0:
        cv = pstdev(credit_vals) / mean(credit_vals)
        inflow_cv = Decimal(str(round(cv, 4)))
    else:
        inflow_cv = Decimal('0') if credit_vals and credit_vals[0] > 0 else None

    material = Decimal('1000')
    credit_months = sum(1 for v in by_month_credit.values() if v >= material)

    turnover_ratio = None
    inst = _d(proposed_installment) if proposed_installment is not None else Decimal('0')
    if inst > 0 and avg_credit is not None:
        turnover_ratio = (avg_credit / inst).quantize(Decimal('0.01'))

    return {
        'schema': BANKING_METRICS_VERSION,
        'window_months': window_months,
        'tx_count': len(transactions),
        'avg_monthly_credit': float(avg_credit),
        'avg_monthly_debit': float(avg_debit),
        'inflow_cv': float(inflow_cv) if inflow_cv is not None else None,
        'nsf_count': nsf_count,
        'negative_balance_days': neg_days,
        'credit_months': credit_months,
        'months_observed': len(set(list(by_month_credit) + list(by_month_debit))),
        'turnover_vs_installment': float(turnover_ratio) if turnover_ratio is not None else None,
        'ending_balance': float(ending) if ending is not None else None,
    }


def refresh_appraisal_banking(appraisal, loan_request=None, *, months: int = DEFAULT_WINDOW_MONTHS) -> Dict[str, Any]:
    """
    Pull transactions for the loan's customer number, compute metrics, persist on appraisal.
    """
    loan = loan_request or appraisal.loan_request
    cid = (getattr(loan, 'customer_number', None) or '').strip()
    rows, provider = fetch_account_transactions(cid, months=months)
    installment = getattr(appraisal, 'proposed_monthly_installment', None)
    metrics = compute_banking_metrics(rows, proposed_installment=installment, window_months=months)
    payload = {
        **metrics,
        'provider': provider,
        'customer_number': cid or None,
        'refreshed_at': timezone.now().isoformat(),
        'sample_tx_count': len(rows),
    }
    appraisal.banking_behavior = payload
    appraisal.banking_refreshed_at = timezone.now()
    appraisal.save(update_fields=['banking_behavior', 'banking_refreshed_at', 'updated_at'])
    return payload
