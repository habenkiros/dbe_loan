"""Conventional hire-purchase. Asset register lives in lease_overlay."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loans.engines.base import ProductEngine
from loans.product_family import FAMILY_LEASE


class LeaseEngine(ProductEngine):
    family = FAMILY_LEASE
    uses_conventional_schedule = True

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
        return {
            'family': self.family,
            'family_label': self.family_label,
            'is_lease': True,
            'is_ijarah': False,
            'supplier': getattr(profile, 'supplier_name', '') if profile else '',
            'serial': getattr(profile, 'serial_number', '') if profile else '',
            'asset_price': str(getattr(profile, 'asset_price', '') or '') if profile else '',
            'blockers': (summary.get('committee_blockers') or [])[:8],
        }
