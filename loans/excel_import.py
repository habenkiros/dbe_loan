"""Excel/CSV import for DECSI master data and loan migration.

Column names are matched case-insensitively; spaces and hyphens become underscores.
Each importer returns an ImportResult (created / updated / skipped / row errors).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Sequence

import pandas as pd
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from collateral.models import MainWork, SubSubWork, SubWork, SubWorkUnitPrice
from loans.ids import bump_latest_id_from_existing, generate_incremental_loan_request_id
from loans.models import (
    ApprovalCommitteeLevel,
    ApprovalCommitteeMemberRule,
    Branch,
    City,
    CollateralType,
    CustomUser,
    Department,
    District,
    LoanApplicationDocumentType,
    LoanCategory,
    LoanCategoryDocumentRequirement,
    LoanRequest,
    Region,
    Zone,
)

PACK_ORDER = [
    'regions',
    'zones',
    'cities',
    'districts',
    'branches',
    'departments',
    'loan_categories',
    'collateral_types',
    'document_types',
    'category_documents',
    'users',
    'committee_levels',
    'committee_members',
    'construction_catalog',
    'loan_requests',
]

SKIP_SHEETS = {
    'instructions', 'readme', 'lookups', 'how_to', 'examples', 'example',
    'valid_values', 'dropdowns',
}

KIND_ALIASES = {
    'regions': 'regions',
    'zones': 'zones',
    'cities': 'cities',
    'woredas': 'cities',
    'districts': 'districts',
    'branches': 'branches',
    'departments': 'departments',
    'loan_categories': 'loan_categories',
    'categories': 'loan_categories',
    'loan_types': 'loan_categories',
    'collateral_types': 'collateral_types',
    'collaterals': 'collateral_types',
    'document_types': 'document_types',
    'category_documents': 'category_documents',
    'document_requirements': 'category_documents',
    'users': 'users',
    'committee_levels': 'committee_levels',
    'committee_members': 'committee_members',
    'construction_catalog': 'construction_catalog',
    'catalog': 'construction_catalog',
    'unit_prices': 'construction_catalog',
    'loan_requests': 'loan_requests',
    'loans': 'loan_requests',
}

ROLE_KEYS = {k for k, _ in CustomUser.ROLE_CHOICES}
ROLE_BY_LABEL = {label.lower(): key for key, label in CustomUser.ROLE_CHOICES}
ROLE_BY_LABEL.update({key.lower(): key for key, _ in CustomUser.ROLE_CHOICES})

COLLATERAL_KINDS = {k for k, _ in CollateralType.KIND_CHOICES}
COLLATERAL_KIND_BY_LABEL = {label.lower(): key for key, label in CollateralType.KIND_CHOICES}
COLLATERAL_KIND_BY_LABEL.update({k: k for k in COLLATERAL_KINDS})

APPRAISAL_MODES = {LoanCategory.MODE_MSME, LoanCategory.MODE_CORPORATE}
VOTER_SCOPES = {k for k, _ in ApprovalCommitteeLevel.VOTER_SCOPE_CHOICES}
COMMITTEE_STATUSES = {k for k, _ in LoanRequest.COMMITTEE_STATUS_CHOICES if k}
DISBURSE_STATUSES = {k for k, _ in LoanRequest.DISBURSE_STATUS_CHOICES if k}

TRUTHY = {'1', 'true', 'yes', 'y', 'required', 'on'}
FALSY = {'0', 'false', 'no', 'n', 'optional', 'off'}


class ImportResult:
    def __init__(self, kind: str = ''):
        self.kind = kind
        self.created = 0
        self.updated = 0
        self.skipped = 0
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def error(self, row_num: int, message: str) -> None:
        self.errors.append(f'row {row_num}: {message}')

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def merge(self, other: 'ImportResult') -> None:
        prefix = f'[{other.kind}] ' if other.kind else ''
        self.created += other.created
        self.updated += other.updated
        self.skipped += other.skipped
        self.errors.extend(prefix + e for e in other.errors)
        self.warnings.extend(prefix + w for w in other.warnings)

    def summary(self) -> str:
        parts = [
            f'created={self.created}',
            f'updated={self.updated}',
            f'skipped={self.skipped}',
            f'errors={len(self.errors)}',
        ]
        if self.kind:
            parts.insert(0, self.kind)
        return ' '.join(parts)


def _norm_key(key: Any) -> str:
    s = str(key or '').strip().lower()
    s = re.sub(r'[\s\-/]+', '_', s)
    s = re.sub(r'_+', '_', s).strip('_')
    return s


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return False


def stringify(value: Any) -> str:
    if _blank(value):
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(value, 'f').rstrip('0').rstrip('.')
    if isinstance(value, datetime):
        return value.isoformat(sep=' ')
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if text.endswith('.0') and text.replace('.', '', 1).replace('-', '', 1).isdigit():
        try:
            as_float = float(text)
            if as_float.is_integer():
                return str(int(as_float))
        except ValueError:
            pass
    return text


def col(row: Dict[str, Any], *names: str) -> str:
    keys = {_norm_key(n) for n in names}
    for key, value in row.items():
        if key in keys and not _blank(value):
            return stringify(value)
    return ''


def as_bool(value: Any, default: Optional[bool] = None) -> Optional[bool]:
    if _blank(value):
        return default
    text = stringify(value).lower()
    if text in TRUTHY:
        return True
    if text in FALSY:
        return False
    raise ValueError(f'Not a yes/no value: {value!r}')


def as_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if _blank(value):
        return default
    text = stringify(value)
    try:
        return int(Decimal(text))
    except (InvalidOperation, ValueError):
        raise ValueError(f'Not an integer: {value!r}')


def as_decimal(value: Any) -> Optional[Decimal]:
    if _blank(value):
        return None
    text = stringify(value).replace(',', '')
    try:
        return Decimal(text)
    except InvalidOperation:
        raise ValueError(f'Not a number: {value!r}')


def as_datetime(value: Any) -> Optional[datetime]:
    if _blank(value):
        return None
    if isinstance(value, datetime):
        dt = value
    elif hasattr(value, 'to_pydatetime'):
        dt = value.to_pydatetime()
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        text = stringify(value).replace('T', ' ')
        dt = parse_datetime(text)
        if dt is None:
            parsed_date = parse_date(text[:10]) if len(text) >= 10 else parse_date(text)
            if parsed_date is None:
                raise ValueError(f'Not a date/datetime: {value!r}')
            dt = datetime.combine(parsed_date, datetime.min.time())
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def as_date(value: Any) -> Optional[date]:
    dt = as_datetime(value)
    return dt.date() if dt else None


def _dataframe_to_rows(df: pd.DataFrame) -> List[Dict[str, Any]]:
    df = df.dropna(how='all')
    df.columns = [_norm_key(c) for c in df.columns]
    # Drop duplicate column names by keeping the first
    df = df.loc[:, ~pd.Index(df.columns).duplicated()]
    rows: List[Dict[str, Any]] = []
    for raw in df.to_dict(orient='records'):
        if all(_blank(v) for v in raw.values()):
            continue
        rows.append(raw)
    return rows


def _open_excel(source: Any, **kwargs) -> pd.DataFrame:
    name = str(getattr(source, 'name', source) or '').lower()
    if hasattr(source, 'read'):
        data = source.read()
        if hasattr(source, 'seek'):
            try:
                source.seek(0)
            except Exception:
                pass
        buffer = BytesIO(data if isinstance(data, (bytes, bytearray)) else str(data).encode())
        if name.endswith('.csv') or name.endswith('.txt'):
            return pd.read_csv(buffer)
        engine = 'xlrd' if name.endswith('.xls') and not name.endswith('.xlsx') else 'openpyxl'
        try:
            return pd.read_excel(buffer, engine=engine, **kwargs)
        except Exception as exc:
            if engine == 'xlrd':
                raise ValueError('Save the file as .xlsx (Excel 2007+) and retry.') from exc
            raise
    path = str(source)
    lower = path.lower()
    if lower.endswith('.csv') or lower.endswith('.txt'):
        return pd.read_csv(path)
    engine = 'xlrd' if lower.endswith('.xls') and not lower.endswith('.xlsx') else 'openpyxl'
    try:
        return pd.read_excel(path, engine=engine, **kwargs)
    except Exception as exc:
        if engine == 'xlrd':
            raise ValueError('Save the file as .xlsx (Excel 2007+) and retry.') from exc
        raise


def read_table(source: Any, sheet_name: Optional[str] = None) -> List[Dict[str, Any]]:
    kwargs = {}
    if sheet_name:
        kwargs['sheet_name'] = sheet_name
    df = _open_excel(source, **kwargs)
    if isinstance(df, dict):
        # sheet_name=None on a workbook can return a dict in some pandas versions
        first = next(iter(df.values()))
        return _dataframe_to_rows(first)
    return _dataframe_to_rows(df)


def read_workbook(source: Any) -> Dict[str, List[Dict[str, Any]]]:
    name = str(getattr(source, 'name', source) or '').lower()
    if name.endswith('.csv') or name.endswith('.txt'):
        return {'sheet1': read_table(source)}
    xl = _open_excel(source, sheet_name=None)
    if isinstance(xl, dict):
        return {str(k): _dataframe_to_rows(v) for k, v in xl.items()}
    return {'sheet1': _dataframe_to_rows(xl)}


def normalize_sheet_kind(name: str) -> str:
    key = _norm_key(name)
    key = re.sub(r'^\d+_', '', key)
    return KIND_ALIASES.get(key, key)


def _row_num(index: int) -> int:
    return index + 2  # header is row 1


def _lookup_role(value: str) -> str:
    text = (value or '').strip()
    if not text:
        return ''
    key = ROLE_BY_LABEL.get(text.lower()) or ROLE_BY_LABEL.get(_norm_key(text).replace('_', ' '))
    if not key:
        raise ValueError(
            f'Unknown role {value!r}. Use a key such as loan_officer or the UI label.'
        )
    return key


def _lookup_kind(value: str) -> str:
    text = (value or '').strip()
    if not text:
        return ''
    key = COLLATERAL_KIND_BY_LABEL.get(text.lower())
    if not key:
        raise ValueError(
            f'Unknown collateral kind {value!r}. Use building, land, movable, or mixed.'
        )
    return key


def _get_region(name: str) -> Region:
    obj = Region.objects.filter(name__iexact=name).first()
    if not obj:
        raise ValueError(f'Region not found: {name}')
    return obj


def _get_zone(name: str, region_name: str = '') -> Zone:
    qs = Zone.objects.filter(name__iexact=name)
    if region_name:
        qs = qs.filter(region__name__iexact=region_name)
    matches = list(qs[:2])
    if not matches:
        raise ValueError(f'Zone not found: {name}')
    if len(matches) > 1 and not region_name:
        raise ValueError(f'Zone {name!r} exists in more than one region; set region.')
    return matches[0]


def _get_city(name: str, zone_name: str = '', region_name: str = '') -> City:
    qs = City.objects.filter(name__iexact=name)
    if zone_name:
        qs = qs.filter(zone__name__iexact=zone_name)
    if region_name:
        qs = qs.filter(zone__region__name__iexact=region_name)
    matches = list(qs[:2])
    if not matches:
        raise ValueError(f'City/woreda not found: {name}')
    if len(matches) > 1 and not zone_name:
        raise ValueError(f'City {name!r} exists in more than one zone; set zone.')
    return matches[0]


def _get_district(name: str) -> District:
    obj = District.objects.filter(name__iexact=name).first()
    if not obj:
        raise ValueError(f'District not found: {name}')
    return obj


def _get_branch(name: str, district_name: str = '') -> Branch:
    qs = Branch.objects.filter(name__iexact=name)
    if district_name:
        qs = qs.filter(district__name__iexact=district_name)
    obj = qs.first()
    if not obj:
        raise ValueError(f'Branch not found: {name}')
    return obj


def _get_department(value: str) -> Department:
    text = (value or '').strip()
    obj = Department.objects.filter(key__iexact=text).first()
    if obj:
        return obj
    obj = Department.objects.filter(name__iexact=text).first()
    if not obj:
        raise ValueError(f'Department not found: {value}')
    return obj


def _apply_update(obj, fields: Dict[str, Any], update: bool) -> str:
    """Return 'created' (caller creates), 'updated', or 'skipped' — used after get."""
    changed = []
    for key, value in fields.items():
        if getattr(obj, key) != value:
            changed.append(key)
            setattr(obj, key, value)
    if not changed:
        return 'skipped'
    if not update:
        return 'exists'
    obj.save(update_fields=changed)
    return 'updated'


def _tally(result: ImportResult, action: str) -> None:
    if action == 'created':
        result.created += 1
    elif action == 'updated':
        result.updated += 1
    else:
        result.skipped += 1


def import_regions(rows: Sequence[Dict[str, Any]], *, update: bool = False, **_kwargs) -> ImportResult:
    result = ImportResult('regions')
    for i, row in enumerate(rows):
        n = _row_num(i)
        name = col(row, 'name', 'region', 'region_name')
        if not name:
            result.error(n, 'name is required')
            continue
        try:
            with transaction.atomic():
                obj = Region.objects.filter(name__iexact=name).first()
                if obj is None:
                    Region.objects.create(name=name)
                    _tally(result, 'created')
                else:
                    action = _apply_update(obj, {'name': name}, update)
                    if action == 'exists':
                        _tally(result, 'skipped')
                    else:
                        _tally(result, action)
        except Exception as exc:
            result.error(n, str(exc))
    return result


def import_zones(rows: Sequence[Dict[str, Any]], *, update: bool = False, **_kwargs) -> ImportResult:
    result = ImportResult('zones')
    for i, row in enumerate(rows):
        n = _row_num(i)
        name = col(row, 'name', 'zone', 'zone_name')
        region_name = col(row, 'region', 'region_name')
        if not name:
            result.error(n, 'name is required')
            continue
        if not region_name:
            result.error(
                n,
                'region is required. import_zones now loads geographic Zones '
                '(region + name). For operational Districts use import_districts.',
            )
            continue
        try:
            with transaction.atomic():
                region = _get_region(region_name)
                obj = Zone.objects.filter(region=region, name__iexact=name).first()
                if obj is None:
                    Zone.objects.create(region=region, name=name)
                    _tally(result, 'created')
                else:
                    _tally(result, 'skipped')
        except Exception as exc:
            result.error(n, str(exc))
    return result


def import_cities(rows: Sequence[Dict[str, Any]], *, update: bool = False, **_kwargs) -> ImportResult:
    result = ImportResult('cities')
    for i, row in enumerate(rows):
        n = _row_num(i)
        name = col(row, 'name', 'city', 'city_name', 'woreda')
        zone_name = col(row, 'zone', 'zone_name')
        region_name = col(row, 'region', 'region_name')
        if not name or not zone_name:
            result.error(n, 'name and zone are required')
            continue
        try:
            with transaction.atomic():
                zone = _get_zone(zone_name, region_name)
                obj = City.objects.filter(zone=zone, name__iexact=name).first()
                if obj is None:
                    City.objects.create(zone=zone, name=name)
                    _tally(result, 'created')
                else:
                    _tally(result, 'skipped')
        except Exception as exc:
            result.error(n, str(exc))
    return result


def import_districts(rows: Sequence[Dict[str, Any]], *, update: bool = False, **_kwargs) -> ImportResult:
    result = ImportResult('districts')
    for i, row in enumerate(rows):
        n = _row_num(i)
        name = col(row, 'name', 'district', 'district_name', 'zone')
        if not name:
            result.error(n, 'name is required')
            continue
        try:
            with transaction.atomic():
                obj = District.objects.filter(name__iexact=name).first()
                if obj is None:
                    District.objects.create(name=name)
                    _tally(result, 'created')
                else:
                    action = _apply_update(obj, {'name': name}, update)
                    _tally(result, 'skipped' if action in ('exists', 'skipped') else action)
        except Exception as exc:
            result.error(n, str(exc))
    return result


def import_branches(rows: Sequence[Dict[str, Any]], *, update: bool = False, **_kwargs) -> ImportResult:
    result = ImportResult('branches')
    for i, row in enumerate(rows):
        n = _row_num(i)
        name = col(row, 'name', 'branch', 'branch_name')
        district_name = col(row, 'district', 'district_name', 'zone')
        if not name or not district_name:
            result.error(n, 'name and district are required')
            continue
        try:
            with transaction.atomic():
                district = _get_district(district_name)
                obj = Branch.objects.filter(name__iexact=name).first()
                if obj is None:
                    Branch.objects.create(name=name, district=district)
                    _tally(result, 'created')
                else:
                    action = _apply_update(obj, {'district': district}, update)
                    if action == 'exists':
                        _tally(result, 'skipped')
                    else:
                        _tally(result, action)
        except Exception as exc:
            result.error(n, str(exc))
    return result


def import_departments(rows: Sequence[Dict[str, Any]], *, update: bool = False, **_kwargs) -> ImportResult:
    result = ImportResult('departments')
    valid_keys = {k for k, _ in Department.KEY_CHOICES}
    for i, row in enumerate(rows):
        n = _row_num(i)
        key = col(row, 'key', 'department_key').lower()
        name = col(row, 'name', 'department', 'department_name')
        if not key:
            result.error(n, 'key is required (cooperative, finance, credit, management, board)')
            continue
        if key not in valid_keys:
            result.error(n, f'Unknown department key {key!r}')
            continue
        if not name:
            name = dict(Department.KEY_CHOICES)[key]
        try:
            is_active = as_bool(col(row, 'is_active'), True)
            sort_order = as_int(col(row, 'sort_order'), 0) or 0
            with transaction.atomic():
                obj = Department.objects.filter(key=key).first()
                fields = {'name': name, 'is_active': is_active, 'sort_order': sort_order}
                if obj is None:
                    Department.objects.create(key=key, **fields)
                    _tally(result, 'created')
                else:
                    action = _apply_update(obj, fields, update)
                    _tally(result, 'skipped' if action in ('exists', 'skipped') else action)
        except Exception as exc:
            result.error(n, str(exc))
    return result


def import_loan_categories(rows: Sequence[Dict[str, Any]], *, update: bool = False, **_kwargs) -> ImportResult:
    result = ImportResult('loan_categories')
    for i, row in enumerate(rows):
        n = _row_num(i)
        name = col(row, 'name', 'category', 'loan_type', 'loan_category')
        if not name:
            result.error(n, 'name is required')
            continue
        mode_raw = col(row, 'appraisal_mode', 'mode') or LoanCategory.MODE_MSME
        mode = mode_raw.strip().lower()
        if mode in ('msme / cashflow', 'msme/cashflow', 'cashflow'):
            mode = LoanCategory.MODE_MSME
        if mode not in APPRAISAL_MODES:
            result.error(n, f'appraisal_mode must be msme or corporate (got {mode_raw!r})')
            continue
        try:
            with transaction.atomic():
                obj = LoanCategory.objects.filter(name__iexact=name).first()
                if obj is None:
                    LoanCategory.objects.create(name=name, appraisal_mode=mode)
                    _tally(result, 'created')
                else:
                    action = _apply_update(obj, {'appraisal_mode': mode}, update)
                    _tally(result, 'skipped' if action in ('exists', 'skipped') else action)
        except Exception as exc:
            result.error(n, str(exc))
    return result


def import_collateral_types(rows: Sequence[Dict[str, Any]], *, update: bool = False, **_kwargs) -> ImportResult:
    result = ImportResult('collateral_types')
    for i, row in enumerate(rows):
        n = _row_num(i)
        name = col(row, 'name', 'collateral', 'collateral_type')
        if not name:
            result.error(n, 'name (or collateral) is required')
            continue
        try:
            kind = _lookup_kind(col(row, 'kind', 'collateral_kind')) if col(row, 'kind', 'collateral_kind') else ''
            with transaction.atomic():
                obj = CollateralType.objects.filter(name__iexact=name).first()
                if obj is None:
                    CollateralType.objects.create(name=name, kind=kind)
                    _tally(result, 'created')
                else:
                    fields = {}
                    if kind:
                        fields['kind'] = kind
                    action = _apply_update(obj, fields, update) if fields else 'skipped'
                    _tally(result, 'skipped' if action in ('exists', 'skipped') else action)
        except Exception as exc:
            result.error(n, str(exc))
    return result


def import_document_types(rows: Sequence[Dict[str, Any]], *, update: bool = False, **_kwargs) -> ImportResult:
    result = ImportResult('document_types')
    for i, row in enumerate(rows):
        n = _row_num(i)
        name = col(row, 'name', 'document_type')
        if not name:
            result.error(n, 'name is required')
            continue
        try:
            mode = col(row, 'for_appraisal_mode', 'appraisal_mode').lower()
            if mode in ('all', 'both', ''):
                mode = ''
            if mode not in ('', 'msme', 'corporate'):
                raise ValueError(f'for_appraisal_mode must be blank, msme, or corporate')
            fields = {
                'order': as_int(col(row, 'order'), 0) or 0,
                'is_required': as_bool(col(row, 'is_required'), True),
                'allowed_extensions': col(row, 'allowed_extensions') or 'pdf,jpg,jpeg,png',
                'require_officer_verification': as_bool(col(row, 'require_officer_verification'), False),
                'enable_ocr_match': as_bool(col(row, 'enable_ocr_match'), False),
                'auth_notes': col(row, 'auth_notes', 'notes'),
                'for_appraisal_mode': mode,
            }
            size = as_int(col(row, 'max_file_size_mb'))
            if size is not None:
                fields['max_file_size_mb'] = size
            with transaction.atomic():
                obj = LoanApplicationDocumentType.objects.filter(name__iexact=name).first()
                if obj is None:
                    LoanApplicationDocumentType.objects.create(name=name, **fields)
                    _tally(result, 'created')
                else:
                    action = _apply_update(obj, fields, update)
                    _tally(result, 'skipped' if action in ('exists', 'skipped') else action)
        except Exception as exc:
            result.error(n, str(exc))
    return result


def import_category_documents(rows: Sequence[Dict[str, Any]], *, update: bool = False, **_kwargs) -> ImportResult:
    result = ImportResult('category_documents')
    for i, row in enumerate(rows):
        n = _row_num(i)
        cat_name = col(row, 'category', 'loan_category', 'loan_type')
        doc_name = col(row, 'document_type', 'document', 'name')
        if not cat_name or not doc_name:
            result.error(n, 'category and document_type are required')
            continue
        try:
            category = LoanCategory.objects.filter(name__iexact=cat_name).first()
            if not category:
                raise ValueError(f'Loan category not found: {cat_name}')
            doc_type = LoanApplicationDocumentType.objects.filter(name__iexact=doc_name).first()
            if not doc_type:
                raise ValueError(f'Document type not found: {doc_name}')
            fields = {
                'is_required': as_bool(col(row, 'is_required'), True),
                'order': as_int(col(row, 'order'), 0) or 0,
            }
            with transaction.atomic():
                obj = LoanCategoryDocumentRequirement.objects.filter(
                    category=category, document_type=doc_type,
                ).first()
                if obj is None:
                    LoanCategoryDocumentRequirement.objects.create(
                        category=category, document_type=doc_type, **fields,
                    )
                    _tally(result, 'created')
                else:
                    action = _apply_update(obj, fields, update)
                    _tally(result, 'skipped' if action in ('exists', 'skipped') else action)
        except Exception as exc:
            result.error(n, str(exc))
    return result


def import_users(
    rows: Sequence[Dict[str, Any]],
    *,
    update: bool = False,
    default_password: str = '',
    **_kwargs,
) -> ImportResult:
    result = ImportResult('users')
    for i, row in enumerate(rows):
        n = _row_num(i)
        username = col(row, 'username', 'user', 'login')
        if not username:
            result.error(n, 'username is required')
            continue
        try:
            role = _lookup_role(col(row, 'role')) if col(row, 'role') else 'loan_officer'
            phone = col(row, 'phone_number', 'phone', 'mobile')
            if not phone:
                raise ValueError('phone_number is required')
            if len(phone) > 20:
                raise ValueError('phone_number is longer than 20 characters')
            district_name = col(row, 'district', 'district_name', 'zone')
            branch_name = col(row, 'branch', 'branch_name')
            dept_name = col(row, 'department', 'department_key')
            district = _get_district(district_name) if district_name else None
            branch = _get_branch(branch_name, district_name) if branch_name else None
            if branch and not district:
                district = branch.district
            department = _get_department(dept_name) if dept_name else None
            is_active = as_bool(col(row, 'is_active'), True)
            password = col(row, 'password') or default_password
            fields = {
                'email': col(row, 'email') or '',
                'first_name': col(row, 'first_name', 'firstname'),
                'last_name': col(row, 'last_name', 'lastname'),
                'phone_number': phone,
                'role': role,
                'district': district,
                'branch': branch,
                'department': department,
                'is_active': is_active,
            }
            if role in ('superadmin', 'admin'):
                fields['is_staff'] = True
            if role == 'superadmin':
                fields['is_superuser'] = True
            with transaction.atomic():
                obj = CustomUser.objects.filter(username__iexact=username).first()
                if obj is None:
                    obj = CustomUser(username=username, **fields)
                    if password:
                        obj.set_password(password)
                    else:
                        obj.set_unusable_password()
                        result.warn(
                            f'row {n}: {username} created with no password '
                            f'(pass --default-password or fill the password column)'
                        )
                    obj.save()
                    _tally(result, 'created')
                else:
                    action = _apply_update(obj, fields, update)
                    if update and password:
                        obj.set_password(password)
                        obj.save(update_fields=['password'])
                        if action != 'updated':
                            action = 'updated'
                    _tally(result, 'skipped' if action in ('exists', 'skipped') else action)
        except Exception as exc:
            result.error(n, str(exc))
    return result


def import_committee_levels(rows: Sequence[Dict[str, Any]], *, update: bool = False, **_kwargs) -> ImportResult:
    result = ImportResult('committee_levels')
    for i, row in enumerate(rows):
        n = _row_num(i)
        key = col(row, 'key', 'level_key').lower().replace(' ', '_')
        name = col(row, 'name', 'level_name')
        if not key or not name:
            result.error(n, 'key and name are required')
            continue
        try:
            scope = col(row, 'voter_scope', 'scope').lower() or ApprovalCommitteeLevel.SCOPE_ORGANIZATION
            if scope not in VOTER_SCOPES:
                raise ValueError(f'voter_scope must be branch, district, or organization')
            tie = col(row, 'tiebreaker_role')
            fields = {
                'name': name,
                'voter_scope': scope,
                'sequence_order': as_int(col(row, 'sequence_order', 'order'), 1) or 1,
                'is_active': as_bool(col(row, 'is_active'), True),
                'min_approvals_required': as_int(col(row, 'min_approvals_required', 'min_approvals'), 2) or 2,
                'min_declines_required': as_int(col(row, 'min_declines_required', 'min_declines'), 2) or 2,
                'tiebreaker_role': _lookup_role(tie) if tie else '',
                'min_loan_amount': as_decimal(col(row, 'min_loan_amount')),
                'max_loan_amount': as_decimal(col(row, 'max_loan_amount')),
            }
            with transaction.atomic():
                obj = ApprovalCommitteeLevel.objects.filter(key=key).first()
                if obj is None:
                    ApprovalCommitteeLevel.objects.create(key=key, **fields)
                    _tally(result, 'created')
                else:
                    action = _apply_update(obj, fields, update)
                    _tally(result, 'skipped' if action in ('exists', 'skipped') else action)
        except Exception as exc:
            result.error(n, str(exc))
    return result


def import_committee_members(rows: Sequence[Dict[str, Any]], *, update: bool = False, **_kwargs) -> ImportResult:
    result = ImportResult('committee_members')
    for i, row in enumerate(rows):
        n = _row_num(i)
        level_key = col(row, 'level_key', 'level', 'committee_level').lower().replace(' ', '_')
        ptype = col(row, 'participant_type', 'type').lower() or ApprovalCommitteeMemberRule.PARTICIPANT_ROLE
        if ptype in ('anyone with role', 'role'):
            ptype = ApprovalCommitteeMemberRule.PARTICIPANT_ROLE
        if ptype in ('specific user', 'user', 'named'):
            ptype = ApprovalCommitteeMemberRule.PARTICIPANT_USER
        if not level_key:
            result.error(n, 'level_key is required')
            continue
        try:
            level = ApprovalCommitteeLevel.objects.filter(key=level_key).first()
            if not level:
                raise ValueError(f'Committee level not found: {level_key}')
            role = _lookup_role(col(row, 'role')) if col(row, 'role') else ''
            username = col(row, 'username', 'user')
            user = None
            if username:
                user = CustomUser.objects.filter(username__iexact=username).first()
                if not user:
                    raise ValueError(f'User not found: {username}')
            if ptype == ApprovalCommitteeMemberRule.PARTICIPANT_ROLE and not role:
                raise ValueError('role is required when participant_type is role')
            if ptype == ApprovalCommitteeMemberRule.PARTICIPANT_USER and not user:
                raise ValueError('username is required when participant_type is user')
            label = col(row, 'label') or role or (user.username if user else '')
            is_active = as_bool(col(row, 'is_active'), True)
            qs = ApprovalCommitteeMemberRule.objects.filter(level=level, participant_type=ptype)
            if ptype == ApprovalCommitteeMemberRule.PARTICIPANT_ROLE:
                qs = qs.filter(role=role)
            else:
                qs = qs.filter(user=user)
            with transaction.atomic():
                obj = qs.first()
                fields = {
                    'role': role,
                    'user': user,
                    'label': label,
                    'is_active': is_active,
                }
                if obj is None:
                    ApprovalCommitteeMemberRule.objects.create(level=level, participant_type=ptype, **fields)
                    _tally(result, 'created')
                else:
                    action = _apply_update(obj, fields, update)
                    _tally(result, 'skipped' if action in ('exists', 'skipped') else action)
        except Exception as exc:
            result.error(n, str(exc))
    return result


def import_construction_catalog(rows: Sequence[Dict[str, Any]], *, update: bool = False, **_kwargs) -> ImportResult:
    result = ImportResult('construction_catalog')
    for i, row in enumerate(rows):
        n = _row_num(i)
        main_name = col(row, 'main_work', 'main')
        if not main_name:
            result.error(n, 'main_work is required')
            continue
        try:
            with transaction.atomic():
                main_order = as_int(col(row, 'main_work_order'), 0) or 0
                main = MainWork.objects.filter(name__iexact=main_name).first()
                if main is None:
                    main = MainWork.objects.create(name=main_name, order=main_order)
                    result.created += 1
                elif update and main.order != main_order and col(row, 'main_work_order'):
                    main.order = main_order
                    main.save(update_fields=['order'])
                    result.updated += 1

                sub_name = col(row, 'sub_work', 'sub')
                sub = None
                if sub_name:
                    sub_order = as_decimal(col(row, 'sub_work_order')) or Decimal('0')
                    sub = SubWork.objects.filter(main_work=main, name__iexact=sub_name).first()
                    if sub is None:
                        sub = SubWork.objects.create(main_work=main, name=sub_name, order=sub_order)
                        result.created += 1
                    elif update and col(row, 'sub_work_order'):
                        sub.order = sub_order
                        sub.save(update_fields=['order'])
                        result.updated += 1

                ssw_name = col(row, 'sub_sub_work', 'sub_sub', 'item')
                ssw = None
                if ssw_name:
                    if sub is None:
                        raise ValueError('sub_work is required when sub_sub_work is set')
                    ssw = SubSubWork.objects.filter(sub_work=sub, name__iexact=ssw_name).first()
                    fields = {
                        'unit_measure': col(row, 'unit_measure', 'unit') or '',
                        'order': col(row, 'sub_sub_order', 'item_order') or '0',
                    }
                    if ssw is None:
                        ssw = SubSubWork.objects.create(sub_work=sub, name=ssw_name, **fields)
                        result.created += 1
                    elif update:
                        action = _apply_update(ssw, fields, True)
                        if action == 'updated':
                            result.updated += 1

                city_name = col(row, 'city', 'woreda', 'city_name')
                price = as_decimal(col(row, 'unit_price', 'price'))
                if price is not None:
                    if not city_name:
                        raise ValueError('city is required when unit_price is set')
                    if ssw is None and sub is None:
                        raise ValueError('sub_work or sub_sub_work is required for a unit price')
                    city = _get_city(
                        city_name,
                        col(row, 'zone', 'zone_name'),
                        col(row, 'region', 'region_name'),
                    )
                    lookup = {'city': city, 'sub_work': None if ssw else sub, 'sub_sub_work': ssw}
                    up = SubWorkUnitPrice.objects.filter(**lookup).first()
                    price_fields = {
                        'unit_price': price,
                        'effective_from': as_date(col(row, 'effective_from')),
                        'effective_to': as_date(col(row, 'effective_to')),
                    }
                    if up is None:
                        SubWorkUnitPrice.objects.create(**lookup, **price_fields)
                        result.created += 1
                    else:
                        action = _apply_update(up, price_fields, update)
                        if action == 'exists':
                            result.skipped += 1
                        elif action == 'updated':
                            result.updated += 1
                        else:
                            result.skipped += 1
                elif not sub_name and not ssw_name:
                    pass
        except Exception as exc:
            result.error(n, str(exc))
    return result


def _normalize_loan_status(value: str) -> str:
    text = (value or '').strip()
    if not text:
        return ''
    mapping = {
        'pending': 'Pending',
        'approved': 'Approved',
        'rejected': 'Rejected',
        'declined': 'Rejected',
        'disbursed': 'Approved',
    }
    return mapping.get(text.lower(), text[:20])


def import_loan_requests(rows: Sequence[Dict[str, Any]], *, update: bool = False, **_kwargs) -> ImportResult:
    result = ImportResult('loan_requests')
    for i, row in enumerate(rows):
        n = _row_num(i)
        applicant = col(row, 'applicant_name', 'applicant', 'customer_name', 'name')
        if not applicant:
            result.error(n, 'applicant_name is required')
            continue
        try:
            cat_name = col(row, 'category', 'loan_category', 'loan_type')
            coll_name = col(row, 'collateral', 'collateral_type')
            branch_name = col(row, 'branch', 'branch_name')
            if not cat_name or not coll_name or not branch_name:
                raise ValueError('category, collateral, and branch are required')
            category = LoanCategory.objects.filter(name__iexact=cat_name).first()
            if not category:
                raise ValueError(f'Loan category not found: {cat_name}')
            collateral = CollateralType.objects.filter(name__iexact=coll_name).first()
            if not collateral:
                raise ValueError(f'Collateral type not found: {coll_name}')
            district_name = col(row, 'district', 'district_name', 'zone')
            branch = _get_branch(branch_name, district_name)
            district = branch.district
            if district_name:
                district = _get_district(district_name)
            amount = as_decimal(col(row, 'amount_requested', 'amount'))
            if amount is None:
                raise ValueError('amount_requested is required')
            phone = col(row, 'phone_number', 'phone', 'mobile') or '0953333311'
            if len(phone) > 15:
                raise ValueError('phone_number is longer than 15 characters')
            reason = col(row, 'reason', 'purpose') or 'Migrated from existing system'
            history = col(row, 'customer_history', 'history').lower()
            if history and history not in ('new', 'existing'):
                raise ValueError('customer_history must be new or existing')
            origin = col(row, 'origin_level', 'origin').lower() or LoanRequest.ORIGIN_BRANCH
            if origin in ('ho', 'head office', 'head_office', 'credit'):
                origin = LoanRequest.ORIGIN_HEAD_OFFICE
            if origin not in (LoanRequest.ORIGIN_BRANCH, LoanRequest.ORIGIN_HEAD_OFFICE):
                raise ValueError('origin_level must be branch or head_office')
            source = col(row, 'source_channel', 'source').lower() or LoanRequest.SOURCE_STAFF
            if source in ('digital', 'online', 'portal'):
                source = LoanRequest.SOURCE_ONLINE
            if source not in (LoanRequest.SOURCE_STAFF, LoanRequest.SOURCE_ONLINE):
                raise ValueError('source_channel must be staff or online')
            status = _normalize_loan_status(col(row, 'status'))
            committee_status = col(row, 'committee_status').lower()
            if committee_status and committee_status not in COMMITTEE_STATUSES:
                raise ValueError(f'Unknown committee_status {committee_status!r}')
            disburse = col(row, 'disbursement_status').lower()
            if disburse and disburse not in DISBURSE_STATUSES:
                raise ValueError(f'Unknown disbursement_status {disburse!r}')
            officer_name = col(row, 'assigned_loan_officer', 'loan_officer', 'officer')
            officer = None
            if officer_name:
                officer = CustomUser.objects.filter(username__iexact=officer_name).first()
                if not officer:
                    raise ValueError(f'Loan officer not found: {officer_name}')
            loan_id = col(row, 'loan_request_id', 'loan_id', 'request_id')
            if loan_id and len(loan_id) > 22:
                raise ValueError('loan_request_id is longer than 22 characters')
            queue_flag = as_bool(col(row, 'queue_approved', 'operation_manager_approval'), None)
            if queue_flag is None:
                queue_flag = status.lower() in ('approved',) or committee_status in (
                    LoanRequest.COMMITTEE_APPROVED,
                ) or disburse == LoanRequest.DISBURSE_DISBURSED
            fields = {
                'applicant_name': applicant,
                'phone_number': phone,
                'customer_number': col(row, 'customer_number', 'cif', 'cust_id') or None,
                'email': col(row, 'email') or None,
                'category': category,
                'collateral': collateral,
                'amount_requested': amount,
                'reason': reason,
                'status': status or None,
                'district': district,
                'branch': branch,
                'customer_history': history or None,
                'origin_level': origin,
                'source_channel': source,
                'assigned_loan_officer': officer,
                'queue_approved': bool(queue_flag),
                'operation_manager_approval': bool(queue_flag),
            }
            if col(row, 'date_requested'):
                fields['date_requested'] = as_datetime(col(row, 'date_requested'))
            if committee_status:
                fields['committee_status'] = committee_status
            if committee_status == LoanRequest.COMMITTEE_APPROVED:
                fields['committee_final_decision'] = 'approve'
            final_amt = as_decimal(col(row, 'committee_final_amount', 'approved_amount'))
            if final_amt is not None:
                fields['committee_final_amount'] = final_amt
            if disburse:
                fields['disbursement_status'] = disburse
            with transaction.atomic():
                obj = None
                if loan_id:
                    obj = LoanRequest.objects.filter(loan_request_id=loan_id).first()
                if obj is None:
                    if not loan_id:
                        loan_id = generate_incremental_loan_request_id()
                    LoanRequest.objects.create(loan_request_id=loan_id, **fields)
                    _tally(result, 'created')
                else:
                    action = _apply_update(obj, fields, update)
                    _tally(result, 'skipped' if action in ('exists', 'skipped') else action)
        except Exception as exc:
            result.error(n, str(exc))
    bump_latest_id_from_existing()
    return result


IMPORTERS: Dict[str, Callable[..., ImportResult]] = {
    'regions': import_regions,
    'zones': import_zones,
    'cities': import_cities,
    'districts': import_districts,
    'branches': import_branches,
    'departments': import_departments,
    'loan_categories': import_loan_categories,
    'collateral_types': import_collateral_types,
    'document_types': import_document_types,
    'category_documents': import_category_documents,
    'users': import_users,
    'committee_levels': import_committee_levels,
    'committee_members': import_committee_members,
    'construction_catalog': import_construction_catalog,
    'loan_requests': import_loan_requests,
}


def run_import(
    kind: str,
    source: Any,
    *,
    sheet_name: Optional[str] = None,
    update: bool = False,
    default_password: str = '',
) -> ImportResult:
    resolved = KIND_ALIASES.get(_norm_key(kind), _norm_key(kind))
    fn = IMPORTERS.get(resolved)
    if not fn:
        raise ValueError(f'Unknown import kind {kind!r}. Choose one of: {", ".join(PACK_ORDER)}')
    rows = read_table(source, sheet_name=sheet_name)
    return fn(rows, update=update, default_password=default_password)


def import_pack(
    source: Any,
    *,
    update: bool = False,
    default_password: str = '',
) -> ImportResult:
    sheets = read_workbook(source)
    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    unknown: List[str] = []
    for name, rows in sheets.items():
        if not rows:
            continue
        kind = normalize_sheet_kind(name)
        if kind in SKIP_SHEETS:
            continue
        if kind not in IMPORTERS:
            unknown.append(name)
            continue
        by_kind[kind] = rows
    combined = ImportResult('pack')
    if unknown:
        combined.warn('Skipped unknown sheets: ' + ', '.join(unknown))
    for kind in PACK_ORDER:
        rows = by_kind.get(kind)
        if not rows:
            continue
        part = IMPORTERS[kind](rows, update=update, default_password=default_password)
        combined.merge(part)
    if combined.created == 0 and combined.updated == 0 and combined.skipped == 0 and not combined.errors:
        combined.warn('No recognised data sheets found. Use the DECSI migration pack sheet names.')
    return combined
