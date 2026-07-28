"""Reporting / exports: pipeline Excel, appraisal pack Excel, branch dashboards."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from django.db.models import Count, Q, QuerySet, Sum
from django.http import HttpResponse
from django.utils import timezone

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from openpyxl.utils import get_column_letter


REPORT_ROLES = (
    'branch_manager', 'operation_manager', 'finance_manager', 'credit_committee',
    'loan_officer', 'district_manager', 'accountant', 'admin', 'superadmin',
)


def user_can_access_reports(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) in REPORT_ROLES


def reporting_base_queryset(user) -> QuerySet:
    from loans.models import LoanRequest

    qs = LoanRequest.objects.select_related(
        'branch', 'branch__district', 'category', 'collateral',
        'assigned_loan_officer', 'appraisal',
    ).order_by('-date_requested', '-id')
    role = getattr(user, 'role', None)
    if getattr(user, 'is_superuser', False) or role in ('admin', 'superadmin', 'operation_manager', 'finance_manager', 'credit_committee', 'accountant'):
        return qs
    if role == 'loan_officer':
        return qs.filter(assigned_loan_officer=user)
    if role == 'branch_manager':
        if getattr(user, 'branch_id', None):
            return qs.filter(branch_id=user.branch_id)
        if getattr(user, 'district_id', None):
            return qs.filter(branch__district_id=user.district_id)
        return qs.none()
    if role == 'district_manager' and getattr(user, 'district_id', None):
        return qs.filter(branch__district_id=user.district_id)
    return qs.none()


def apply_report_filters(qs: QuerySet, params: Dict[str, Any], user=None) -> QuerySet:
    status = (params.get('status') or '').strip()
    committee_status = (params.get('committee_status') or '').strip()
    disbursement_status = (params.get('disbursement_status') or '').strip()
    branch_id = (params.get('branch_id') or '').strip()
    district_id = (params.get('district_id') or '').strip()
    date_from = (params.get('date_from') or '').strip()
    date_to = (params.get('date_to') or '').strip()

    if status:
        qs = qs.filter(status__iexact=status)
    if committee_status:
        qs = qs.filter(committee_status=committee_status)
    if disbursement_status:
        qs = qs.filter(disbursement_status=disbursement_status)

    # Branch managers are already scoped; still allow explicit branch if in scope
    role = getattr(user, 'role', None) if user else None
    can_pick_branch = (
        not user
        or getattr(user, 'is_superuser', False)
        or role in ('admin', 'superadmin', 'operation_manager', 'finance_manager', 'credit_committee', 'accountant', 'district_manager')
    )
    if branch_id and can_pick_branch:
        qs = qs.filter(branch_id=branch_id)
    elif branch_id and role == 'branch_manager' and str(getattr(user, 'branch_id', '')) == str(branch_id):
        qs = qs.filter(branch_id=branch_id)

    if district_id and can_pick_branch:
        qs = qs.filter(branch__district_id=district_id)

    if date_from:
        qs = qs.filter(date_requested__date__gte=date_from)
    if date_to:
        qs = qs.filter(date_requested__date__lte=date_to)
    return qs


def filtered_reporting_queryset(user, params: Dict[str, Any]) -> QuerySet:
    return apply_report_filters(reporting_base_queryset(user), params, user=user)


def _cell(v):
    if v is None:
        return ''
    if isinstance(v, Decimal):
        return float(v)
    if hasattr(v, 'strftime'):
        return v.strftime('%Y-%m-%d %H:%M') if hasattr(v, 'hour') else v.strftime('%Y-%m-%d')
    return v


def _autosize(ws, max_width=40):
    for col in ws.columns:
        letter = get_column_letter(col[0].column)
        width = 10
        for cell in col:
            if cell.value is not None:
                width = max(width, min(max_width, len(str(cell.value)) + 2))
        ws.column_dimensions[letter].width = width


def _write_header(ws, headers: List[str]):
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True)


def build_pipeline_workbook(qs: QuerySet) -> BytesIO:
    """Multi-sheet Excel: Pipeline + Branch summary."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'Pipeline'
    headers = [
        'Loan ID', 'Applicant', 'Phone', 'Branch', 'District', 'Category',
        'Amount requested', 'Status', 'OM approval', 'Finance approval',
        'Committee status', 'Recommended amount', 'Final amount',
        'Credit score', 'Score band', 'Recommendation',
        'Disbursement status', 'Officer',
        'Date requested', 'Date reviewed', 'Appraisal finished',
        'Committee decided', 'Disbursed at',
    ]
    _write_header(ws, headers)

    loans = list(qs[:5000])
    for lr in loans:
        appraisal = getattr(lr, 'appraisal', None)
        ws.append([
            _cell(lr.loan_request_id),
            _cell(lr.applicant_name),
            _cell(lr.phone_number),
            _cell(lr.branch.name if lr.branch_id else ''),
            _cell(lr.branch.district.name if lr.branch_id and lr.branch.district_id else ''),
            _cell(lr.category.name if lr.category_id else ''),
            _cell(lr.amount_requested),
            _cell(lr.status),
            'Yes' if lr.operation_manager_approval else 'No',
            'Yes' if lr.finance_approval else 'No',
            _cell(lr.get_committee_status_display() if lr.committee_status else ''),
            _cell(appraisal.amount_approved if appraisal else None),
            _cell(lr.committee_final_amount),
            _cell(appraisal.credit_score_total if appraisal else None),
            _cell(appraisal.credit_score_band if appraisal else None),
            _cell(appraisal.get_recommendation_display() if appraisal and appraisal.recommendation else ''),
            _cell(lr.get_disbursement_status_display() if lr.disbursement_status else ''),
            _cell(
                (lr.assigned_loan_officer.get_full_name() or lr.assigned_loan_officer.username)
                if lr.assigned_loan_officer_id else ''
            ),
            _cell(lr.date_requested),
            _cell(lr.date_reviewed),
            _cell(lr.appraisal_completed_at),
            _cell(lr.committee_decided_at),
            _cell(lr.disbursed_at),
        ])
    _autosize(ws)

    # Branch summary sheet
    summary = wb.create_sheet('By branch')
    _write_header(summary, [
        'Branch', 'District', 'Loans', 'Requested amount',
        'Queue approved', 'Committee approved', 'Disbursed',
    ])
    branch_rows = (
        qs.values('branch__name', 'branch__district__name')
        .annotate(
            total=Count('id'),
            amount=Sum('amount_requested'),
            queue_ok=Count('id', filter=Q(queue_approved=True)),
            committee_ok=Count('id', filter=Q(committee_status='committee_approved')),
            disbursed=Count('id', filter=Q(disbursement_status='disbursed')),
        )
        .order_by('branch__district__name', 'branch__name')
    )
    for row in branch_rows:
        summary.append([
            row['branch__name'] or 'Unassigned',
            row['branch__district__name'] or '',
            row['total'],
            float(row['amount'] or 0),
            row['queue_ok'],
            row['committee_ok'],
            row['disbursed'],
        ])
    _autosize(summary)

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio


def build_appraisal_pack_workbook(loan_request) -> BytesIO:
    """Per-loan Excel pack: summary, scorecard, conditions, schedule."""
    from loans.appraisal_pack import build_committee_appraisal_pack
    from loans.disbursement import final_annual_rate_pct, final_loan_amount, final_term_months

    pack = build_committee_appraisal_pack(loan_request)
    appraisal = pack.get('appraisal')
    basic = pack.get('basic_info')
    scorecard = pack.get('scorecard') or {}

    wb = Workbook()
    summary = wb.active
    summary.title = 'Summary'
    _write_header(summary, ['Field', 'Value'])
    rows = [
        ('Loan ID', loan_request.loan_request_id),
        ('Applicant', loan_request.applicant_name),
        ('Branch', loan_request.branch.name if loan_request.branch_id else ''),
        ('Amount requested', loan_request.amount_requested),
        ('Status', loan_request.status),
        ('Committee status', loan_request.get_committee_status_display() if loan_request.committee_status else ''),
        ('Final amount', loan_request.committee_final_amount or final_loan_amount(loan_request, appraisal)),
        ('Recommended amount', appraisal.amount_approved if appraisal else ''),
        ('Term (months)', appraisal.term_approved_months if appraisal else final_term_months(loan_request, appraisal, basic)),
        ('Rate %', appraisal.rate_approved if appraisal else final_annual_rate_pct(loan_request, appraisal, basic)),
        ('Recommendation', appraisal.get_recommendation_display() if appraisal and appraisal.recommendation else ''),
        ('Credit score', scorecard.get('total', '')),
        ('Score band', scorecard.get('band_label', '')),
        ('DSCR', getattr(appraisal, 'dscr', None) if appraisal else ''),
        ('Disbursement status', loan_request.get_disbursement_status_display() if loan_request.disbursement_status else ''),
    ]
    for label, val in rows:
        summary.append([label, _cell(val)])
    _autosize(summary)

    if scorecard.get('pillars'):
        sc = wb.create_sheet('Scorecard')
        _write_header(sc, ['Pillar', 'Earned', 'Max', 'Remark'])
        for p in scorecard['pillars']:
            sc.append([p.get('label'), p.get('earned'), p.get('max'), p.get('remark')])
        _autosize(sc)

    conditions = pack.get('conditions') or []
    if conditions:
        cd = wb.create_sheet('Conditions')
        _write_header(cd, ['Type', 'Description', 'Responsible', 'Before disbursement', 'Fulfilled'])
        for c in conditions:
            cd.append([
                c.get_condition_type_display() if hasattr(c, 'get_condition_type_display') else getattr(c, 'condition_type', ''),
                getattr(c, 'description', ''),
                getattr(c, 'responsible_party', '') or '',
                'Yes' if getattr(c, 'required_before_disbursement', False) else 'No',
                'Yes' if getattr(c, 'fulfilled', False) else 'No',
            ])
        _autosize(cd)

    amort = pack.get('amortization') or []
    if amort:
        am = wb.create_sheet('Schedule')
        _write_header(am, ['#', 'Date', 'Payment', 'Principal', 'Interest', 'Balance'])
        for row in amort:
            am.append([
                row.period_number,
                _cell(row.payment_date),
                _cell(row.payment_amount),
                _cell(row.principal),
                _cell(row.interest),
                _cell(row.balance_after),
            ])
        _autosize(am)

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio


def excel_response(bio: BytesIO, filename: str) -> HttpResponse:
    response = HttpResponse(
        bio.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def pipeline_export_filename(params: Optional[Dict[str, Any]] = None) -> str:
    stamp = timezone.now().strftime('%Y%m%d_%H%M')
    status = (params or {}).get('status') or 'all'
    safe = ''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in str(status))[:24]
    return f'loan_pipeline_{safe}_{stamp}.xlsx'


def branch_dashboard_stats(qs: QuerySet) -> Dict[str, Any]:
    total = qs.count()
    approved = qs.filter(status__iexact='Approved').count()
    pending = qs.filter(status__iexact='Pending').count()
    rejected = qs.filter(status__iexact='Rejected').count()
    committee_pending = qs.filter(committee_status='pending_committee').count()
    committee_approved = qs.filter(committee_status='committee_approved').count()
    awaiting_disbursement = qs.filter(
        committee_status='committee_approved',
    ).exclude(disbursement_status='disbursed').count()
    disbursed = qs.filter(disbursement_status='disbursed').count()
    amount = qs.aggregate(total=Sum('amount_requested'))['total'] or Decimal('0')
    final_amt = qs.filter(committee_final_amount__isnull=False).aggregate(
        total=Sum('committee_final_amount')
    )['total'] or Decimal('0')

    by_branch = list(
        qs.values('branch_id', 'branch__name', 'branch__district__name')
        .annotate(
            total=Count('id'),
            amount=Sum('amount_requested'),
            committee_ok=Count('id', filter=Q(committee_status='committee_approved')),
            disbursed=Count('id', filter=Q(disbursement_status='disbursed')),
            pending_committee=Count('id', filter=Q(committee_status='pending_committee')),
        )
        .order_by('-total')[:25]
    )
    return {
        'total': total,
        'approved': approved,
        'pending': pending,
        'rejected': rejected,
        'committee_pending': committee_pending,
        'committee_approved': committee_approved,
        'awaiting_disbursement': awaiting_disbursement,
        'disbursed': disbursed,
        'amount_requested': amount,
        'final_approved_amount': final_amt,
        'approval_rate': round((approved / total) * 100, 1) if total else 0,
        'by_branch': by_branch,
    }


def filter_choices_for_user(user) -> Dict[str, Any]:
    from loans.models import Branch, District, LoanRequest

    role = getattr(user, 'role', None)
    districts = District.objects.none()
    branches = Branch.objects.none()
    if getattr(user, 'is_superuser', False) or role in (
        'admin', 'superadmin', 'operation_manager', 'finance_manager', 'credit_committee', 'accountant',
    ):
        districts = District.objects.order_by('name')
        branches = Branch.objects.select_related('district').order_by('district__name', 'name')
    elif role == 'district_manager' and getattr(user, 'district_id', None):
        districts = District.objects.filter(pk=user.district_id)
        branches = Branch.objects.filter(district_id=user.district_id).order_by('name')
    elif role == 'branch_manager' and getattr(user, 'branch_id', None):
        branches = Branch.objects.filter(pk=user.branch_id)
        if user.branch.district_id:
            districts = District.objects.filter(pk=user.branch.district_id)

    return {
        'districts': districts,
        'branches': branches,
        'status_choices': [
            ('', 'All statuses'),
            ('Approved', 'Approved'),
            ('Pending', 'Pending'),
            ('Rejected', 'Rejected'),
        ],
        'committee_status_choices': [('', 'All committee')] + list(LoanRequest.COMMITTEE_STATUS_CHOICES),
        'disbursement_status_choices': [('', 'All disbursement')] + [
            c for c in LoanRequest.DISBURSE_STATUS_CHOICES if c[0]
        ],
        'can_pick_geo': districts.exists() or (
            getattr(user, 'is_superuser', False) or role in (
                'admin', 'superadmin', 'operation_manager', 'finance_manager',
                'credit_committee', 'accountant', 'district_manager',
            )
        ),
    }
