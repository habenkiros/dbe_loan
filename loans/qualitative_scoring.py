"""Sheet 2 qualitative scoring: Excel option lists → weight / earned / pass."""

from __future__ import annotations

from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from .appraisal_vision import QUALITATIVE_PASS_THRESHOLD
from .models import QUALITATIVE_RATING_CHOICES_BY_FACTOR, AppraisalQualitativeFactor


DEFAULT_FACTOR_WEIGHT = Decimal('10')  # 10 factors × 10 = 100

# Excel dropdown order is chronological (worst → best) for these factors.
RATING_ORDER_WORST_FIRST = frozenset({'years_operation'})


def _norm_rating(value: Optional[str]) -> str:
    return (value or '').strip()


def _option_index(factor_key: str, rating: str, opts: List[str]) -> Optional[int]:
    """Resolve rating to option index; tolerate trailing-space / case drift from Excel."""
    needle = _norm_rating(rating)
    if not needle:
        return None
    for i, opt in enumerate(opts):
        if _norm_rating(opt) == needle:
            return i
    # Legacy Poor/basic/Professional
    legacy = {'Professional': 0, 'basic': 1, 'Poor': 2}
    if rating in legacy and len(opts) >= 3:
        return min(legacy[rating], len(opts) - 1)
    lower = needle.lower()
    for i, opt in enumerate(opts):
        if _norm_rating(opt).lower() == lower:
            return i
    return None


def rating_tier_score(factor_key: str, rating: Optional[str]) -> Optional[Decimal]:
    """
    Map selected rating string to 0–1 fraction of max weight.
    Default Excel option order is best → worst; years_operation is worst → best.
    """
    if not rating:
        return None
    opts = list(QUALITATIVE_RATING_CHOICES_BY_FACTOR.get(factor_key) or [])
    if not opts:
        return None
    idx = _option_index(factor_key, rating, opts)
    if idx is None:
        return None
    n = len(opts)
    if n == 1:
        return Decimal('1')
    # Convert to "best=0 … worst=n-1" rank
    if factor_key in RATING_ORDER_WORST_FIRST:
        rank = n - 1 - idx  # last option is best
    else:
        rank = idx
    # Best (0) → 1.0, worst (n-1) → 0.25 floor so a filled factor still contributes
    frac = Decimal(n - 1 - rank) / Decimal(n - 1)
    if rank >= n - 1:
        return Decimal('0.25') if n > 2 else frac
    return max(frac, Decimal('0.25'))


def best_rating_for_factor(factor_key: str) -> Optional[str]:
    """Highest-scoring option for demos / tests."""
    opts = QUALITATIVE_RATING_CHOICES_BY_FACTOR.get(factor_key) or []
    if not opts:
        return None
    if factor_key in RATING_ORDER_WORST_FIRST:
        return opts[-1]
    return opts[0]


def earned_for_rating(factor_key: str, rating: Optional[str], weight: Optional[Decimal] = None) -> Optional[Decimal]:
    w = weight if weight is not None else DEFAULT_FACTOR_WEIGHT
    frac = rating_tier_score(factor_key, rating)
    if frac is None:
        return None
    return (w * frac).quantize(Decimal('0.01'))


def qualitative_score_map_for_js(weight: Optional[Decimal] = None) -> Dict[str, Dict[str, float]]:
    """factor_key → {rating_label: earned_score} for live Sheet 2 UI."""
    w = weight if weight is not None else DEFAULT_FACTOR_WEIGHT
    out: Dict[str, Dict[str, float]] = {}
    for key, opts in QUALITATIVE_RATING_CHOICES_BY_FACTOR.items():
        out[key] = {}
        for opt in opts:
            earned = earned_for_rating(key, opt, w)
            if earned is not None:
                out[key][opt] = float(earned)
                # Also key stripped form so JS matches pasted values
                stripped = _norm_rating(opt)
                if stripped != opt:
                    out[key][stripped] = float(earned)
    return out


def score_factor(factor: AppraisalQualitativeFactor) -> Tuple[Decimal, Optional[Decimal]]:
    """Return (weight, earned_score)."""
    weight = factor.weight if factor.weight is not None else DEFAULT_FACTOR_WEIGHT
    earned = earned_for_rating(factor.factor_key, factor.rating, weight)
    return weight, earned


def apply_qualitative_scores(factors: Iterable[AppraisalQualitativeFactor]) -> Decimal:
    """
    Persist weight/earned on each factor; return total earned (0–100 scale).
    """
    total = Decimal('0')
    for factor in factors:
        weight, earned = score_factor(factor)
        factor.weight = weight
        factor.earned_score = earned
        factor.save(update_fields=['weight', 'earned_score'])
        if earned is not None:
            total += earned
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
