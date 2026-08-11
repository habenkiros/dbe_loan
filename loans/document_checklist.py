"""Document checklist resolved by loan category (loan type).

Prefer category-specific packs; fall back to global document types when a
category has no requirements configured (backward compatible).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Union

from django.db.models import Prefetch


@dataclass(frozen=True)
class DocumentChecklistItem:
    document_type: object
    is_required: bool
    order: int

    @property
    def id(self):
        return self.document_type.id

    @property
    def name(self) -> str:
        return self.document_type.name

    def __getattr__(self, name):
        # Delegate auth/upload attributes to the underlying document type.
        return getattr(self.document_type, name)


def _mode_allows(document_type, appraisal_mode: str) -> bool:
    mode = (getattr(document_type, 'for_appraisal_mode', None) or '').strip()
    if not mode:
        return True
    return mode == (appraisal_mode or '').strip()


def _fallback_global_items(appraisal_mode: str = '') -> List[DocumentChecklistItem]:
    from loans.models import LoanApplicationDocumentType

    qs = LoanApplicationDocumentType.objects.order_by('order', 'name', 'id')
    items = []
    for dt in qs:
        if not _mode_allows(dt, appraisal_mode):
            continue
        items.append(DocumentChecklistItem(
            document_type=dt,
            is_required=bool(dt.is_required),
            order=int(dt.order or 0),
        ))
    return items


def checklist_for_category(
    category=None,
    *,
    appraisal_mode: str = '',
) -> List[DocumentChecklistItem]:
    """Return ordered checklist for a loan category.

    If the category has mapped document requirements, those define the pack
    (required/optional + order). Otherwise fall back to the global catalog,
    filtered by appraisal mode when available.
    """
    from loans.models import LoanCategoryDocumentRequirement

    mode = appraisal_mode
    if category is not None:
        mode = mode or getattr(category, 'appraisal_mode', '') or ''

    if category is not None and getattr(category, 'pk', None):
        reqs = (
            LoanCategoryDocumentRequirement.objects
            .filter(category=category)
            .select_related('document_type')
            .order_by('order', 'document_type__order', 'document_type__name', 'id')
        )
        if reqs.exists():
            items = []
            for r in reqs:
                dt = r.document_type
                if not _mode_allows(dt, mode):
                    continue
                items.append(DocumentChecklistItem(
                    document_type=dt,
                    is_required=bool(r.is_required),
                    order=int(r.order if r.order is not None else (dt.order or 0)),
                ))
            return items

    return _fallback_global_items(mode)


def checklist_for_loan(loan_request) -> List[DocumentChecklistItem]:
    category = getattr(loan_request, 'category', None)
    mode = ''
    if category is not None:
        mode = getattr(category, 'appraisal_mode', '') or ''
    appraisal = getattr(loan_request, 'appraisal', None)
    if appraisal is not None and getattr(appraisal, 'appraisal_mode', None):
        mode = appraisal.appraisal_mode or mode
    return checklist_for_category(category, appraisal_mode=mode)


def required_items(checklist: Sequence[DocumentChecklistItem]) -> List[DocumentChecklistItem]:
    return [i for i in checklist if i.is_required]


def checklist_type_ids(checklist: Sequence[DocumentChecklistItem]) -> set:
    return {i.id for i in checklist}


def item_by_type_id(
    checklist: Sequence[DocumentChecklistItem],
    document_type_id: int,
) -> Optional[DocumentChecklistItem]:
    for item in checklist:
        if item.id == document_type_id:
            return item
    return None


def ensure_default_requirements_for_category(category) -> int:
    """Copy global document types into category pack if empty. Returns created count."""
    from loans.models import LoanApplicationDocumentType, LoanCategoryDocumentRequirement

    if LoanCategoryDocumentRequirement.objects.filter(category=category).exists():
        return 0
    mode = getattr(category, 'appraisal_mode', '') or ''
    created = 0
    for dt in LoanApplicationDocumentType.objects.order_by('order', 'id'):
        if not _mode_allows(dt, mode):
            continue
        _, was_created = LoanCategoryDocumentRequirement.objects.get_or_create(
            category=category,
            document_type=dt,
            defaults={
                'is_required': bool(dt.is_required),
                'order': int(dt.order or 0),
            },
        )
        if was_created:
            created += 1
    return created
