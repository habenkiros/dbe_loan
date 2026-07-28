"""Portfolio ledger adapter — CBS outstanding / NPL / disbursement booking."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from loans.services.cbs_client import BookDisbursementResult, OutstandingResult

logger = logging.getLogger(__name__)


class PortfolioLedgerAdapter(ABC):
    """Interface for core-banking outstanding / NPL / booking."""

    @abstractmethod
    def is_connected(self) -> bool:
        ...

    @abstractmethod
    def total_outstanding(self, user) -> Optional[Decimal]:
        """Portfolio outstanding balance in ETB for the user's loan scope, or None."""

    @abstractmethod
    def npl_ratio(self, user) -> Optional[float]:
        """NPL ratio 0..1 for scoped customers, or None."""

    @abstractmethod
    def active_borrowers(self, user) -> Optional[int]:
        ...

    def customer_outstanding(self, customer_number: str) -> Optional['OutstandingResult']:
        return None

    def book_disbursement(self, loan_request, user, *, notes: str = '') -> 'BookDisbursementResult':
        from loans.services.cbs_client import BookDisbursementResult
        return BookDisbursementResult(
            ok=False,
            status='skipped',
            message='Ledger adapter does not support booking.',
            provider='stub',
        )

    def connection_label(self) -> str:
        return self.__class__.__name__


class StubPortfolioLedgerAdapter(PortfolioLedgerAdapter):
    """No CBS — Credit Intelligence uses origination proxies."""

    def is_connected(self) -> bool:
        return False

    def total_outstanding(self, user) -> Optional[Decimal]:
        return None

    def npl_ratio(self, user) -> Optional[float]:
        return None

    def active_borrowers(self, user) -> Optional[int]:
        return None

    def connection_label(self) -> str:
        return 'stub (origination proxies only)'


class DecsiCbsLedgerAdapter(PortfolioLedgerAdapter):
    """
    DECSI / Temenos-style party outstanding + disbursement booking.

    Uses DECSI_BASE_URL when set; otherwise mock outstanding/booking so demos
    and CI stay offline-capable (DECSI_CBS_USE_MOCK_LEDGER=True by default).
    """

    def is_connected(self) -> bool:
        from loans.services.cbs_client import cbs_enabled
        return cbs_enabled()

    def connection_label(self) -> str:
        from loans.services.cbs_client import cbs_base_url, cbs_force_mock
        if cbs_base_url() and not cbs_force_mock():
            return 'DECSI CBS (live)'
        return 'DECSI CBS (mock ledger)'

    def customer_outstanding(self, customer_number: str) -> Optional['OutstandingResult']:
        from loans.services.cbs_client import fetch_customer_outstanding
        return fetch_customer_outstanding(customer_number)

    def book_disbursement(self, loan_request, user, *, notes: str = '') -> 'BookDisbursementResult':
        from loans.services.cbs_client import book_disbursement, build_disbursement_payload
        payload = build_disbursement_payload(loan_request, user, notes=notes)
        if not payload.get('customer_number'):
            from loans.services.cbs_client import BookDisbursementResult
            return BookDisbursementResult(
                ok=False,
                status='failed',
                message='Customer number required before CBS disbursement booking.',
                provider='decsi_cbs',
            )
        return book_disbursement(payload)

    def _scoped_customer_numbers(self, user) -> List[str]:
        from loans.credit_intelligence import scoped_loans

        qs, _ = scoped_loans(user)
        nums = (
            qs.exclude(customer_number__isnull=True)
            .exclude(customer_number='')
            .values_list('customer_number', flat=True)
            .distinct()
        )
        return [str(n).strip() for n in nums if str(n).strip()][:200]

    def total_outstanding(self, user) -> Optional[Decimal]:
        numbers = self._scoped_customer_numbers(user)
        if not numbers:
            return Decimal('0')
        total = Decimal('0')
        any_ok = False
        for cid in numbers:
            row = self.customer_outstanding(cid)
            if row:
                total += row.total_outstanding
                any_ok = True
        return total if any_ok else None

    def npl_ratio(self, user) -> Optional[float]:
        numbers = self._scoped_customer_numbers(user)
        if not numbers:
            return 0.0
        outstanding = Decimal('0')
        npl = Decimal('0')
        any_ok = False
        for cid in numbers:
            row = self.customer_outstanding(cid)
            if row:
                outstanding += row.total_outstanding
                npl += row.npl_amount
                any_ok = True
        if not any_ok or outstanding <= 0:
            return 0.0 if any_ok else None
        return float((npl / outstanding).quantize(Decimal('0.0001')))

    def active_borrowers(self, user) -> Optional[int]:
        numbers = self._scoped_customer_numbers(user)
        if not numbers:
            return 0
        count = 0
        for cid in numbers:
            row = self.customer_outstanding(cid)
            if row and row.active_loans > 0:
                count += 1
        return count


_ADAPTER: Optional[PortfolioLedgerAdapter] = None


def resolve_default_adapter() -> PortfolioLedgerAdapter:
    """Pick stub vs CBS adapter from settings."""
    mode = (getattr(settings, 'DECSI_LEDGER_ADAPTER', 'auto') or 'auto').strip().lower()
    if mode == 'stub':
        return StubPortfolioLedgerAdapter()
    if mode in ('cbs', 'decsi', 'temenos', 'auto'):
        from loans.services.cbs_client import cbs_enabled
        if mode != 'auto' or cbs_enabled():
            return DecsiCbsLedgerAdapter()
    return StubPortfolioLedgerAdapter()


def get_ledger_adapter() -> PortfolioLedgerAdapter:
    global _ADAPTER
    if _ADAPTER is None:
        _ADAPTER = resolve_default_adapter()
    return _ADAPTER


def set_ledger_adapter(adapter: Optional[PortfolioLedgerAdapter]) -> None:
    """Inject adapter for tests; pass None to reset to settings default."""
    global _ADAPTER
    _ADAPTER = adapter
