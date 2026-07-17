"""Sheet 2 qualitative scoring: Excel option lists → weight / earned / pass."""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable, List, Optional, Tuple

from .appraisal_vision import QUALITATIVE_PASS_THRESHOLD
from .models import QUALITATIVE_RATING_CHOICES_BY_FACTOR, AppraisalQualitativeFactor


DEFAULT_FACTOR_WEIGHT = Decimal('10')  # 10 factors × 10 = 100


def rating_tier_score(factor_key: str, rating: Optional[str]) -> Optional[Decimal]:
    """
    Map selected rating string to 0–1 fraction of max weight.
    Options are ordered best → worst (Excel order).
    """
    if not rating:
        return None
    opts = QUALITATIVE_RATING_CHOICES_BY_FACTOR.get(factor_key) or []
    if not opts:
        return None
    try:
        idx = opts.index(rating)
    except ValueError:
        # Legacy Poor/basic/Professional
        legacy = {'Professional': 0, 'basic': 1, 'Poor': 2}
        if rating in legacy and len(opts) >= 3:
            idx = min(legacy[rating], len(opts) - 1)
        else:
            return None
    n = len(opts)
    if n == 1:
        return Decimal('1')
    # Best (0) → 1.0, worst (n-1) → ~0.25 floor so a filled factor still contributes
    frac = Decimal(n - 1 - idx) / Decimal(n - 1)
    return max(frac, Decimal('0.25')) if idx < n - 1 else Decimal('0.25') if n > 2 else frac


def score_factor(factor: AppraisalQualitativeFactor) -> Tuple[Decimal, Optional[Decimal]]:
    """Return (weight, earned_score)."""
    weight = factor.weight if factor.weight is not None else DEFAULT_FACTOR_WEIGHT
    frac = rating_tier_score(factor.factor_key, factor.rating)
    if frac is None:
        return weight, None
    earned = (weight * frac).quantize(Decimal('0.01'))
    return weight, earned


def apply_qualitative_scores(factors: Iterable[AppraisalQualitativeFactor]) -> Decimal:
    """
    Persist weight/earned on each factor; return total earned (0–100 scale).
    """
    total = Decimal('0')
    counted = 0
    for factor in factors:
        weight, earned = score_factor(factor)
        factor.weight = weight
        factor.earned_score = earned
        factor.save(update_fields=['weight', 'earned_score'])
        if earned is not None:
            total += earned
            counted += 1
    return total.quantize(Decimal('0.01'))


def update_appraisal_qualitative_totals(appraisal) -> Tuple[Decimal, bool]:
    """Recompute factors + appraisal.qualitative_total_score / qualitative_passed."""
    factors = list(appraisal.qualitative_factors.all())
    total = apply_qualitative_scores(factors)
    passed = total >= Decimal(str(QUALITATIVE_PASS_THRESHOLD))
    appraisal.qualitative_total_score = total
    appraisal.qualitative_passed = passed
    appraisal.save(update_fields=['qualitative_total_score', 'qualitative_passed', 'updated_at'])
    return total, passed


def qualitative_contributions(appraisal) -> List[dict]:
    rows = []
    for f in appraisal.qualitative_factors.all().order_by('display_order', 'id'):
        rows.append({
            'feature_key': f'qual.{f.factor_key}',
            'value': f.rating or '',
            'points': float(f.earned_score) if f.earned_score is not None else None,
            'max_points': float(f.weight or DEFAULT_FACTOR_WEIGHT),
            'reason': f.factor_name or f.factor_key,
        })
    return rows
