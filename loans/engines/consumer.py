"""Consumer housing / vehicle. HRM scorecard, not MSME sheets."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loans.engines.base import ProductEngine
from loans.product_family import FAMILY_CONSUMER


class ConsumerEngine(ProductEngine):
    family = FAMILY_CONSUMER
    uses_conventional_schedule = True

    def requires_appraisal_sheets(self) -> bool:
        return False

    def committee_blockers(self) -> List[str]:
        from loans.consumer_overlay import consumer_committee_blockers

        return list(super().committee_blockers()) + consumer_committee_blockers(self.loan)

    def disbursement_blockers(self) -> List[str]:
        from loans.consumer_overlay import consumer_disbursement_blockers

        return list(super().disbursement_blockers()) + consumer_disbursement_blockers(self.loan)

    def file_summary(self) -> Optional[Dict[str, Any]]:
        from loans.consumer_overlay import consumer_file_summary

        return consumer_file_summary(self.loan)

    def assist_brief(self) -> Optional[Dict[str, Any]]:
        summary = self.file_summary() or {}
        profile = summary.get('profile')
        scorecard = summary.get('scorecard') or {}
        return {
            'family': self.family,
            'family_label': self.family_label,
            'is_consumer': True,
            'employer': getattr(profile, 'employer_name', '') if profile else '',
            'dti_pct': str(summary.get('dti_pct') or ''),
            'ltv_pct': str(summary.get('ltv_pct') or ''),
            'score': str(scorecard.get('total') or ''),
            'band': scorecard.get('band_label') or '',
            'installment': str(scorecard.get('installment') or ''),
            'blockers': (summary.get('committee_blockers') or [])[:8],
        }
