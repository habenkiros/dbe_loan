"""Stub adapter for future core-banking outstanding / NPL feeds."""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional


class PortfolioLedgerAdapter(ABC):
    """Interface for true outstanding / NPL when DECSI CBS APIs exist."""

    @abstractmethod
    def is_connected(self) -> bool:
        ...

    @abstractmethod
    def total_outstanding(self, user) -> Optional[Decimal]:
        """Portfolio outstanding balance in ETB, or None if unavailable."""

    @abstractmethod
    def npl_ratio(self, user) -> Optional[float]:
        """NPL ratio 0..1, or None if unavailable."""

    @abstractmethod
    def active_borrowers(self, user) -> Optional[int]:
        ...


class StubPortfolioLedgerAdapter(PortfolioLedgerAdapter):
    """Default: no CBS — Credit Intelligence uses origination proxies instead."""

    def is_connected(self) -> bool:
        return False

    def total_outstanding(self, user) -> Optional[Decimal]:
        return None

    def npl_ratio(self, user) -> Optional[float]:
        return None

    def active_borrowers(self, user) -> Optional[int]:
        return None


_ADAPTER: Optional[PortfolioLedgerAdapter] = None


def get_ledger_adapter() -> PortfolioLedgerAdapter:
    global _ADAPTER
    if _ADAPTER is None:
        _ADAPTER = StubPortfolioLedgerAdapter()
    return _ADAPTER


def set_ledger_adapter(adapter: PortfolioLedgerAdapter) -> None:
    """Tests / future CBS wiring can inject a real adapter."""
    global _ADAPTER
    _ADAPTER = adapter
