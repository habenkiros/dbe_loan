"""Idea / quasi-equity. Cap table after approval — no installment."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loans.engines.base import ProductEngine
from loans.product_family import FAMILY_IDEA_EQUITY


class IdeaEngine(ProductEngine):
    family = FAMILY_IDEA_EQUITY
    uses_conventional_schedule = False

    def requires_appraisal_sheets(self) -> bool:
        return False

    def committee_blockers(self) -> List[str]:
        from loans.idea_overlay import idea_committee_blockers

        return list(super().committee_blockers()) + idea_committee_blockers(self.loan)

    def disbursement_blockers(self) -> List[str]:
        from loans.idea_overlay import idea_disbursement_blockers

        return list(super().disbursement_blockers()) + idea_disbursement_blockers(self.loan)

    def file_summary(self) -> Optional[Dict[str, Any]]:
        from loans.idea_overlay import idea_file_summary

        return idea_file_summary(self.loan)

    def assist_brief(self) -> Optional[Dict[str, Any]]:
        summary = self.file_summary() or {}
        profile = summary.get('profile')
        totals = summary.get('cap_totals') or {}
        return {
            'family': self.family,
            'family_label': self.family_label,
            'is_idea': True,
            'venture': getattr(profile, 'venture_name', '') if profile else '',
            'dbe_share': str(getattr(profile, 'proposed_dbe_share_pct', '') or '') if profile else '',
            'cap_dbe': str(totals.get('dbe') or ''),
            'blockers': (summary.get('committee_blockers') or [])[:8],
        }
