"""Ijarah — same asset register as hire-purchase; rent + Sharia, no interest Sheet 7."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loans.engines.base import ProductEngine
from loans.product_family import FAMILY_IFB_IJARAH


class IjarahEngine(ProductEngine):
    family = FAMILY_IFB_IJARAH
    uses_conventional_schedule = False

    def requires_appraisal_sheets(self) -> bool:
        return False

    def committee_blockers(self) -> List[str]:
        from loans.lease_overlay import lease_committee_blockers

        return list(super().committee_blockers()) + lease_committee_blockers(self.loan)

    def disbursement_blockers(self) -> List[str]:
        from loans.lease_overlay import lease_disbursement_blockers

        return list(super().disbursement_blockers()) + lease_disbursement_blockers(self.loan)

    def file_summary(self) -> Optional[Dict[str, Any]]:
        from loans.lease_overlay import lease_file_summary

        return lease_file_summary(self.loan)

    def assist_brief(self) -> Optional[Dict[str, Any]]:
        summary = self.file_summary() or {}
        profile = summary.get('profile')
        sharia = summary.get('latest_sharia')
        return {
            'family': self.family,
            'family_label': self.family_label,
            'is_lease': True,
            'is_ijarah': True,
            'supplier': getattr(profile, 'supplier_name', '') if profile else '',
            'monthly_rent': str(getattr(profile, 'monthly_rent', '') or '') if profile else '',
            'sharia': getattr(sharia, 'status', '') if sharia else '',
            'blockers': (summary.get('disbursement_blockers') or [])[:8],
        }
