"""External-fund window engine. Covenants live in fund_overlay (any family)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loans.engines.base import ProductEngine
from loans.product_family import FAMILY_EXTERNAL_FUND


class FundEngine(ProductEngine):
    family = FAMILY_EXTERNAL_FUND

    def committee_blockers(self) -> List[str]:
        blockers = list(super().committee_blockers())
        if not getattr(self.loan, 'financing_fund_id', None):
            blockers.insert(0, 'Assign a funding window — this file is an external-fund window.')
        return blockers

    def file_summary(self) -> Optional[Dict[str, Any]]:
        from loans.fund_overlay import fund_file_summary

        summary = fund_file_summary(self.loan)
        if summary:
            return summary
        return {
            'is_fund': True,
            'is_project': False,
            'is_wholesale': False,
            'fund': None,
            'tag': None,
            'book': None,
            'committee_blockers': self.committee_blockers(),
            'disbursement_blockers': self.disbursement_blockers(),
        }

    def assist_brief(self) -> Optional[Dict[str, Any]]:
        summary = self.file_summary() or {}
        fund = summary.get('fund')
        book = summary.get('book') or {}
        return {
            'family': self.family,
            'family_label': self.family_label,
            'is_fund': True,
            'fund_code': getattr(fund, 'code', '') if fund else '',
            'envelope': str(book.get('envelope') or ''),
            'committed': str(book.get('committed') or ''),
            'remaining': str(book.get('remaining') or ''),
            'blockers': (summary.get('committee_blockers') or [])[:8],
        }
