"""Registry: family on the loan → product engine.

Consumer uses the HRM scorecard desk. Fund covenants still apply on the
base engine when a window is tagged.
"""

from __future__ import annotations

from loans.engines.base import ProductEngine
from loans.engines.consumer import ConsumerEngine
from loans.engines.fund import FundEngine
from loans.engines.general import GeneralEngine
from loans.engines.idea import IdeaEngine
from loans.engines.ijarah import IjarahEngine
from loans.engines.lease import LeaseEngine
from loans.engines.murabaha import MurabahaEngine
from loans.engines.project import ProjectEngine
from loans.engines.wholesale import WholesaleEngine
from loans.product_family import (
    FAMILY_CONSUMER,
    FAMILY_EXTERNAL_FUND,
    FAMILY_IDEA_EQUITY,
    FAMILY_IFB_IJARAH,
    FAMILY_IFB_MURABAHA,
    FAMILY_LEASE,
    FAMILY_PROJECT,
    FAMILY_WHOLESALE,
    resolve_product_family,
)

_ENGINE_BY_FAMILY = {
    FAMILY_PROJECT: ProjectEngine,
    FAMILY_WHOLESALE: WholesaleEngine,
    FAMILY_EXTERNAL_FUND: FundEngine,
    FAMILY_LEASE: LeaseEngine,
    FAMILY_IFB_IJARAH: IjarahEngine,
    FAMILY_IFB_MURABAHA: MurabahaEngine,
    FAMILY_IDEA_EQUITY: IdeaEngine,
    FAMILY_CONSUMER: ConsumerEngine,
}


def get_engine(loan_request) -> ProductEngine:
    family = resolve_product_family(loan_request)
    cls = _ENGINE_BY_FAMILY.get(family, GeneralEngine)
    return cls(loan_request)


__all__ = [
    'ProductEngine', 'GeneralEngine', 'ProjectEngine',
    'WholesaleEngine', 'FundEngine', 'LeaseEngine', 'IjarahEngine',
    'MurabahaEngine', 'IdeaEngine', 'ConsumerEngine', 'get_engine',
]
