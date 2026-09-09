"""Project-finance engine. Logic stays in project_overlay until Phase B grows it."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loans.engines.base import ProductEngine
from loans.product_family import FAMILY_PROJECT


class ProjectEngine(ProductEngine):
    family = FAMILY_PROJECT

    def requires_appraisal_sheets(self) -> bool:
        return False

    def committee_blockers(self) -> List[str]:
        from loans.project_overlay import project_committee_blockers
        return list(super().committee_blockers()) + project_committee_blockers(self.loan)

    def disbursement_blockers(self) -> List[str]:
        from loans.project_overlay import project_disbursement_blockers
        return list(super().disbursement_blockers()) + project_disbursement_blockers(self.loan)

    def consume_draw(self, tranche) -> None:
        from loans.project_overlay import consume_unlocking_visit
        consume_unlocking_visit(self.loan, tranche)

    def file_summary(self) -> Optional[Dict[str, Any]]:
        from loans.project_overlay import project_file_summary
        return project_file_summary(self.loan)

    def assist_brief(self) -> Optional[Dict[str, Any]]:
        summary = self.file_summary()
        if not summary:
            return None
        profile = summary.get('profile')
        totals = summary.get('totals') or {}
        return {
            'family': self.family,
            'family_label': self.family_label,
            'is_project': True,
            'title': getattr(profile, 'project_title', '') if profile else '',
            'sources': str(totals.get('sources') or 0),
            'uses': str(totals.get('uses') or 0),
            'balanced': bool(totals.get('balanced')),
            'blockers': (summary.get('committee_blockers') or [])[:8],
            'npv': str((summary.get('metrics') or {}).get('npv') or ''),
            'irr_pct': str((summary.get('metrics') or {}).get('irr_pct') or ''),
            'equity_irr_pct': str((summary.get('metrics') or {}).get('equity_irr_pct') or ''),
            'payback_years': str((summary.get('metrics') or {}).get('payback_years') or ''),
            'break_even_capacity_pct': str(
                (summary.get('metrics') or {}).get('break_even_capacity_pct') or ''
            ),
        }
