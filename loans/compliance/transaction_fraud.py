"""Rule-based transaction anomaly scoring for fraud / AML monitoring."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = 'tx_fraud_v1'


def _d(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal('0')


def score_transaction_anomalies(
    transactions: List[Dict[str, Any]],
    *,
    metrics: Optional[Dict[str, Any]] = None,
    proposed_installment: Optional[Decimal] = None,
) -> Dict[str, Any]:
    """
    Score banking activity 0–100 from transaction rows + aggregated metrics.
    Returns {score, risk_band, signals, schema}.
    """
    metrics = metrics or {}
    signals: List[Dict[str, Any]] = []
    score = 0

    def add(code: str, label: str, weight: int, detail: str = '') -> None:
        nonlocal score
        if weight <= 0:
            return
        score += weight
        signals.append({
            'code': code,
            'label': label,
            'weight': weight,
            'detail': detail,
        })

    nsf = int(metrics.get('nsf_count') or 0)
    if nsf >= 5:
        add('nsf_high', 'High NSF / returned items', 30, f'{nsf} NSF events in window')
    elif nsf >= 2:
        add('nsf_elevated', 'Elevated NSF count', 18, f'{nsf} NSF events')

    neg_days = int(metrics.get('negative_balance_days') or 0)
    if neg_days >= 10:
        add('neg_balance', 'Frequent negative balances', 25, f'{neg_days} days below zero')
    elif neg_days >= 3:
        add('neg_balance_moderate', 'Some negative balance days', 12, f'{neg_days} days')

    inflow_cv = metrics.get('inflow_cv')
    if inflow_cv is not None:
        cv = float(inflow_cv)
        if cv >= 1.2:
            add('inflow_volatile', 'Highly volatile inflows', 20, f'inflow CV {cv:.2f}')
        elif cv >= 0.75:
            add('inflow_lumpy', 'Lumpy / irregular inflows', 10, f'inflow CV {cv:.2f}')

    tx_count = int(metrics.get('tx_count') or len(transactions) or 0)
    if tx_count < 3:
        add('thin_banking', 'Thin banking history', 12, f'only {tx_count} transactions')
    elif tx_count > 120:
        add('high_velocity', 'Very high transaction velocity', 8, f'{tx_count} transactions in window')

    turnover = metrics.get('turnover_vs_installment')
    inst = _d(proposed_installment)
    if inst > 0 and turnover is not None:
        t = float(turnover)
        if t < 0.4:
            add(
                'turnover_low',
                'Inflows weak vs proposed installment',
                22,
                f'monthly credit / installment ratio {t:.2f}',
            )
        elif t < 0.75:
            add(
                'turnover_moderate',
                'Inflows only moderate vs installment',
                10,
                f'ratio {t:.2f}',
            )

    # Row-level patterns
    round_credits = 0
    large_credits = 0
    for row in transactions or []:
        amt = _d(row.get('amount'))
        if amt >= 0 and amt >= Decimal('50000') and amt % Decimal('1000') == 0:
            round_credits += 1
        if amt >= Decimal('100000'):
            large_credits += 1
    if round_credits >= 3:
        add('round_credits', 'Repeated round-number credits', 15, f'{round_credits} large round credits')
    if large_credits >= 2:
        add('large_credits', 'Multiple very large credits', 12, f'{large_credits} credits ≥ 100k')

    score = min(100, score)
    if score >= 75:
        band = 'critical'
    elif score >= 55:
        band = 'high'
    elif score >= 35:
        band = 'medium'
    else:
        band = 'low'

    return {
        'schema': SCHEMA,
        'score': score,
        'risk_band': band,
        'signals': signals,
        'tx_count': tx_count,
    }
