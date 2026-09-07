"""Product-engine hooks. Empty methods = DECSI general path."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loans.product_family import FAMILY_GENERAL, family_label, resolve_product_family


class ProductEngine:
    """One instance per loan file. Spine calls these hooks; engines never own CBS."""

    family = FAMILY_GENERAL
    uses_conventional_schedule = True

    def __init__(self, loan_request):
        self.loan = loan_request
        self.family = resolve_product_family(loan_request)

    @property
    def family_label(self) -> str:
        return family_label(self.family)

    def requires_appraisal_sheets(self) -> bool:
        """True only for MSME / corporate 7-sheet files. Product desks return False."""
        return True

    def committee_blockers(self) -> List[str]:
        from loans.fund_overlay import fund_committee_blockers
        return list(fund_committee_blockers(self.loan))

    def disbursement_blockers(self) -> List[str]:
        from loans.fund_overlay import fund_disbursement_blockers
        return list(fund_disbursement_blockers(self.loan))

    def consume_draw(self, tranche) -> None:
        return None

    def file_summary(self) -> Optional[Dict[str, Any]]:
        """Officer UI payload. None = hide product overlay panels."""
        from loans.fund_overlay import fund_file_summary
        return fund_file_summary(self.loan)

    def assist_brief(self) -> Optional[Dict[str, Any]]:
        summary = self.file_summary()
        if not summary:
            return None
        fund = summary.get('fund')
        book = summary.get('book') or {}
        return {
            'family': self.family,
            'family_label': self.family_label,
            'is_fund': True,
            'fund_code': getattr(fund, 'code', '') if fund else '',
            'remaining': str(book.get('remaining') or ''),
            'blockers': (summary.get('committee_blockers') or [])[:8],
        }
