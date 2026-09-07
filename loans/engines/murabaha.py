"""Murabaha — cost-plus + Sharia. No conventional interest schedule."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loans.engines.base import ProductEngine
from loans.product_family import FAMILY_IFB_MURABAHA


class MurabahaEngine(ProductEngine):
    family = FAMILY_IFB_MURABAHA
    uses_conventional_schedule = False

    def requires_appraisal_sheets(self) -> bool:
        return False

    def committee_blockers(self) -> List[str]:
        from loans.murabaha_overlay import murabaha_committee_blockers

        return list(super().committee_blockers()) + murabaha_committee_blockers(self.loan)

    def disbursement_blockers(self) -> List[str]:
        from loans.murabaha_overlay import murabaha_disbursement_blockers

        return list(super().disbursement_blockers()) + murabaha_disbursement_blockers(self.loan)

    def file_summary(self) -> Optional[Dict[str, Any]]:
        from loans.murabaha_overlay import murabaha_file_summary

        return murabaha_file_summary(self.loan)

    def assist_brief(self) -> Optional[Dict[str, Any]]:
        summary = self.file_summary() or {}
        contract = summary.get('contract')
        return {
            'family': self.family,
            'family_label': self.family_label,
            'is_murabaha': True,
            'cost': str(getattr(contract, 'cost_price', '') or '') if contract else '',
            'markup_pct': str(getattr(contract, 'markup_pct', '') or '') if contract else '',
            'selling_price': str(summary.get('selling_price') or ''),
            'blockers': (summary.get('committee_blockers') or [])[:8],
        }
