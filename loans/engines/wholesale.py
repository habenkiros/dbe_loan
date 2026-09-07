"""Wholesale / PFI engine. Institution file + optional fund covenants."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loans.engines.base import ProductEngine
from loans.product_family import FAMILY_WHOLESALE


class WholesaleEngine(ProductEngine):
    family = FAMILY_WHOLESALE
    uses_conventional_schedule = True

    def requires_appraisal_sheets(self) -> bool:
        return False

    def committee_blockers(self) -> List[str]:
        from loans.wholesale_overlay import wholesale_committee_blockers

        return list(super().committee_blockers()) + wholesale_committee_blockers(self.loan)

    def disbursement_blockers(self) -> List[str]:
        from loans.wholesale_overlay import wholesale_disbursement_blockers

        return list(super().disbursement_blockers()) + wholesale_disbursement_blockers(self.loan)

    def file_summary(self) -> Optional[Dict[str, Any]]:
        from loans.wholesale_overlay import wholesale_file_summary

        return wholesale_file_summary(self.loan)

    def assist_brief(self) -> Optional[Dict[str, Any]]:
        summary = self.file_summary() or {}
        profile = summary.get('profile')
        fund_summary = summary.get('fund') or {}
        fund = fund_summary.get('fund') if isinstance(fund_summary, dict) else None
        return {
            'family': self.family,
            'family_label': self.family_label,
            'is_wholesale': True,
            'institution': getattr(profile, 'institution_name', '') if profile else '',
            'par90': str(getattr(profile, 'par90_pct', '') or '') if profile else '',
            'facility': str(getattr(profile, 'facility_amount', '') or '') if profile else '',
            'fund_code': getattr(fund, 'code', '') if fund else '',
            'blockers': (summary.get('committee_blockers') or [])[:8],
        }
