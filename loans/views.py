# loans/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_http_methods
from .services import fetch_customer_by_number
from django.utils import timezone
from .forms import (
    CustomUserCreationForm, CustomUserChangeForm, LoanRequestForm, AssignLoanOfficerForm, AssignEngineerForm,
    DistrictForm, BranchForm, DepartmentForm, RegionForm, ZoneForm, CityForm,
    LoanCategoryForm, CollateralTypeForm, LoanApplicationDocumentTypeForm,
    DocumentAuthenticationDefaultsForm, LoanApplicationDocumentTypeEditForm, LoanAppraisalForm,
    LoanRequestBasicInfoForm, get_credit_history_formset, get_qualitative_factors_formset,
    get_purpose_line_formset,
    get_es_checklist_formset, get_risk_mitigation_formset, get_conditions_formset,
    CollateralEstimationConfigForm,
    AppraisalSheet2Form, AppraisalSheet3Form,
    AppraisalESForm, AppraisalCollateralForm, AppraisalSummaryForm,
    CommitteeVoteForm,
    ApprovalCommitteeLevelForm, ApprovalCommitteeLevelCreateForm,
    get_approval_committee_member_rule_formset,
    ACTIVE_USER_ROLE_CHOICES,
)
from .appraisal_lock import appraisal_is_locked, get_appraisal_lock_state
from .appraisal_pack import build_committee_appraisal_pack
from .appraisal_policy import get_loan_analysis_policy
from .analysis_assist import build_analysis_assist, officer_checklist_for_mode
from .appraisal_scorecard import (
    build_credit_scorecard, evaluate_analysis_gates, persist_credit_scorecard,
)
from .appraisal_features import persist_feature_snapshot
from .qualitative_scoring import (
    DEFAULT_FACTOR_WEIGHT,
    qualitative_score_map_for_js,
    update_appraisal_qualitative_totals,
)
from .cashflow_utils import (
    payments_per_year_from_repayment_frequency,
    parse_monthly_cashflow_grid_from_post,
    seed_monthly_grid_from_averages,
)
from .sheet_requirements import get_appraisal_sheet_status, sheets_blocking_completion
from .models import (
    Region, Zone, City, District, Branch, Department, LoanCategory, CollateralType,
    LoanApplicationDocumentType, LoanRequestDocument, LoanDocumentRequest, LoanAppraisal,
    LoanRequest, CustomUser, CollateralEstimationConfig,
    LoanRequestBasicInfo, AppraisalCreditHistoryEntry, AppraisalQualitativeFactor, QUALITATIVE_FACTOR_KEYS,
    AppraisalAmortizationEntry, AppraisalESChecklistItem, ES_CHECKLIST_STRUCTURE,
    ApprovalCommitteeLevel,
)
from .committee import (
    committee_filter_branches,
    committee_filter_districts,
    committee_loan_requests_queryset,
    committee_queue_queryset,
    get_committee_tally,
    officer_can_submit_to_committee,
    return_loan_to_officer,
    start_approval_workflow,
    try_finalize_committee_decision,
    user_can_return_to_officer,
    user_can_view_committee_loan,
    user_can_vote_at_level,
    user_is_approval_participant,
)
from .collateral_config import get_collateral_estimation_mode, allows_loan_officer, allows_engineering_team
from .reporting import user_can_access_reports
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q, Count, Sum
import json
from django.http import HttpResponse
import csv
from django.contrib import messages
from loans.ids import generate_incremental_loan_request_id


def _user_is_cooperative_manager(user) -> bool:
    from loans.delegation import user_has_cooperative_authority
    return user_has_cooperative_authority(user)


def _user_is_credit_staff(user) -> bool:
    return getattr(user, 'role', None) in ('credit_head', 'credit_loan_officer')


def _user_can_configure_committees(user) -> bool:
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) in ('superadmin', 'admin', 'credit_head')


def _user_can_create_loan(user) -> bool:
    role = getattr(user, 'role', None)
    return role == 'branch_manager' or role in ('credit_head', 'credit_loan_officer')


def _user_is_finance_manager(user) -> bool:
    from loans.delegation import user_has_finance_authority
    return user_has_finance_authority(user)


def _user_can_work_appraisal(user) -> bool:
    if getattr(user, 'role', None) in ('loan_officer', 'credit_loan_officer'):
        return True
    from loans.delegation import SCOPE_APPRAISAL, principals_for
    return bool(principals_for(user, SCOPE_APPRAISAL))


def _user_can_assign_officer(user) -> bool:
    from loans.delegation import user_has_assign_officer_authority
    return user_has_assign_officer_authority(user)


def _user_can_view_loan_list(user) -> bool:
    if getattr(user, 'is_superuser', False):
        return True
    role = getattr(user, 'role', None)
    if role in (
        'branch_manager', 'loan_officer', 'credit_loan_officer', 'credit_head',
        'district_manager', 'engineer', 'engineering_head', 'superadmin', 'admin',
    ):
        return True
    from loans.delegation import (
        SCOPE_APPRAISAL,
        principals_for,
        user_has_assign_officer_authority,
    )
    if user_has_assign_officer_authority(user):
        return True
    if principals_for(user, SCOPE_APPRAISAL):
        return True
    return False


def _user_can_open_loan_detail(user) -> bool:
    if _user_can_view_loan_list(user):
        return True
    if _user_is_cooperative_manager(user) or _user_is_finance_manager(user):
        return True
    role = getattr(user, 'role', None)
    return role in (
        'cooperative_manager', 'operation_manager', 'finance_manager',
        'accountant', 'ceo', 'vp', 'vp_operations', 'vp_it', 'vp_customer_service',
        'board_member', 'risk_compliance', 'auditor',
    )


def _get_loan_for_officer(user, loan_request_id):
    """Assigned LO or appraisal-delegate covering that officer."""
    from loans.delegation import can_access_loan_as_officer, log_delegation_action

    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    ok, principal = can_access_loan_as_officer(user, loan_request)
    if not ok:
        from django.http import Http404
        raise Http404('No loan request found matching the query')
    if principal and principal.id != user.id:
        log_delegation_action(
            actor=user,
            principal=principal,
            action='appraisal_access',
            loan_request=loan_request,
            detail={'path': 'officer_loan'},
        )
    return loan_request


@login_required
@user_passes_test(lambda u: u.is_superuser)
def create_user(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('manage_users')
    else:
        form = CustomUserCreationForm()
    return render(request, 'loans/create_user.html', {'form': form})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_users(request):
    users = CustomUser.objects.all()

    # --- Search and filter handling ---
    query = request.GET.get("q")
    role = request.GET.get("role")

    if query:
        users = users.filter(
            Q(username__icontains=query) |
            Q(email__icontains=query) |
            Q(phone_number__icontains=query)
        )

    if role:
        users = users.filter(role=role)

    # Pagination
    paginator = Paginator(users, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "roles": ACTIVE_USER_ROLE_CHOICES,
        "query": query or "",
        "selected_role": role or "",
    }
    return render(request, "loans/manage_users.html", context)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def edit_user(request, user_id):
    user = get_object_or_404(CustomUser, pk=user_id)
    if request.method == 'POST':
        form = CustomUserChangeForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            return redirect('manage_users')
    else:
        form = CustomUserChangeForm(instance=user)
    return render(request, 'loans/edit_user.html', {'form': form, 'user': user})

@login_required
@user_passes_test(_user_can_create_loan)
def create_loan_request(request):
    is_credit = _user_is_credit_staff(request.user)
    if request.method == 'POST':
        form = LoanRequestForm(request.POST, credit_origin=is_credit)
        if form.is_valid():
            loan_request = form.save(commit=False)
            cn = (form.cleaned_data.get('customer_number') or '').strip()
            profile = getattr(form, '_lookup_profile', None)
            if profile is None and cn:
                profile = fetch_customer_by_number(cn)
            from loans.services.customer import attach_profile_snapshot_to_loan, customer_api_is_live
            if profile:
                attach_profile_snapshot_to_loan(loan_request, profile)
                # Form cleaned data already has name/phone from clean(); keep declared address.
                addr = (profile.get('home_address') or '').strip()
                if addr and not loan_request.declared_address_text:
                    loan_request.declared_address_text = addr[:2000]
                    loan_request.declared_address_source = 'home'
                if (profile.get('provider') or '') == 'mock_fallback':
                    messages.warning(
                        request,
                        'Live core banking lookup failed — demo mock profile was used. '
                        'Verify the customer number before proceeding.',
                    )
            elif customer_api_is_live():
                form.add_error(
                    'customer_number',
                    'Customer number not found in DECSI core banking. Check the number or register at branch CBS first.',
                )
                return render(request, 'loans/create_loan_request.html', {
                    'form': form,
                    'is_credit_origin': is_credit,
                    'customer_api_live': customer_api_is_live(),
                })

            if is_credit:
                branch = form.cleaned_data.get('branch') or request.user.branch
                if not branch:
                    messages.error(request, 'Select a branch for this head-office loan.')
                    return render(request, 'loans/create_loan_request.html', {
                        'form': form,
                        'is_credit_origin': True,
                        'customer_api_live': customer_api_is_live(),
                    })
                loan_request.branch = branch
                loan_request.district = branch.district
                loan_request.origin_level = LoanRequest.ORIGIN_HEAD_OFFICE
                loan_request.operation_manager_approval = True
                if request.user.role == 'credit_loan_officer':
                    loan_request.assigned_loan_officer = request.user
            else:
                loan_request.district = request.user.district
                loan_request.branch = request.user.branch
                loan_request.origin_level = LoanRequest.ORIGIN_BRANCH
            loan_request.loan_request_id = generate_incremental_loan_request_id()
            loan_request.save()
            try:
                from loans.compliance.case_engine import screen_loan_and_open_case
                from loans.models import ComplianceCase
                screen_loan_and_open_case(
                    loan_request,
                    opened_by=request.user,
                    source=ComplianceCase.SOURCE_NAME_SCREEN,
                )
            except Exception:
                pass
            if profile:
                msg = (
                    f'Loan request created for customer {cn} '
                    f'({profile.get("name") or loan_request.applicant_name}). '
                    'You can now add application documents.'
                )
            else:
                msg = 'Loan request created. You can now add application documents.'
            messages.success(request, msg)
            return redirect('upload_loan_request_documents', loan_request_id=loan_request.id)
    else:
        form = LoanRequestForm(credit_origin=is_credit)
    from loans.services.customer import customer_api_is_live
    return render(request, 'loans/create_loan_request.html', {
        'form': form,
        'is_credit_origin': is_credit,
        'customer_api_live': customer_api_is_live(),
    })


@login_required
@user_passes_test(_user_can_create_loan)
@require_http_methods(['GET'])
def ajax_staff_lookup_customer(request):
    """Staff hub customer-number lookup for loan registration (branch manager / credit)."""
    from django.http import JsonResponse
    from loans.services.customer import (
        compact_customer_profile,
        customer_api_is_live,
        fetch_customer_by_number,
    )

    raw = (request.GET.get('customer_number') or request.GET.get('cn') or '').strip()
    cn = ''.join(ch for ch in raw if ch.isalnum())
    if len(cn) < 4:
        return JsonResponse({'ok': False, 'error': 'Enter a valid customer number.'}, status=400)

    profile = fetch_customer_by_number(cn)
    if not profile:
        return JsonResponse({
            'ok': False,
            'error': (
                'Customer not found in DECSI core banking.'
                if customer_api_is_live()
                else 'Customer not found (mock: try 2000050041 Tekeste or 2000050042 Samrawit).'
            ),
            'live': customer_api_is_live(),
        }, status=404)

    compact = compact_customer_profile(profile)
    from loans.services.customer import profile_data_source
    src = profile_data_source(profile)
    return JsonResponse({
        'ok': True,
        'live': customer_api_is_live() and src.get('code') == 'live',
        'data_source': src,
        'message': src.get('label') or (
            'Customer loaded from core banking.' if customer_api_is_live() else 'Customer loaded (demo / mock).'
        ),
        'profile': {
            'customer_number': profile.get('customer_number') or cn,
            'name': profile.get('name') or '',
            'phone_number': profile.get('phone_number') or '',
            'home_address': profile.get('home_address') or '',
            'status': profile.get('status') or '',
            'customer_status': profile.get('customer_status') or '',
            'gender': profile.get('gender') or '',
            'date_of_birth': profile.get('date_of_birth') or '',
            'age': profile.get('age') or '',
            'marital_status': profile.get('marital_status') or '',
            'city': profile.get('city') or '',
            'branch_code': profile.get('branch_code') or '',
            'provider': profile.get('provider') or '',
            'highlights': compact,
        },
    })


@login_required
@user_passes_test(
    lambda u: (
        getattr(u, 'role', None) == 'branch_manager'
        or _user_is_credit_staff(u)
        or _user_can_work_loan_documents(u)
    )
)
def upload_loan_request_documents(request, loan_request_id):
    """Upload or view application documents for a loan request."""
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not _user_can_upload_loan_documents(request.user, loan_request):
        messages.warning(request, 'You can only manage documents for loans you cover.')
        return redirect('view_loan_requests')
    if request.user.role == 'branch_manager' and loan_request.branch_id != request.user.branch_id:
        messages.warning(request, 'You can only manage documents for loans in your branch.')
        return redirect('view_loan_requests')
    if _user_is_credit_staff(request.user) and loan_request.origin_level != LoanRequest.ORIGIN_HEAD_OFFICE:
        # Appraisal delegates / LOs may still upload when covering the loan
        if not _user_covers_loan_documents(request.user, loan_request):
            messages.warning(request, 'Credit staff can only manage head-office Credit loans.')
            return redirect('view_loan_requests')
    existing = loan_request.application_documents.select_related(
        'document_type', 'uploaded_by',
    ).order_by('-uploaded_at')
    existing_by_type = {}
    for doc in existing:
        if doc.document_type_id not in existing_by_type:
            existing_by_type[doc.document_type_id] = doc
    from .document_checklist import checklist_for_loan, checklist_type_ids
    document_checklist = checklist_for_loan(loan_request)
    allowed_type_ids = checklist_type_ids(document_checklist)
    if request.method == 'POST':
        from .services.document_auth import (
            replace_documents_for_type,
            run_automated_document_checks,
            validate_upload_bytes,
            _read_upload_bytes,
        )
        from django.core.files.base import ContentFile
        from .services.document_notifications import notify_document_uploaded

        uploaded = 0
        rejected = 0
        for key, f in request.FILES.items():
            if key.startswith('doc_type_') and f:
                try:
                    doc_type_id = int(key.replace('doc_type_', ''))
                    if doc_type_id not in allowed_type_ids:
                        rejected += 1
                        messages.error(
                            request,
                            'That document type is not part of this loan type’s checklist.',
                        )
                        continue
                    doc_type = LoanApplicationDocumentType.objects.get(pk=doc_type_id)
                except (ValueError, LoanApplicationDocumentType.DoesNotExist):
                    continue
                raw = _read_upload_bytes(f)
                if not raw:
                    rejected += 1
                    messages.error(
                        request,
                        f'{doc_type.name}: Could not read the uploaded file. Try again or use JPG/PNG.',
                    )
                    continue
                ok, errs = validate_upload_bytes(raw, f.name, doc_type, loan_request=loan_request)
                if not ok:
                    rejected += 1
                    for err in errs:
                        messages.error(request, f'{doc_type.name}: {err}')
                    continue
                replaced = replace_documents_for_type(loan_request, doc_type)
                save_file = ContentFile(raw, name=f.name)
                doc = LoanRequestDocument.objects.create(
                    loan_request=loan_request,
                    document_type=doc_type,
                    file=save_file,
                    original_filename=f.name,
                    uploaded_by=request.user,
                )
                run_automated_document_checks(doc)
                notify_document_uploaded(doc)
                try:
                    from .services.document_extraction_defaults import sync_sheet1_from_documents
                    report = sync_sheet1_from_documents(loan_request, only_empty=True)
                    filled = []
                    for d in (report.get('documents') or []):
                        filled.extend((d.get('fields') or {}).keys())
                    if filled:
                        messages.info(
                            request,
                            'Sheet 1 updated from document text: ' + ', '.join(sorted(set(filled))[:12]),
                        )
                except Exception:
                    pass
                uploaded += 1
                if replaced:
                    messages.info(request, f'"{doc_type.name}" replaced the previous upload.')
        if uploaded and rejected:
            messages.warning(
                request,
                f'{uploaded} file(s) uploaded, {rejected} rejected — see errors above.',
            )
        elif uploaded:
            messages.success(
                request,
                f'{uploaded} document(s) uploaded — automated authentication checks completed.',
            )
        elif rejected:
            messages.error(
                request,
                f'No files were uploaded ({rejected} rejected). Fix the errors above and try again.',
            )
        return redirect('upload_loan_request_documents', loan_request_id=loan_request.id)
    document_requests = loan_request.document_requests.select_related('document_type', 'requested_by').all()
    required_by_id = {i.id: i.is_required for i in document_checklist}
    existing_list = list(existing_by_type.values())
    for doc in existing_list:
        doc.checklist_required = required_by_id.get(doc.document_type_id, doc.document_type.is_required)
    return render(request, 'loans/upload_loan_request_documents.html', {
        'loan_request': loan_request,
        'document_types': document_checklist,
        'loan_category_name': getattr(loan_request.category, 'name', ''),
        'using_category_pack': bool(
            loan_request.category_id
            and loan_request.category.document_requirements.exists()
        ),
        'existing_documents': existing_list,
        'existing_by_type': existing_by_type,
        'document_requests': document_requests,
    })


@login_required
@user_passes_test(_user_is_cooperative_manager)
def update_loan_request_status(request, loan_request_id):
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if request.method == 'POST':
        was_approved = loan_request.managers_queue_approved()
        loan_request.operation_manager_approval = request.POST.get('operation_manager_approval') == 'True'
        loan_request.save()
        if loan_request.managers_queue_approved():
            messages.success(
                request,
                'Loan approved by Branch Cooperative. Branch can assign loan officer and proceed.',
            )
            if not was_approved:
                try:
                    from applicant_portal.notify import notify_applicant_loan_event
                    notify_applicant_loan_event(loan_request, event='intake')
                except Exception:
                    pass
        return redirect('view_loan_requests_operation_manager')
    return render(request, 'loans/update_loan_request_status.html', {'loan_request': loan_request})

@login_required
@user_passes_test(_user_is_cooperative_manager)
def update_operation_manager_approval(request, loan_request_id):
    """Branch Cooperative intake-queue approval (URL kept for compatibility)."""
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if loan_request.origin_level == LoanRequest.ORIGIN_HEAD_OFFICE:
        messages.info(request, 'Head-office Credit loans skip the Cooperative intake queue.')
        return redirect('view_loan_requests_operation_manager')
    if request.method == 'POST':
        was_approved = loan_request.managers_queue_approved()
        loan_request.operation_manager_approval = request.POST.get('operation_manager_approval') == 'True'
        loan_request.save()
        if loan_request.managers_queue_approved():
            messages.success(
                request,
                'Loan approved by Branch Cooperative. Status is Approved — branch can assign loan officer.',
            )
            if not was_approved:
                try:
                    from applicant_portal.notify import notify_applicant_loan_event
                    notify_applicant_loan_event(loan_request, event='intake')
                except Exception:
                    pass
        else:
            messages.success(request, 'Branch Cooperative approval saved.')
        return redirect('view_loan_requests_operation_manager')
    return render(request, 'loans/update_operation_manager_approval.html', {'loan_request': loan_request})

@login_required
@user_passes_test(_user_is_finance_manager)
def update_finance_manager_approval(request, loan_request_id):
    """Finance disbursement approval (not intake queue)."""
    from .disbursement import (
        can_approve_finance_disbursement,
        finance_ready_to_book,
        set_finance_disbursement_approval,
    )

    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    book = finance_ready_to_book(loan_request)
    if request.method == 'POST':
        approved = request.POST.get('finance_disbursement_approval') == 'True'
        if approved and not can_approve_finance_disbursement(request.user, loan_request):
            if loan_request.finance_disbursement_approval:
                messages.info(request, 'Finance disbursement already approved.')
            else:
                messages.warning(
                    request,
                    'Loan must be committee-approved and marked ready for disbursement first.',
                )
            return redirect('view_loan_requests_finance_manager')
        if approved and not book['ok']:
            messages.warning(
                request,
                'Ready-to-book checklist incomplete: ' + '; '.join(book['blockers'][:5]),
            )
            return render(request, 'loans/update_finance_manager_approval.html', {
                'loan_request': loan_request,
                'ready_to_book': book,
            })
        set_finance_disbursement_approval(loan_request, request.user, approved=approved)
        if approved:
            messages.success(
                request,
                'Finance approved disbursement. Assigned officer can confirm funds released.',
            )
        else:
            messages.success(request, 'Finance disbursement approval cleared.')
        return redirect('view_loan_requests_finance_manager')
    return render(request, 'loans/update_finance_manager_approval.html', {
        'loan_request': loan_request,
        'ready_to_book': book,
    })


def _is_assigned_officer_or_engineer(user, loan_request):
    """True if this user is the assigned loan officer or engineer for this loan."""
    if user.role in ('loan_officer', 'credit_loan_officer') and loan_request.assigned_loan_officer_id == user.id:
        return True
    if user.role == 'engineer' and loan_request.assigned_engineer_id == user.id:
        return True
    return False


def _user_covers_loan_documents(user, loan_request) -> bool:
    """Assigned LO/engineer or appraisal delegate covering the assigned officer."""
    if _is_assigned_officer_or_engineer(user, loan_request):
        return True
    from loans.delegation import can_access_loan_as_officer
    ok, _principal = can_access_loan_as_officer(user, loan_request)
    return bool(ok)


def _user_can_work_loan_documents(user) -> bool:
    """Decorator gate: native LO/engineer roles or anyone with appraisal delegation."""
    if getattr(user, 'role', None) in ('loan_officer', 'credit_loan_officer', 'engineer'):
        return True
    from loans.delegation import SCOPE_APPRAISAL, principals_for
    return bool(principals_for(user, SCOPE_APPRAISAL))


def _get_loan_for_document_worker(user, loan_request_id):
    """Loan accessible as assigned LO/engineer or appraisal delegate."""
    from django.http import Http404
    from loans.delegation import can_access_loan_as_officer, log_delegation_action

    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not _user_covers_loan_documents(user, loan_request):
        raise Http404('No loan request found matching the query')
    ok, principal = can_access_loan_as_officer(user, loan_request)
    if ok and principal and principal.id != user.id:
        log_delegation_action(
            actor=user,
            principal=principal,
            action='document_access',
            loan_request=loan_request,
            detail={'path': 'document_worker'},
        )
    return loan_request


def _user_can_upload_loan_documents(user, loan_request) -> bool:
    """BM / credit / assigned LO / appraisal delegate / assigned engineer."""
    if getattr(user, 'is_superuser', False) or getattr(user, 'role', None) in ('superadmin', 'admin'):
        return True
    if getattr(user, 'role', None) == 'branch_manager' and user.branch_id == loan_request.branch_id:
        return True
    if _user_is_credit_staff(user) and loan_request.origin_level == LoanRequest.ORIGIN_HEAD_OFFICE:
        return True
    return _user_covers_loan_documents(user, loan_request)


def _user_can_access_loan_documents(user, loan_request) -> bool:
    if getattr(user, 'is_superuser', False) or getattr(user, 'role', None) in ('superadmin', 'admin'):
        return True
    if getattr(user, 'role', None) == 'branch_manager' and user.branch_id == loan_request.branch_id:
        return True
    if _user_is_credit_staff(user) and loan_request.origin_level == LoanRequest.ORIGIN_HEAD_OFFICE:
        return True
    if _user_covers_loan_documents(user, loan_request):
        return True
    if _user_is_cooperative_manager(user) or getattr(user, 'role', None) == 'finance_manager':
        return True
    from .committee import user_can_view_committee_loan
    if user_can_view_committee_loan(user, loan_request):
        return True
    return False


def _document_access_denied_redirect(request, loan_request):
    messages.warning(request, 'You do not have access to view this document.')
    if getattr(request.user, 'role', None) == 'branch_manager':
        return redirect('upload_loan_request_documents', loan_request_id=loan_request.id)
    return redirect('loan_request_detail', loan_request_id=loan_request.id)


def _build_loan_document_file_response(doc, *, download: bool = False):
    import mimetypes
    from django.http import FileResponse, Http404

    if not doc.file_is_available():
        raise Http404('Document file not found on server.')
    name = doc.get_display_filename() or 'document'
    ext = doc.get_file_extension()
    content_type, _ = mimetypes.guess_type(name)
    if ext == 'pdf':
        content_type = 'application/pdf'
    if not content_type:
        content_type = 'application/octet-stream'
    disposition = 'attachment' if download else 'inline'
    response = FileResponse(doc.file.open('rb'), content_type=content_type)
    response['Content-Disposition'] = f'{disposition}; filename="{name}"'
    return response


@login_required
def view_loan_document(request, loan_request_id, document_id):
    """Review an uploaded document in the browser (PDF / images)."""
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not _user_can_access_loan_documents(request.user, loan_request):
        return _document_access_denied_redirect(request, loan_request)
    doc = get_object_or_404(
        LoanRequestDocument.objects.select_related('document_type'),
        pk=document_id,
        loan_request=loan_request,
    )

    if request.GET.get('raw') == '1' and doc.is_viewable_inline() and doc.file_is_available():
        return _build_loan_document_file_response(doc, download=request.GET.get('download') == '1')

    return render(request, 'loans/view_loan_document.html', {
        'loan_request': loan_request,
        'doc': doc,
        'viewable_inline': doc.is_viewable_inline(),
        'file_ext': doc.get_file_extension(),
        'file_available': doc.file_is_available(),
    })


@login_required
@xframe_options_sameorigin
def serve_loan_document_inline(request, loan_request_id, document_id):
    """Authenticated inline file response for iframe / img / embed preview."""
    from django.http import Http404

    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not _user_can_access_loan_documents(request.user, loan_request):
        raise Http404()
    doc = get_object_or_404(LoanRequestDocument, pk=document_id, loan_request=loan_request)
    return _build_loan_document_file_response(
        doc,
        download=request.GET.get('download') == '1',
    )


@login_required
@user_passes_test(_user_can_open_loan_detail)
def loan_request_detail(request, loan_request_id):
    user = request.user
    from loans.delegation import (
        can_access_loan_as_officer,
        user_can_access_loan_for_assign,
    )
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if user.role in ('loan_officer', 'credit_loan_officer'):
        ok, _ = can_access_loan_as_officer(user, loan_request)
        if not ok:
            # District LO may open district-branch files found via filter (read / pick up).
            in_district = False
            if (
                user.role == 'loan_officer'
                and getattr(user, 'district_id', None)
                and not getattr(user, 'branch_id', None)
            ):
                loan_district = loan_request.district_id or getattr(
                    loan_request.branch, 'district_id', None,
                )
                in_district = loan_district == user.district_id
            if not in_district:
                messages.warning(request, 'You do not have access to this loan request.')
                return redirect('view_loan_requests')
    elif user.role == 'engineer':
        if loan_request.assigned_engineer_id != user.id:
            messages.warning(request, 'You do not have access to this loan request.')
            return redirect('view_loan_requests')
    elif user.role not in (
        'branch_manager', 'district_manager', 'credit_head', 'admin', 'superadmin',
        'cooperative_manager', 'operation_manager', 'finance_manager',
        'ceo', 'vp', 'vp_operations', 'vp_it', 'vp_customer_service', 'board_member',
        'risk_compliance', 'auditor', 'engineering_head', 'accountant',
    ) and not getattr(user, 'is_superuser', False):
        if not (
            user_can_access_loan_for_assign(user, loan_request)
            or can_access_loan_as_officer(user, loan_request)[0]
        ):
            messages.warning(request, 'You do not have access to this loan request.')
            return redirect('home')
    elif user.role == 'accountant':
        # Accountants only open loans when covering assign_officer (or similar)
        if not user_can_access_loan_for_assign(user, loan_request):
            messages.warning(request, 'You do not have access to this loan request.')
            return redirect('home')
    collateral_mode = get_collateral_estimation_mode()
    from .document_checklist import checklist_for_loan
    document_types = checklist_for_loan(loan_request)
    _docs_qs = loan_request.application_documents.select_related(
        'document_type', 'uploaded_by', 'authenticated_by',
    ).order_by('-uploaded_at')
    application_documents = []
    _seen_types = set()
    for _doc in _docs_qs:
        if _doc.document_type_id not in _seen_types:
            _seen_types.add(_doc.document_type_id)
            application_documents.append(_doc)
    uploaded_type_ids = {_doc.document_type_id for _doc in application_documents}
    pending_document_requests = loan_request.document_requests.select_related('document_type', 'requested_by').all()
    requested_type_ids = set(pending_document_requests.values_list('document_type_id', flat=True))
    can_request_documents = _user_covers_loan_documents(user, loan_request)
    can_upload_documents = _user_can_upload_loan_documents(user, loan_request)
    document_types_missing = [dt for dt in document_types if dt.id not in uploaded_type_ids] if document_types else []
    appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    lock_state = get_appraisal_lock_state(loan_request)
    committee_submit = officer_can_submit_to_committee(loan_request) if (
        user.role == 'loan_officer' and loan_request.assigned_loan_officer_id == user.id
    ) else None
    # Appraisal delegates covering the assigned LO can also finish → committee when unlocked
    if committee_submit is None and _user_covers_loan_documents(user, loan_request):
        from loans.delegation import can_access_loan_as_officer
        ok, _ = can_access_loan_as_officer(user, loan_request)
        if ok:
            committee_submit = officer_can_submit_to_committee(loan_request)
    committee_tally = get_committee_tally(loan_request, current_user=user)
    from .services.document_auth import loan_documents_collateral_readiness

    doc_readiness = loan_documents_collateral_readiness(loan_request)
    can_authenticate_documents = _user_covers_loan_documents(user, loan_request)
    collateral_readiness = None
    collateral_totals = None
    collateral_blockers = []
    collateral_pipeline_stage_code = None
    collateral_pipeline_label = None
    if loan_request.documents_reviewed_at or loan_request.queue_approved or (loan_request.status or '').lower() == 'approved':
        from collateral.field_utils import get_loan_collateral_readiness, collateral_submit_blockers
        from collateral.pipeline import collateral_pipeline_stage, pipeline_stage_label
        from loans.services.appraisal_prefill import compute_collateral_totals

        collateral_readiness = get_loan_collateral_readiness(loan_request)
        collateral_totals = compute_collateral_totals(loan_request)
        if not collateral_readiness.get('locked'):
            collateral_blockers = collateral_submit_blockers(loan_request)
        collateral_pipeline_stage_code = collateral_pipeline_stage(loan_request)
        collateral_pipeline_label = pipeline_stage_label(collateral_pipeline_stage_code)
    coverage = None
    if collateral_readiness:
        from collateral.coverage import compute_coverage_adequacy
        coverage = compute_coverage_adequacy(loan_request)
    decision_card = None
    if appraisal:
        from .ci_decision import build_application_decision
        basic_info = getattr(loan_request, 'basic_info', None)
        decision_card = build_application_decision(loan_request, appraisal, basic_info)
    from .risk_desk import loan_risk_summary
    from loans.compliance.case_engine import open_cases_for_loan, user_can_manage_compliance_cases
    risk_summary = loan_risk_summary(loan_request)
    compliance_cases = list(open_cases_for_loan(loan_request, open_only=False)[:8])
    can_open_compliance_case = user_can_manage_compliance_cases(user)
    return render(request, 'loans/loan_request_detail.html', {
        'loan_request': loan_request,
        'collateral_estimation_mode': collateral_mode,
        'document_types': document_types,
        'application_documents': application_documents,
        'pending_document_requests': pending_document_requests,
        'can_request_documents': can_request_documents,
        'can_authenticate_documents': can_authenticate_documents,
        'can_upload_documents': can_upload_documents,
        'document_types_missing': document_types_missing,
        'requested_type_ids': requested_type_ids,
        'doc_readiness': doc_readiness,
        'collateral_readiness': collateral_readiness,
        'collateral_totals': collateral_totals,
        'collateral_blockers': collateral_blockers,
        'coverage': coverage,
        'pipeline_stage': collateral_pipeline_stage_code,
        'pipeline_label': collateral_pipeline_label,
        'appraisal': appraisal,
        'appraisal_locked': lock_state['locked'],
        'appraisal_lock_reason': lock_state['reason'],
        'appraisal_lock_code': lock_state['code'],
        'committee_submit': committee_submit,
        'committee_tally': committee_tally,
        'decision_card': decision_card,
        'risk_summary': risk_summary,
        'compliance_cases': compliance_cases,
        'can_open_compliance_case': can_open_compliance_case,
    })


@login_required
@user_passes_test(_user_can_work_loan_documents)
def request_loan_document(request, loan_request_id):
    """Assigned LO/engineer or appraisal delegate requests a document type."""
    if request.method != 'POST':
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    loan_request = _get_loan_for_document_worker(request.user, loan_request_id)
    doc_type_id = request.POST.get('document_type_id')
    if not doc_type_id:
        messages.warning(request, 'Please select a document type.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    from .document_checklist import checklist_for_loan, checklist_type_ids

    try:
        doc_type = LoanApplicationDocumentType.objects.get(pk=doc_type_id)
    except LoanApplicationDocumentType.DoesNotExist:
        messages.warning(request, 'Invalid document type.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    allowed = checklist_type_ids(checklist_for_loan(loan_request))
    if doc_type.id not in allowed:
        messages.warning(
            request,
            'That document type is not on this loan type’s checklist.',
        )
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    LoanDocumentRequest.objects.update_or_create(
        loan_request=loan_request,
        document_type=doc_type,
        defaults={'requested_by': request.user, 'requested_at': timezone.now()},
    )
    from .services.document_notifications import notify_document_requested

    notify_document_requested(loan_request, doc_type, request.user)
    messages.success(
        request,
        f'Request for "{doc_type.name}" recorded. Branch manager or covering officer can upload it.',
    )
    return redirect('loan_request_detail', loan_request_id=loan_request_id)


@login_required
@user_passes_test(_user_can_work_loan_documents)
def proceed_to_collateral(request, loan_request_id):
    """Assigned LO/engineer or appraisal delegate marks documents reviewed → collateral."""
    if request.method != 'POST':
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    loan_request = _get_loan_for_document_worker(request.user, loan_request_id)
    from .services.document_auth import loan_documents_collateral_readiness

    readiness = loan_documents_collateral_readiness(loan_request)
    if not readiness['ready']:
        if readiness['missing_required']:
            messages.error(request, f'Missing required documents: {", ".join(readiness["missing_required"])}.')
        if readiness['not_authenticated']:
            messages.error(
                request,
                f'These required documents are not verified yet: {", ".join(readiness["not_authenticated"])}.',
            )
        if readiness['rejected']:
            messages.error(request, f'Rejected documents must be replaced: {", ".join(readiness["rejected"])}.')
        if readiness['pending_review']:
            messages.error(
                request,
                f'Documents still pending review: {", ".join(readiness["pending_review"])}.',
            )
        if not any([
            readiness['missing_required'],
            readiness['not_authenticated'],
            readiness['rejected'],
            readiness['pending_review'],
        ]):
            messages.error(request, 'Document authentication requirements are not met.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    loan_request.documents_reviewed_at = timezone.now()
    loan_request.documents_reviewed_by = request.user
    loan_request.save(update_fields=['documents_reviewed_at', 'documents_reviewed_by'])
    messages.success(request, 'Documents reviewed. You can now proceed to collateral estimation.')
    return redirect('loan_request_detail', loan_request_id=loan_request_id)


@login_required
@user_passes_test(_user_can_work_loan_documents)
def authenticate_loan_document(request, loan_request_id, document_id):
    """LO / engineer / appraisal delegate: verify or reject document authenticity."""
    if request.method != 'POST':
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    loan_request = _get_loan_for_document_worker(request.user, loan_request_id)
    doc = get_object_or_404(LoanRequestDocument, pk=document_id, loan_request=loan_request)
    action = request.POST.get('auth_action', '').strip()
    notes = request.POST.get('auth_notes', '').strip()
    verdict = request.POST.get('auth_verdict', '').strip()

    from .models import LoanRequestDocument as LRD
    from .services.document_notifications import (
        notify_document_rejected,
        notify_document_verified,
        notify_document_needs_review,
        notify_document_uploaded,
    )

    if action == 'verify':
        doc.auth_status = LRD.AUTH_VERIFIED
        doc.auth_verdict = verdict or LRD.VERDICT_AUTHENTIC
        doc.auth_notes = notes
        doc.authenticated_by = request.user
        doc.authenticated_at = timezone.now()
        doc.save()
        notify_document_verified(doc, request.user)
        messages.success(request, f'"{doc.document_type.name}" marked as verified.')
    elif action == 'reject':
        doc.auth_status = LRD.AUTH_REJECTED
        doc.auth_verdict = verdict or LRD.VERDICT_NOT_AUTHENTIC
        doc.auth_notes = notes
        doc.authenticated_by = request.user
        doc.authenticated_at = timezone.now()
        doc.save()
        notify_document_rejected(doc, request.user)
        if doc.auth_verdict == LRD.VERDICT_SUSPICIOUS:
            try:
                from loans.compliance.case_engine import maybe_open_document_case
                case = maybe_open_document_case(
                    doc, suspicious=True, opened_by=request.user,
                )
                if case:
                    messages.info(request, f'Fraud case {case.case_number} opened for investigation.')
            except Exception:
                pass
        messages.warning(request, f'"{doc.document_type.name}" rejected.')
    elif action == 'requeue':
        try:
            from .services.document_auth import run_automated_document_checks
            from .services.document_extraction_defaults import sync_sheet1_from_documents
            run_automated_document_checks(doc)
            doc.refresh_from_db()
            sync_sheet1_from_documents(loan_request, only_empty=True)
            if doc.auth_status == LRD.AUTH_NEEDS_REVIEW:
                notify_document_needs_review(doc)
            else:
                notify_document_uploaded(doc)
            messages.info(
                request,
                f'Automated checks re-run for "{doc.document_type.name}" and Sheet 1 re-synced from documents.',
            )
        except Exception as exc:
            messages.error(request, f'Could not re-run checks: {exc}')
    else:
        messages.warning(request, 'Unknown action.')
    return redirect('loan_request_detail', loan_request_id=loan_request_id)


@login_required
@user_passes_test(_user_can_work_appraisal)
def loan_appraisal_steps(request):
    """Loan officers only: static clickable steps from Cashflow based MSME loan appraisal tool (V1.8.3). Presentation only."""
    return render(request, 'loans/loan_appraisal_steps.html')


def _ensure_qualitative_factors(appraisal):
    """Seed mode-specific qualitative factor rows (MSME or Corporate Sheet 2)."""
    from .appraisal_mode import ensure_appraisal_mode, qualitative_factor_keys_for_mode

    mode = ensure_appraisal_mode(appraisal, appraisal.loan_request)
    expected = qualitative_factor_keys_for_mode(mode)
    expected_keys = {k for k, _ in expected}
    # Drop factors that belong to the other mode
    appraisal.qualitative_factors.exclude(factor_key__in=expected_keys).delete()
    existing_keys = set(appraisal.qualitative_factors.values_list('factor_key', flat=True))
    for order, (key, name) in enumerate(expected):
        if key not in existing_keys:
            AppraisalQualitativeFactor.objects.create(
                appraisal=appraisal,
                factor_key=key,
                factor_name=name,
                display_order=order,
            )
        else:
            AppraisalQualitativeFactor.objects.filter(
                appraisal=appraisal, factor_key=key,
            ).update(factor_name=name, display_order=order)


def _ensure_es_checklist_items(appraisal):
    """Seed 21 E&S checklist rows from ES_CHECKLIST_STRUCTURE."""
    existing = set(appraisal.es_checklist_items.values_list('item_key', flat=True))
    order = 0
    for section_key, section_label, rows in ES_CHECKLIST_STRUCTURE:
        for item_key, question in rows:
            order += 1
            if item_key in existing:
                continue
            AppraisalESChecklistItem.objects.create(
                appraisal=appraisal,
                section_key=section_key,
                section_label=section_label,
                item_key=item_key,
                question_text=question,
                display_order=order,
            )


def _es_checklist_groups(appraisal):
    """Group checklist items for Sheet 4 template."""
    groups = []
    by_section = {}
    for item in appraisal.es_checklist_items.all().order_by('display_order', 'id'):
        by_section.setdefault(item.section_key, {
            'section_key': item.section_key,
            'section_label': item.section_label,
            'items': [],
        })
        by_section[item.section_key]['items'].append(item)
    for section_key, _label, _rows in ES_CHECKLIST_STRUCTURE:
        if section_key in by_section:
            groups.append(by_section[section_key])
    return groups


APPRAISAL_STEPS = [
    (1, 'Basic Info & loan request'),
    (2, 'Business & character assessment'),
    (3, 'Cashflow analysis'),
    (4, 'E&S assessment'),
    (5, 'Collateral worksheet'),
    (6, 'Summary & decision'),
    (7, 'Repayment schedule (optional)'),
]
TOTAL_APPRAISAL_STEPS = len(APPRAISAL_STEPS)


def _try_finish_appraisal(request, loan_request, appraisal, basic_info, policy):
    """
    Mark appraisal complete after Sheets 1–6 gates pass.
    Auto-generates Sheet 7 schedule if missing (optional pack support).
    Returns (ok: bool, error_message: str|None).
    """
    blocks, _w = evaluate_analysis_gates(appraisal, basic_info)
    if policy.require_sheets_complete_before_finish:
        status = get_appraisal_sheet_status(loan_request, appraisal, basic_info)
        sheet_blocks = sheets_blocking_completion(status, max_step=6)
        if sheet_blocks:
            return False, 'Cannot finish: ' + '; '.join(sheet_blocks[:3])
    if blocks:
        return False, 'Cannot finish while hard blocks remain: ' + '; '.join(blocks[:3])
    if not appraisal.amortization_entries.exists():
        _generate_amortization_schedule(appraisal, basic_info, loan_request)
    persist_credit_scorecard(appraisal)
    persist_feature_snapshot(loan_request, appraisal=appraisal, basic_info=basic_info)
    loan_request.appraisal_completed_at = timezone.now()
    loan_request.save(update_fields=['appraisal_completed_at'])
    return True, None


def _try_submit_to_committee(request, loan_request, notes=''):
    """Submit finished appraisal to committee. Returns (ok, error_list)."""
    check = officer_can_submit_to_committee(loan_request)
    if not check['ok']:
        return False, check['errors']
    loan_request.submitted_to_committee_at = timezone.now()
    loan_request.submitted_to_committee_by = request.user
    loan_request.committee_submission_notes = (notes or '').strip()
    loan_request.save(
        update_fields=[
            'submitted_to_committee_at',
            'submitted_to_committee_by',
            'committee_submission_notes',
        ]
    )
    start_approval_workflow(loan_request)
    return True, []


@login_required
@user_passes_test(_user_can_work_appraisal)
def loan_appraisal_edit(request, loan_request_id):
    """Redirect to step-based appraisal (step 1)."""
    return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=1)


@login_required
@user_passes_test(_user_can_work_appraisal)
def loan_appraisal_step(request, loan_request_id, step):
    """
    Page-based loan appraisal: one sheet per step (1–7).
    GET: show that step's form. POST: save and redirect to next step (or stay on error).
    """
    if step < 1 or step > TOTAL_APPRAISAL_STEPS:
        return redirect('loan_appraisal_edit', loan_request_id=loan_request_id)

    loan_request = _get_loan_for_officer(request.user, loan_request_id)
    basic_info, _ = LoanRequestBasicInfo.objects.get_or_create(loan_request=loan_request)
    from .appraisal_mode import (
        MODE_CORPORATE, ensure_appraisal_mode, is_corporate, mode_label, resolve_appraisal_mode,
    )
    category_mode = resolve_appraisal_mode(loan_request)
    appraisal, created = LoanAppraisal.objects.get_or_create(
        loan_request=loan_request,
        defaults={'created_by': request.user, 'appraisal_mode': category_mode},
    )
    if not created:
        ensure_appraisal_mode(appraisal, loan_request)
    else:
        appraisal.appraisal_mode = category_mode
        appraisal.save(update_fields=['appraisal_mode', 'updated_at'])
    _ensure_qualitative_factors(appraisal)
    _ensure_es_checklist_items(appraisal)

    CreditHistoryFormSet = get_credit_history_formset()
    QualitativeFormSet = get_qualitative_factors_formset()
    PurposeLineFormSet = get_purpose_line_formset()
    ESFormSet = get_es_checklist_formset()
    RiskFormSet = get_risk_mitigation_formset()
    CondFormSet = get_conditions_formset()
    policy = get_loan_analysis_policy()
    ppy = payments_per_year_from_repayment_frequency(basic_info.repayment_frequency)

    corp = is_corporate(loan_request, appraisal)
    steps = list(APPRAISAL_STEPS)
    if corp:
        steps[1] = (2, 'Governance & character')
        steps[2] = (3, 'Financial statements & cashflow')

    sheet_status = get_appraisal_sheet_status(loan_request, appraisal, basic_info)
    lock_state = get_appraisal_lock_state(loan_request)
    common_ctx = {
        'loan_request': loan_request,
        'appraisal': appraisal,
        'basic_info': basic_info,
        'appraisal_mode': appraisal.appraisal_mode or category_mode,
        'is_corporate': corp,
        'mode_label': mode_label(appraisal.appraisal_mode or category_mode),
        'step': step,
        'total_steps': TOTAL_APPRAISAL_STEPS,
        'steps': steps,
        'step_title': steps[step - 1][1],
        'loan_analysis_policy': policy,
        'payments_per_year': ppy,
        'sheet_status_list': sorted(sheet_status.items()),
        'current_sheet_status': sheet_status.get(step),
        'officer_checklist': officer_checklist_for_mode(appraisal.appraisal_mode or category_mode),
        'appraisal_locked': lock_state['locked'],
        'appraisal_lock_reason': lock_state['reason'],
        'appraisal_lock_code': lock_state['code'],
    }

    # Finalized appraisal / in committee / decided — read-only (POST blocked).
    if request.method == 'POST' and lock_state['locked']:
        messages.error(
            request,
            lock_state['reason'] or 'This appraisal is locked and cannot be edited.',
        )
        return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=step)

    def _step1_ctx(**extra):
        return {
            **common_ctx,
            'basic_form': extra.pop('basic_form', None) or LoanRequestBasicInfoForm(instance=basic_info),
            'purpose_formset': extra.pop('purpose_formset', None) or PurposeLineFormSet(
                instance=basic_info, prefix='purpose',
            ),
            'field_sources': dict(basic_info.field_sources or {}),
            'banking_conflicts': extra.pop('banking_conflicts', []),
            'document_conflicts': extra.pop('document_conflicts', []),
            **extra,
        }

    def _step6_context(form=None, risk_formset=None, cond_formset=None):
        from .ci_decision import build_application_decision

        card = build_credit_scorecard(appraisal)
        blocks, warnings = evaluate_analysis_gates(appraisal, basic_info)
        assist = build_analysis_assist(appraisal, basic_info)
        return {
            **common_ctx,
            'form': form or AppraisalSummaryForm(instance=appraisal),
            'risk_formset': risk_formset or RiskFormSet(instance=appraisal, prefix='risk'),
            'cond_formset': cond_formset or CondFormSet(instance=appraisal, prefix='cond'),
            'scorecard': card,
            'analysis_blocks': blocks,
            'analysis_warnings': warnings,
            'analysis_assist': assist,
            'decision_card': build_application_decision(loan_request, appraisal, basic_info),
        }

    if request.method == 'POST':
        if step == 1 and request.POST.get('banking_lookup'):
            from .services.appraisal_prefill import lookup_and_apply_banking

            cid = (request.POST.get('customer_number') or '').strip()
            banking = lookup_and_apply_banking(
                loan_request, customer_number=cid or None, only_empty=True,
            )
            loan_request.refresh_from_db()
            basic_info.refresh_from_db()
            if banking.get('error'):
                messages.warning(request, banking['error'])
            elif banking.get('applied'):
                provider = banking.get('provider') or 'banking'
                src_note = {
                    'decsi_party': 'live',
                    'mock_fallback': 'mock — live failed',
                    'mock': 'demo mock',
                }.get(provider, provider)
                messages.success(
                    request,
                    f'Core banking filled {len(banking["applied"])} field(s) ({src_note}).',
                )
                if provider == 'mock_fallback':
                    messages.warning(
                        request,
                        'Live API failed; Sheet 1 was filled from mock data. Confirm values before appraisal.',
                    )
            if banking.get('conflicts'):
                messages.info(
                    request,
                    f'{len(banking["conflicts"])} field(s) differ from core banking — review and accept below.',
                )
            elif not banking.get('error') and not banking.get('applied'):
                messages.info(request, 'Core banking profile matched; no empty fields to fill.')
            return render(request, 'loans/loan_appraisal_step1.html', _step1_ctx(
                banking_conflicts=banking.get('conflicts') or [],
                banking_profile=banking.get('profile'),
            ))

        if step == 1 and request.POST.get('accept_banking'):
            from .services.appraisal_prefill import lookup_and_apply_banking

            accept_fields = request.POST.getlist('accept_field')
            if request.POST.get('accept_all_banking'):
                accept_fields = request.POST.getlist('all_conflict_field') or accept_fields
            banking = lookup_and_apply_banking(
                loan_request,
                customer_number=(request.POST.get('customer_number') or loan_request.customer_number or None),
                only_empty=True,
                accept_fields=accept_fields,
            )
            loan_request.refresh_from_db()
            basic_info.refresh_from_db()
            n = len(banking.get('applied') or [])
            if n:
                messages.success(request, f'Accepted {n} core banking value(s).')
            else:
                messages.info(request, 'No banking fields accepted.')
            return render(request, 'loans/loan_appraisal_step1.html', _step1_ctx(
                banking_conflicts=banking.get('conflicts') or [],
                banking_profile=banking.get('profile'),
            ))

        if step == 1 and request.POST.get('import_documents'):
            from .services.appraisal_prefill import reimport_sheet1_from_documents

            prefill_report = reimport_sheet1_from_documents(loan_request, only_empty=True)
            n = prefill_report.get('total_fields', 0)
            doc_conflicts = prefill_report.get('conflicts') or []
            if n:
                messages.success(request, f'Re-imported {n} Sheet 1 field(s) from documents.')
            elif doc_conflicts:
                messages.info(
                    request,
                    f'{len(doc_conflicts)} document field(s) differ from Sheet 1 — review and accept below.',
                )
            else:
                messages.info(
                    request,
                    'No new document fields to import — existing values kept, or documents have no extractable data.',
                )
            basic_info.refresh_from_db()
            return render(request, 'loans/loan_appraisal_step1.html', _step1_ctx(
                prefill_report=prefill_report,
                document_conflicts=doc_conflicts,
            ))

        if step == 1 and request.POST.get('accept_documents'):
            from .services.appraisal_prefill import reimport_sheet1_from_documents

            accept_fields = request.POST.getlist('accept_doc_field')
            if request.POST.get('accept_all_documents'):
                accept_fields = request.POST.getlist('all_doc_conflict_field') or accept_fields
            prefill_report = reimport_sheet1_from_documents(
                loan_request, only_empty=True, accept_fields=accept_fields,
            )
            basic_info.refresh_from_db()
            n = prefill_report.get('total_fields', 0)
            if n:
                messages.success(request, f'Accepted {n} document value(s).')
            else:
                messages.info(request, 'No document fields accepted.')
            return render(request, 'loans/loan_appraisal_step1.html', _step1_ctx(
                prefill_report=prefill_report,
                document_conflicts=prefill_report.get('conflicts') or [],
            ))

        if step == 1 and request.POST.get('import_sources'):
            from .services.appraisal_prefill import sync_appraisal_from_sources

            prefill_report = sync_appraisal_from_sources(loan_request, only_empty=True)
            n = prefill_report.get('total_fields', 0)
            if n:
                messages.success(request, f'Imported {n} field(s) from banking, registration, documents, and collateral.')
            else:
                messages.info(request, 'No new fields to import — existing data kept, or sources are empty.')
            basic_info.refresh_from_db()
            appraisal.refresh_from_db()
            loan_request.refresh_from_db()
            common_ctx['loan_request'] = loan_request
            return render(request, 'loans/loan_appraisal_step1.html', _step1_ctx(
                prefill_report=prefill_report,
                banking_conflicts=prefill_report.get('conflicts') or [],
                document_conflicts=prefill_report.get('document_conflicts') or [],
                banking_profile=(prefill_report.get('banking') or {}).get('profile'),
            ))

        if step == 1:
            from .appraisal_mode import is_corporate as _is_corporate
            basic_form = LoanRequestBasicInfoForm(request.POST, instance=basic_info)
            purpose_formset = PurposeLineFormSet(request.POST, instance=basic_info, prefix='purpose')
            corp = _is_corporate(loan_request, appraisal)
            purpose_ok = True if corp else purpose_formset.is_valid()
            if basic_form.is_valid() and purpose_ok:
                basic_form.save()
                if not corp:
                    purpose_formset.save()
                messages.success(request, 'Sheet 1 saved.')
                return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=2)
            return render(request, 'loans/loan_appraisal_step1.html', _step1_ctx(
                basic_form=basic_form,
                purpose_formset=purpose_formset,
            ))

        if step == 2:
            if request.POST.get('refresh_banking'):
                from .services.banking_transactions import refresh_appraisal_banking
                if not (loan_request.customer_number or '').strip():
                    messages.warning(
                        request,
                        'Set a core banking customer number on the loan / Sheet 1 before refreshing transactions.',
                    )
                else:
                    metrics = refresh_appraisal_banking(appraisal, loan_request)
                    messages.success(
                        request,
                        f'Banking metrics refreshed ({metrics.get("provider")}: '
                        f'{metrics.get("tx_count", 0)} txs, '
                        f'avg credit {metrics.get("avg_monthly_credit")}).',
                    )
                return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=2)
            form = AppraisalSheet2Form(request.POST, instance=appraisal)
            credit_formset = CreditHistoryFormSet(request.POST, instance=appraisal, prefix='credit')
            qual_formset = QualitativeFormSet(request.POST, instance=appraisal, prefix='qual')
            if form.is_valid() and credit_formset.is_valid() and qual_formset.is_valid():
                form.save()
                credit_formset.save()
                qual_formset.save()
                total, passed = update_appraisal_qualitative_totals(appraisal)
                messages.success(
                    request,
                    f'Sheet 2 saved. Character score {total}/100 '
                    f'({"passed" if passed else "below 75% gate"}).',
                )
                return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=3)
            return render(request, 'loans/loan_appraisal_step2.html', {
                **common_ctx,
                'form': form,
                'credit_formset': credit_formset,
                'qual_formset': qual_formset,
                'qual_score_map_json': json.dumps(qualitative_score_map_for_js()),
                'qual_factor_weight': float(DEFAULT_FACTOR_WEIGHT),
                'banking_behavior': appraisal.banking_behavior or {},
            })

        if step == 3:
            form = AppraisalSheet3Form(request.POST, instance=appraisal, basic_info=basic_info)
            if form.is_valid():
                obj = form.save(commit=False)
                if request.POST.get('seed_monthly_grid'):
                    sales = obj.cf_monthly_sales or obj.monthly_business_income
                    expenses = obj.monthly_business_expenses
                    obj.monthly_cashflow_grid = seed_monthly_grid_from_averages(sales, expenses)
                    obj.save()
                    messages.success(request, '12-month grid seeded from monthly averages. Adjust seasonality then save.')
                    return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=3)
                obj.monthly_cashflow_grid = parse_monthly_cashflow_grid_from_post(request.POST)
                obj.save()
                messages.success(request, 'Sheet 3 saved (cashflow, DSCR, capacity, BS ratios, 12-month grid).')
                return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=4)
            return render(request, 'loans/loan_appraisal_step3.html', {
                **common_ctx, 'form': form,
                'monthly_grid': parse_monthly_cashflow_grid_from_post(request.POST),
            })

        if step == 4:
            form = AppraisalESForm(request.POST, instance=appraisal, officer=request.user)
            es_formset = ESFormSet(request.POST, instance=appraisal, prefix='es')
            if form.is_valid() and es_formset.is_valid():
                obj = form.save(commit=False)
                # Loan officer owns E&S screening / check / confirmation on Sheet 4
                for attr in ('es_screened_by', 'es_checked_by', 'es_approved_by'):
                    if not getattr(obj, f'{attr}_id', None):
                        setattr(obj, attr, request.user)
                if not obj.es_assessment_date:
                    obj.es_assessment_date = timezone.localdate()
                obj.save()
                es_formset.save()
                messages.success(
                    request,
                    'Sheet 4 (E&S) saved — loan officer screening complete. '
                    'Credit committee will sign on the committee pack when submitted.',
                )
                return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=5)
            return render(request, 'loans/loan_appraisal_step4.html', {
                **common_ctx,
                'form': form,
                'es_formset': es_formset,
                'es_checklist_groups': _group_es_formset(es_formset),
            })

        if step == 5:
            form = AppraisalCollateralForm(request.POST, instance=appraisal)
            if form.is_valid():
                obj = form.save(commit=False)
                ask = loan_request.amount_requested
                if obj.collateral_total_value and ask and ask > 0 and not obj.collateral_coverage_ratio:
                    from decimal import Decimal
                    obj.collateral_coverage_ratio = (
                        Decimal(str(obj.collateral_total_value)) / Decimal(str(ask))
                    ).quantize(Decimal('0.01'))
                obj.save()
                messages.success(request, 'Sheet 5 (Collateral) saved.')
                return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=6)
            return render(request, 'loans/loan_appraisal_step5.html', { **common_ctx, 'form': form })

        if step == 6:
            form = AppraisalSummaryForm(request.POST, instance=appraisal)
            risk_formset = RiskFormSet(request.POST, instance=appraisal, prefix='risk')
            cond_formset = CondFormSet(request.POST, instance=appraisal, prefix='cond')
            # Always allow saving Sheet 6 draft first. Hard blocks were previously checked
            # before save, which blocked entering recommendation/strengths/weaknesses
            # (those empty fields were themselves listed as hard blocks).
            if form.is_valid() and risk_formset.is_valid() and cond_formset.is_valid():
                obj = form.save(commit=False)
                if not obj.created_by_id:
                    obj.created_by = request.user
                obj.save()
                risk_formset.save()
                cond_formset.save()
                persist_credit_scorecard(appraisal)
                appraisal.refresh_from_db()

                finishing = bool(
                    request.POST.get('finish_and_submit') or request.POST.get('finish_appraisal')
                )
                if finishing:
                    ok, err = _try_finish_appraisal(
                        request, loan_request, appraisal, basic_info, policy,
                    )
                    if not ok:
                        messages.error(request, err)
                        return render(
                            request, 'loans/loan_appraisal_step6.html',
                            _step6_context(form=form, risk_formset=risk_formset, cond_formset=cond_formset),
                        )
                    if request.POST.get('finish_and_submit'):
                        loan_request.refresh_from_db()
                        notes = request.POST.get('committee_submission_notes', '')
                        submitted, submit_errs = _try_submit_to_committee(
                            request, loan_request, notes=notes,
                        )
                        if submitted:
                            messages.success(
                                request,
                                'Appraisal finished and submitted to the approval committee '
                                '(branch → district → head office → management as configured).',
                            )
                            return redirect('loan_request_detail', loan_request_id=loan_request_id)
                        messages.success(request, 'Appraisal finished.')
                        for e in submit_errs:
                            messages.warning(request, e)
                        return redirect('loan_request_detail', loan_request_id=loan_request_id)
                    messages.success(
                        request,
                        'Appraisal finished. Submit to the approval committee from the loan detail page '
                        '(or use “Finish & submit to committee” next time).',
                    )
                    return redirect('loan_request_detail', loan_request_id=loan_request_id)

                if request.POST.get('save_and_schedule'):
                    messages.success(
                        request,
                        'Sheet 6 saved. Optional repayment schedule — generate if needed, then return to finish.',
                    )
                    return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=7)

                messages.success(request, 'Sheet 6 saved. Credit scorecard updated.')
                return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=6)
            return render(
                request, 'loans/loan_appraisal_step6.html',
                _step6_context(form=form, risk_formset=risk_formset, cond_formset=cond_formset),
            )

        if step == 7:
            if request.POST.get('generate_schedule'):
                _generate_amortization_schedule(appraisal, basic_info, loan_request)
                messages.success(request, 'Repayment schedule generated.')
                return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=7)
            if request.POST.get('finish') or request.POST.get('finish_and_submit'):
                ok, err = _try_finish_appraisal(
                    request, loan_request, appraisal, basic_info, policy,
                )
                if not ok:
                    messages.error(request, err)
                    return redirect(
                        'loan_appraisal_step',
                        loan_request_id=loan_request_id,
                        step=6 if 'hard blocks' in (err or '').lower() else 7,
                    )
                if request.POST.get('finish_and_submit'):
                    loan_request.refresh_from_db()
                    notes = request.POST.get('committee_submission_notes', '')
                    submitted, submit_errs = _try_submit_to_committee(request, loan_request, notes=notes)
                    if submitted:
                        messages.success(
                            request,
                            'Appraisal finished and submitted to the approval committee.',
                        )
                        return redirect('loan_request_detail', loan_request_id=loan_request_id)
                    messages.success(request, 'Appraisal finished.')
                    for e in submit_errs:
                        messages.warning(request, e)
                    return redirect('loan_request_detail', loan_request_id=loan_request_id)
                messages.success(
                    request,
                    'Appraisal complete. Submit to the approval committee from the loan detail page.',
                )
                return redirect('loan_request_detail', loan_request_id=loan_request_id)
            return render(request, 'loans/loan_appraisal_step7.html', {
                **common_ctx,
                'scorecard': build_credit_scorecard(appraisal),
                'feature_snapshot': appraisal.feature_snapshot,
                'analysis_assist': build_analysis_assist(appraisal, basic_info),
            })

    # GET
    if step == 1:
        from .services.appraisal_prefill import sync_appraisal_from_sources

        prefill_report = sync_appraisal_from_sources(loan_request, only_empty=True)
        if (
            prefill_report.get('total_fields')
            or prefill_report.get('conflicts')
            or prefill_report.get('document_conflicts')
        ):
            basic_info.refresh_from_db()
            appraisal.refresh_from_db()
            loan_request.refresh_from_db()
            common_ctx['loan_request'] = loan_request
            sheet_status = get_appraisal_sheet_status(loan_request, appraisal, basic_info)
            common_ctx['sheet_status_list'] = sorted(sheet_status.items())
            common_ctx['current_sheet_status'] = sheet_status.get(step)
        return render(request, 'loans/loan_appraisal_step1.html', _step1_ctx(
            prefill_report=prefill_report,
            banking_conflicts=prefill_report.get('conflicts') or [],
            document_conflicts=prefill_report.get('document_conflicts') or [],
            banking_profile=(prefill_report.get('banking') or {}).get('profile'),
        ))
    if step == 2:
        # Keep earned scores in sync when ratings already exist (e.g. after seed / partial save).
        if appraisal.qualitative_factors.filter(rating__isnull=False).exclude(rating='').exists():
            update_appraisal_qualitative_totals(appraisal)
            appraisal.refresh_from_db()
        # Auto-pull banking metrics once when customer number exists and never refreshed.
        if (
            (loan_request.customer_number or '').strip()
            and not (appraisal.banking_behavior or {}).get('tx_count')
        ):
            try:
                from .services.banking_transactions import refresh_appraisal_banking
                refresh_appraisal_banking(appraisal, loan_request)
                appraisal.refresh_from_db()
            except Exception:
                pass
        form = AppraisalSheet2Form(instance=appraisal)
        credit_formset = CreditHistoryFormSet(instance=appraisal, prefix='credit')
        qual_formset = QualitativeFormSet(instance=appraisal, prefix='qual')
        return render(request, 'loans/loan_appraisal_step2.html', {
            **common_ctx,
            'form': form,
            'credit_formset': credit_formset,
            'qual_formset': qual_formset,
            'qual_score_map_json': json.dumps(qualitative_score_map_for_js()),
            'qual_factor_weight': float(DEFAULT_FACTOR_WEIGHT),
            'banking_behavior': appraisal.banking_behavior or {},
        })
    if step == 3:
        form = AppraisalSheet3Form(instance=appraisal, basic_info=basic_info)
        grid = appraisal.monthly_cashflow_grid or []
        if not grid:
            grid = [{'month': m, 'sales': None, 'expenses': None, 'net': None} for m in range(1, 13)]
        return render(request, 'loans/loan_appraisal_step3.html', {
            **common_ctx, 'form': form, 'monthly_grid': grid,
        })
    if step == 4:
        form = AppraisalESForm(instance=appraisal, officer=request.user)
        es_formset = ESFormSet(instance=appraisal, prefix='es')
        return render(request, 'loans/loan_appraisal_step4.html', {
            **common_ctx,
            'form': form,
            'es_formset': es_formset,
            'es_checklist_groups': _group_es_formset(es_formset),
        })
    if step == 5:
        from .services.appraisal_prefill import sync_collateral_to_appraisal

        collateral_prefill = sync_collateral_to_appraisal(loan_request, appraisal, only_empty=True)
        if collateral_prefill:
            appraisal.refresh_from_db()
        common_ctx['prefill_report'] = {'collateral': collateral_prefill}
        form = AppraisalCollateralForm(instance=appraisal)
        return render(request, 'loans/loan_appraisal_step5.html', { **common_ctx, 'form': form })
    if step == 6:
        return render(request, 'loans/loan_appraisal_step6.html', _step6_context())
    if step == 7:
        return render(request, 'loans/loan_appraisal_step7.html', {
            **common_ctx,
            'scorecard': build_credit_scorecard(appraisal),
            'feature_snapshot': appraisal.feature_snapshot,
            'analysis_assist': build_analysis_assist(appraisal, basic_info),
        })

    return redirect('loan_appraisal_edit', loan_request_id=loan_request_id)


def _group_es_formset(es_formset):
    """Attach forms to section groups for Sheet 4 template."""
    forms_by_key = {}
    for f in es_formset.forms:
        key = f.instance.item_key or f.initial.get('item_key')
        if key:
            forms_by_key[key] = f
    groups = []
    for section_key, section_label, rows in ES_CHECKLIST_STRUCTURE:
        items = []
        for item_key, _q in rows:
            if item_key in forms_by_key:
                items.append(forms_by_key[item_key])
        if items:
            groups.append({
                'section_key': section_key,
                'section_label': section_label,
                'forms': items,
            })
    return groups


def _add_months(date, months):
    """Add months to a date (stdlib only)."""
    import calendar
    month = date.month - 1 + months
    year = date.year + month // 12
    month = month % 12 + 1
    day = min(date.day, calendar.monthrange(year, month)[1])
    return date.replace(year=year, month=month, day=day)


def _generate_amortization_schedule(appraisal, basic_info, loan_request):
    """Generate amortization from final approved terms when available (else request + Sheet 1)."""
    from decimal import Decimal
    from django.utils import timezone
    from loans.disbursement import final_annual_rate_pct, final_loan_amount, final_term_months

    AppraisalAmortizationEntry.objects.filter(appraisal=appraisal).delete()
    amount = final_loan_amount(loan_request, appraisal)
    term_months = final_term_months(loan_request, appraisal, basic_info)
    annual_rate = final_annual_rate_pct(loan_request, appraisal, basic_info) / Decimal('100')
    if amount <= 0 or term_months <= 0:
        return
    n = term_months
    r = annual_rate / 12 if annual_rate else Decimal('0')
    balance = amount
    start_date = timezone.now().date()
    entries = []
    for period in range(1, n + 1):
        if r > 0:
            interest = (balance * r).quantize(Decimal('0.01'))
            remaining_periods = n - period + 1
            principal = (balance / remaining_periods).quantize(Decimal('0.01'))
            if period == n:
                principal = balance
            payment = principal + interest
        else:
            interest = Decimal('0')
            principal = (amount / n).quantize(Decimal('0.01'))
            if period == n:
                principal = balance
            payment = principal
        balance = (balance - principal).quantize(Decimal('0.01'))
        if balance < 0:
            balance = Decimal('0')
        pay_date = _add_months(start_date, period)
        entries.append(AppraisalAmortizationEntry(
            appraisal=appraisal,
            period_number=period,
            payment_date=pay_date,
            payment_amount=payment,
            principal=principal,
            interest=interest,
            balance_after=balance,
        ))
    AppraisalAmortizationEntry.objects.bulk_create(entries)


@login_required
@user_passes_test(_user_can_assign_officer)
def assign_loan_officer(request, loan_request_id):
    from loans.delegation import assign_officer_scope_user, log_delegation_action
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    scope_user = assign_officer_scope_user(request.user)
    role = scope_user.role
    if role == 'branch_manager' and loan_request.branch_id != scope_user.branch_id:
        return redirect('view_loan_requests')
    if role == 'district_manager':
        loan_district = loan_request.district_id or getattr(loan_request.branch, 'district_id', None)
        if loan_district != scope_user.district_id:
            return redirect('view_loan_requests')
    if role == 'credit_head' and loan_request.origin_level != LoanRequest.ORIGIN_HEAD_OFFICE:
        messages.warning(request, 'Credit Head assigns officers on head-office Credit loans only.')
        return redirect('view_loan_requests')
    if scope_user.id != request.user.id:
        log_delegation_action(
            actor=request.user, principal=scope_user, action='assign_officer_access',
            loan_request=loan_request,
        )
    if not loan_request.queue_approved:
        messages.warning(
            request,
            'Assign a loan officer only after Branch Cooperative has approved the loan '
            '(head-office Credit loans are auto-approved for intake).',
        )
        return redirect('loan_request_detail', loan_request_id=loan_request.id)
    if loan_request.status and loan_request.status.strip().lower() != 'approved':
        messages.warning(request, 'You can assign a loan officer only when the loan request status is Approved.')
        return redirect('loan_request_detail', loan_request_id=loan_request.id)
    form_kwargs = {
        'branch': loan_request.branch,
        'district': loan_request.district or getattr(loan_request.branch, 'district', None),
        'credit_origin': loan_request.origin_level == LoanRequest.ORIGIN_HEAD_OFFICE,
    }
    form = AssignLoanOfficerForm(**form_kwargs)
    if request.method == 'POST':
        form = AssignLoanOfficerForm(request.POST, **form_kwargs)
        if form.is_valid():
            loan_request.assigned_loan_officer = form.cleaned_data.get('assigned_loan_officer')
            loan_request.save(update_fields=['assigned_loan_officer'])
            messages.success(request, 'Assigned loan officer updated.')
            return redirect('loan_request_detail', loan_request_id=loan_request.id)
    else:
        form = AssignLoanOfficerForm(
            initial={'assigned_loan_officer': loan_request.assigned_loan_officer},
            **form_kwargs,
        )
    return render(request, 'loans/assign_loan_officer.html', {'loan_request': loan_request, 'form': form})


@login_required
@user_passes_test(lambda u: u.role in ['branch_manager', 'admin', 'superadmin'])
def send_to_engineering_head(request, loan_request_id):
    """Branch manager sends approved loan to engineering head for collateral estimation (when mode is Engineering Team)."""
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if request.user.role == 'branch_manager' and loan_request.branch_id != request.user.branch_id:
        return redirect('view_loan_requests')
    if not allows_engineering_team():
        messages.warning(request, 'Collateral estimation is not using engineering team. Change config in Admin if needed.')
        return redirect('loan_request_detail', loan_request_id=loan_request.id)
    if not loan_request.queue_approved:
        messages.warning(
            request,
            'Send to engineering only after Branch Cooperative has approved the loan.',
        )
        return redirect('loan_request_detail', loan_request_id=loan_request.id)
    if loan_request.status and loan_request.status.strip().lower() != 'approved':
        messages.warning(request, 'You can send to engineering only when the loan request status is Approved.')
        return redirect('loan_request_detail', loan_request_id=loan_request.id)
    if request.method == 'POST':
        loan_request.sent_to_engineering_at = timezone.now()
        loan_request.save(update_fields=['sent_to_engineering_at'])
        messages.success(request, 'Loan sent to engineering head for collateral estimation.')
        return redirect('loan_request_detail', loan_request_id=loan_request.id)
    return render(request, 'loans/send_to_engineering_head_confirm.html', {'loan_request': loan_request})


@login_required
@user_passes_test(lambda u: u.role in ['engineering_head', 'admin', 'superadmin'])
def loans_sent_for_collateral(request):
    """Engineering head: list loans sent for collateral (to assign engineer)."""
    if not allows_engineering_team():
        return redirect('view_loan_requests')
    qs = LoanRequest.objects.filter(
        sent_to_engineering_at__isnull=False
    ).filter(
        Q(queue_approved=True) | Q(status__iexact='Approved')
    ).select_related('branch', 'collateral', 'assigned_engineer').order_by('-sent_to_engineering_at')
    q = request.GET.get('q')
    if q:
        qs = qs.filter(
            Q(loan_request_id__icontains=q) | Q(applicant_name__icontains=q) | Q(phone_number__icontains=q)
        )
    from loans.pagination import page_querystring, paginate
    page_obj = paginate(request, qs)
    return render(request, 'loans/loans_sent_for_collateral.html', {
        'loan_requests': page_obj,
        'page_obj': page_obj,
        'query': q or '',
        'querystring': page_querystring(request),
    })


@login_required
@user_passes_test(lambda u: u.role in ['engineering_head', 'admin', 'superadmin'])
def assign_engineer(request, loan_request_id):
    """Engineering head assigns an engineer to a loan sent for collateral."""
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not loan_request.sent_to_engineering_at:
        messages.warning(request, 'This loan was not sent for collateral estimation.')
        return redirect('loan_request_detail', loan_request_id=loan_request.id)
    if not allows_engineering_team():
        messages.warning(request, 'Collateral estimation is not using engineering team.')
        return redirect('loan_request_detail', loan_request_id=loan_request.id)
    form = AssignEngineerForm()
    if request.method == 'POST':
        form = AssignEngineerForm(request.POST)
        if form.is_valid():
            loan_request.assigned_engineer = form.cleaned_data.get('assigned_engineer')
            loan_request.save(update_fields=['assigned_engineer'])
            if loan_request.assigned_engineer_id:
                from collateral.services.notifications import notify_collateral_assigned
                notify_collateral_assigned(loan_request, loan_request.assigned_engineer)
            messages.success(request, 'Assigned engineer updated.')
            return redirect('loan_request_detail', loan_request_id=loan_request.id)
    else:
        form = AssignEngineerForm(initial={'assigned_engineer': loan_request.assigned_engineer})
    return render(request, 'loans/assign_engineer.html', {'loan_request': loan_request, 'form': form})


@login_required
@user_passes_test(lambda u: u.role == 'superadmin')
def collateral_estimation_config(request):
    """Superadmin only: set who performs collateral estimation (loan officer vs engineering team)."""
    config, _ = CollateralEstimationConfig.objects.get_or_create(defaults={'mode': CollateralEstimationConfig.MODE_LOAN_OFFICER})
    if request.method == 'POST':
        form = CollateralEstimationConfigForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, 'Collateral estimation config saved.')
            return redirect('collateral_estimation_config')
    else:
        form = CollateralEstimationConfigForm(instance=config)
    return render(request, 'loans/collateral_estimation_config.html', {'form': form, 'config': config})


@login_required
@user_passes_test(_user_is_cooperative_manager)
def loan_request_detail_operation_manager(request, loan_request_id):
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    return render(request, 'loans/loan_request_detail_operation_manager.html', {'loan_request': loan_request})

@login_required
@user_passes_test(_user_is_finance_manager)
def loan_request_detail_finance(request, loan_request_id):
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    return render(request, 'loans/loan_request_detail_finance.html', {'loan_request': loan_request})
#manager
@login_required
def loan_request_detail_manager(request, loan_request_id):
    from .committee_evidence import build_committee_vote_evidence

    loan_request = get_object_or_404(
        LoanRequest.objects.select_related('branch', 'collateral', 'assigned_loan_officer'),
        pk=loan_request_id,
    )
    appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).select_related('created_by').first()
    basic_info = LoanRequestBasicInfo.objects.filter(loan_request=loan_request).first()
    committee_tally = get_committee_tally(loan_request, current_user=request.user)
    vote_form = CommitteeVoteForm()
    if appraisal and appraisal.amount_approved:
        vote_form.fields['amount_supported'].initial = appraisal.amount_approved
    can_access = (
        getattr(request.user, 'is_superuser', False)
        or request.user.role in ('superadmin', 'admin')
        or user_can_view_committee_loan(request.user, loan_request)
        or committee_tally.get('can_vote')
    )
    if not can_access:
        messages.warning(request, 'You do not have access to this approval review.')
        return redirect('view_loan_requests_manager')
    can_return = user_can_return_to_officer(request.user, loan_request)
    evidence = build_committee_vote_evidence(loan_request)
    scorecard = evidence.get('scorecard')
    if appraisal and not scorecard:
        scorecard = appraisal.scorecard_detail or build_credit_scorecard(appraisal)
    return render(request, 'loans/loan_request_detail_manager.html', {
        'loan_request': loan_request,
        'appraisal': appraisal,
        'basic_info': basic_info,
        'committee_tally': committee_tally,
        'vote_form': vote_form,
        'can_return_to_officer': can_return,
        'scorecard': scorecard,
        'evidence': evidence,
    })


@login_required
@user_passes_test(_user_can_work_appraisal)
def submit_to_committee(request, loan_request_id):
    """Loan officer submits completed appraisal package to the approval committee."""
    if request.method != 'POST':
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    loan_request = _get_loan_for_officer(request.user, loan_request_id)
    notes = request.POST.get('committee_submission_notes', '').strip()
    submitted, errors = _try_submit_to_committee(request, loan_request, notes=notes)
    if not submitted:
        for err in errors:
            messages.error(request, err)
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    messages.success(
        request,
        'Submitted to the approval committee workflow (branch → district → head office → management as configured).',
    )
    return redirect('loan_request_detail', loan_request_id=loan_request_id)


@login_required
def cast_committee_vote(request, loan_request_id):
    if request.method != 'POST':
        return redirect('loan_request_detail_manager', loan_request_id=loan_request_id)
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not user_can_view_committee_loan(request.user, loan_request):
        messages.warning(request, 'You do not have access to this loan in the approval workflow.')
        return redirect('view_loan_requests_manager')
    level = loan_request.current_approval_level
    if not level or loan_request.committee_status != LoanRequest.COMMITTEE_PENDING:
        messages.warning(request, 'This loan is not open for voting at any committee level.')
        return redirect('loan_request_detail_manager', loan_request_id=loan_request_id)

    if not user_can_vote_at_level(request.user, loan_request, level):
        messages.warning(request, 'You cannot vote on this loan at the current approval level.')
        return redirect('loan_request_detail_manager', loan_request_id=loan_request_id)

    form = CommitteeVoteForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Invalid vote — check your entries.')
        return redirect('loan_request_detail_manager', loan_request_id=loan_request_id)

    appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    amount = form.cleaned_data.get('amount_supported')
    if not amount and form.cleaned_data['vote'] == 'approve' and appraisal:
        amount = appraisal.amount_approved

    from loans.delegation import (
        find_delegation,
        log_delegation_action,
        resolve_vote_principal,
        SCOPE_COMMITTEE,
    )
    from .models import LoanCommitteeVote

    member, cast_by = resolve_vote_principal(request.user, loan_request, level)
    if not member:
        messages.warning(request, 'You cannot vote on this loan at the current approval level.')
        return redirect('loan_request_detail_manager', loan_request_id=loan_request_id)

    LoanCommitteeVote.objects.create(
        loan_request=loan_request,
        approval_level=level,
        member=member,
        cast_by=cast_by,
        vote=form.cleaned_data['vote'],
        amount_supported=amount,
        comments=form.cleaned_data.get('comments') or '',
    )
    if cast_by:
        log_delegation_action(
            actor=cast_by,
            principal=member,
            action='committee_vote',
            loan_request=loan_request,
            delegation=find_delegation(cast_by, member, SCOPE_COMMITTEE),
            detail={'vote': form.cleaned_data['vote'], 'level': level.key},
        )
        messages.info(
            request,
            f'Vote recorded for {member.get_full_name() or member.username} (you are acting by delegation).',
        )

    from .committee import get_level_tally, resolve_level_vote_decision

    finalized = try_finalize_committee_decision(loan_request)
    if finalized:
        loan_request.refresh_from_db()
        if loan_request.committee_status == LoanRequest.COMMITTEE_APPROVED:
            messages.success(request, 'Required approvals reached — loan fully approved by all committee levels.')
        elif loan_request.committee_status == LoanRequest.COMMITTEE_DECLINED:
            messages.warning(request, 'Required declines reached — loan rejected at this committee level.')
        else:
            messages.success(request, f'Level “{level.name}” complete. Advanced to the next approval committee.')
    else:
        tally = get_level_tally(loan_request, level)
        _decision, reason = resolve_level_vote_decision(loan_request, level, tally)
        if tally.get('is_tied'):
            messages.info(request, f'Your vote at {level.name} has been recorded. {reason}')
        else:
            messages.success(request, f'Your vote at {level.name} has been recorded.')
    return redirect('loan_request_detail_manager', loan_request_id=loan_request_id)


@login_required
def return_loan_to_officer_view(request, loan_request_id):
    if request.method != 'POST':
        return redirect('loan_request_detail_manager', loan_request_id=loan_request_id)
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not user_can_view_committee_loan(request.user, loan_request):
        messages.warning(request, 'You do not have access to this loan.')
        return redirect('view_loan_requests_manager')
    if not user_can_return_to_officer(request.user, loan_request):
        messages.warning(request, 'You cannot return this loan at the current stage.')
        return redirect('loan_request_detail_manager', loan_request_id=loan_request_id)
    notes = request.POST.get('return_notes', '').strip()
    if len(notes) < 10:
        messages.error(request, 'Please provide return notes (at least 10 characters) for the loan officer.')
        return redirect('loan_request_detail_manager', loan_request_id=loan_request_id)
    return_loan_to_officer(loan_request, request.user, notes)
    messages.success(request, 'Loan returned to the loan officer for corrections.')
    return redirect('loan_request_detail_manager', loan_request_id=loan_request_id)


@login_required
def committee_appraisal_pack(request, loan_request_id):
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not user_can_view_committee_loan(request.user, loan_request):
        messages.warning(request, 'You do not have access to this appraisal package.')
        return redirect('view_loan_requests_manager')
    pack = build_committee_appraisal_pack(loan_request)
    if not pack.get('appraisal'):
        messages.warning(request, 'No appraisal record found for this loan.')
        return redirect('loan_request_detail_manager', loan_request_id=loan_request_id)
    pack['auto_print'] = request.GET.get('print') == '1'
    return render(request, 'loans/committee_appraisal_pack.html', pack)


@login_required
def export_appraisal_pack_excel(request, loan_request_id):
    """Excel export of appraisal pack (summary, scorecard, conditions, schedule)."""
    from .reporting import build_appraisal_pack_workbook, excel_response

    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not _user_can_export_appraisal_pack(request.user, loan_request):
        messages.warning(request, 'You do not have access to export this appraisal pack.')
        return redirect('view_loan_requests')
    if not LoanAppraisal.objects.filter(loan_request=loan_request).exists():
        messages.warning(request, 'No appraisal record found for this loan.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    bio = build_appraisal_pack_workbook(loan_request)
    filename = f'appraisal_pack_{loan_request.loan_request_id}.xlsx'
    return excel_response(bio, filename)


@login_required
def export_appraisal_pack_pdf(request, loan_request_id):
    """Server-side PDF attachment of the appraisal pack (WeasyPrint or ReportLab)."""
    from .appraisal_pack_pdf import build_appraisal_pack_pdf, pdf_response

    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not _user_can_export_appraisal_pack(request.user, loan_request):
        messages.warning(request, 'You do not have access to export this appraisal pack.')
        return redirect('view_loan_requests')
    if not LoanAppraisal.objects.filter(loan_request=loan_request).exists():
        messages.warning(request, 'No appraisal record found for this loan.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    try:
        pdf_bytes, _engine = build_appraisal_pack_pdf(
            loan_request,
            base_url=request.build_absolute_uri('/'),
        )
    except Exception:
        messages.error(request, 'Could not generate the appraisal pack PDF.')
        return redirect('committee_appraisal_pack', loan_request_id=loan_request_id)
    filename = f'appraisal_pack_{loan_request.loan_request_id}.pdf'
    return pdf_response(pdf_bytes, filename)


def _user_can_export_appraisal_pack(user, loan_request) -> bool:
    role = getattr(user, 'role', None)
    if user_can_view_committee_loan(user, loan_request):
        return True
    if role in ('loan_officer', 'credit_loan_officer') and loan_request.assigned_loan_officer_id == user.id:
        return True
    if getattr(user, 'is_superuser', False) or role in ('admin', 'superadmin', 'credit_head'):
        return True
    if role == 'branch_manager' and user.branch_id and loan_request.branch_id == user.branch_id:
        return True
    return False


def _can_view_post_approval(user, loan_request) -> bool:
    from .disbursement import (
        can_manage_conditions, can_mark_disbursed, can_mark_ready, post_approval_queue_queryset,
    )
    if loan_request.committee_status != LoanRequest.COMMITTEE_APPROVED:
        return False
    if can_manage_conditions(user, loan_request) or can_mark_ready(user, loan_request) or can_mark_disbursed(user, loan_request):
        return True
    role = getattr(user, 'role', None)
    if role in ('risk_compliance', 'auditor') or role in CustomUser.MANAGEMENT_VP_ROLES:
        return True
    return post_approval_queue_queryset(user).filter(pk=loan_request.pk).exists()


@login_required
def post_approval_queue(request):
    """Loans awaiting conditions / schedule / disbursement after committee approve."""
    from .disbursement import post_approval_queue_queryset

    qs = post_approval_queue_queryset(request.user)
    status_filter = (request.GET.get('disbursement_status') or '').strip()
    if status_filter:
        qs = qs.filter(disbursement_status=status_filter)
    from loans.pagination import page_querystring, paginate
    page_obj = paginate(request, qs)
    return render(request, 'loans/post_approval_queue.html', {
        'loan_requests': page_obj,
        'page_obj': page_obj,
        'disbursement_status_choices': LoanRequest.DISBURSE_STATUS_CHOICES,
        'selected_status': status_filter,
        'querystring': page_querystring(request),
    })


@login_required
def loan_audit_pack_zip(request, loan_request_id):
    """Download compliance audit ZIP for a loan (docs, appraisal, votes, legal, agreement, CBS)."""
    from django.http import HttpResponse

    from loans.audit_export_pack import build_loan_audit_pack_zip, user_can_export_audit_pack
    from loans.models import SecurityAuditLog
    from loans.security import log_security_event

    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not user_can_export_audit_pack(request.user, loan_request):
        messages.warning(request, 'You do not have access to export the audit pack for this loan.')
        return redirect('view_loan_requests')

    zip_bytes, manifest = build_loan_audit_pack_zip(loan_request, exported_by=request.user)
    try:
        log_security_event(
            SecurityAuditLog.EVT_LOAN_AUDIT_PACK,
            request=request,
            user=request.user,
            username=request.user.username,
            detail={
                'loan_request_id': loan_request.loan_request_id,
                'loan_pk': loan_request.pk,
                'file_count': len(manifest.get('files_sha256') or {}),
            },
        )
    except Exception:
        pass

    filename = f'audit_pack_{loan_request.loan_request_id}.zip'
    response = HttpResponse(zip_bytes, content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Content-Length'] = str(len(zip_bytes))
    return response


@login_required
def post_approval_detail(request, loan_request_id):
    from .disbursement import (
        can_confirm_schedule, can_manage_conditions, can_mark_disbursed, can_mark_ready,
        disbursement_readiness, final_loan_amount,
    )
    from .models import AppraisalCondition, LoanRequestBasicInfo

    loan_request = get_object_or_404(
        LoanRequest.objects.select_related(
            'branch', 'assigned_loan_officer', 'appraisal', 'schedule_confirmed_by',
            'ready_for_disbursement_by', 'disbursed_by',
        ),
        pk=loan_request_id,
    )
    if not _can_view_post_approval(request.user, loan_request):
        messages.warning(request, 'You do not have access to this post-approval workspace.')
        return redirect('view_loan_requests')

    appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    basic_info = LoanRequestBasicInfo.objects.filter(loan_request=loan_request).first()
    readiness = disbursement_readiness(loan_request)
    conditions = list(appraisal.conditions.order_by('display_order', 'id')) if appraisal else []

    from .collateral_legal import closing_pack_summary
    from .disbursement import can_approve_finance_disbursement
    from .process_policy import closing_locks, requirement_on, tranches_enabled
    pack = closing_pack_summary(loan_request)
    tranches = list(loan_request.disbursement_tranches.order_by('sequence', 'id'))
    return render(request, 'loans/post_approval_detail.html', {
        'loan_request': loan_request,
        'appraisal': appraisal,
        'basic_info': basic_info,
        'readiness': readiness,
        'conditions': conditions,
        'closing_pack': pack,
        'collateral_legal': pack['legal'],
        'agreement_signing': pack['agreement'],
        'final_amount': final_loan_amount(loan_request, appraisal),
        'tranches': tranches,
        'closing_locks': closing_locks(),
        'own_contribution_required': requirement_on(loan_request, 'own_contribution_required'),
        'tranches_enabled': tranches_enabled(),
        'can_manage_conditions': can_manage_conditions(request.user, loan_request),
        'can_confirm_schedule': can_confirm_schedule(request.user, loan_request),
        'can_mark_ready': can_mark_ready(request.user, loan_request),
        'can_mark_disbursed': can_mark_disbursed(request.user, loan_request),
        'can_approve_finance_disbursement': can_approve_finance_disbursement(request.user, loan_request),
        'TYPE_CP': AppraisalCondition.TYPE_CP,
        'TYPE_COVENANT': AppraisalCondition.TYPE_COVENANT,
    })


@login_required
def post_approval_condition_toggle(request, loan_request_id, condition_id):
    from .disbursement import can_manage_conditions, set_condition_fulfilled
    from .models import AppraisalCondition

    if request.method != 'POST':
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not can_manage_conditions(request.user, loan_request):
        messages.warning(request, 'You cannot update conditions on this loan.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    condition = get_object_or_404(
        AppraisalCondition,
        pk=condition_id,
        appraisal__loan_request=loan_request,
    )
    fulfilled = request.POST.get('fulfilled') == '1'
    evidence = request.POST.get('evidence_note', '').strip()
    if fulfilled and condition.required_before_disbursement and len(evidence) < 5:
        messages.error(request, 'Add a short evidence note when marking a required condition fulfilled.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    set_condition_fulfilled(condition, request.user, fulfilled=fulfilled, evidence_note=evidence)
    messages.success(request, 'Condition updated.')
    return redirect('post_approval_detail', loan_request_id=loan_request_id)


@login_required
@require_http_methods(['POST'])
def post_approval_collateral_flags(request, loan_request_id):
    """Toggle require restriction / POA on the loan (officer / BM)."""
    from .disbursement import can_manage_conditions

    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not can_manage_conditions(request.user, loan_request):
        messages.warning(request, 'You cannot update collateral legal flags on this loan.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    loan_request.require_collateral_restriction = request.POST.get('require_collateral_restriction') == '1'
    loan_request.collateral_held_via_poa = request.POST.get('collateral_held_via_poa') == '1'
    loan_request.require_agreement_signatures = request.POST.get('require_agreement_signatures') == '1'
    loan_request.require_title_search = request.POST.get('require_title_search') == '1'
    loan_request.require_mortgage_registration = request.POST.get('require_mortgage_registration') == '1'
    loan_request.require_notary_stamp = request.POST.get('require_notary_stamp') == '1'
    loan_request.own_contribution_required = request.POST.get('own_contribution_required') == '1'
    from loans.process_policy import LOAN_TO_POLICY_FLAG, policy_forces
    for attr in LOAN_TO_POLICY_FLAG:
        if policy_forces(attr):
            setattr(loan_request, attr, True)
    loan_request.save(update_fields=[
        'require_collateral_restriction',
        'collateral_held_via_poa',
        'require_agreement_signatures',
        'require_title_search',
        'require_mortgage_registration',
        'require_notary_stamp',
        'own_contribution_required',
    ])
    messages.success(request, 'Closing requirements updated.')
    return redirect('post_approval_detail', loan_request_id=loan_request_id)


@login_required
@require_http_methods(['POST'])
def post_approval_agreement_generate(request, loan_request_id):
    from .agreement_signing import generate_loan_agreement
    from .disbursement import can_manage_conditions

    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not can_manage_conditions(request.user, loan_request):
        messages.warning(request, 'You cannot generate agreements on this loan.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    agr = generate_loan_agreement(
        loan_request,
        request.user,
        require_guarantor=request.POST.get('require_guarantor') == '1',
        require_branch_manager=request.POST.get('require_branch_manager') == '1',
    )
    messages.success(request, f'Agreement generated — ready for digital signatures ({agr.title}).')
    return redirect('post_approval_agreement_sign', loan_request_id=loan_request_id, agreement_id=agr.pk)


@login_required
def post_approval_agreement_sign(request, loan_request_id, agreement_id):
    """Signature pad page — borrower / guarantor / officer / BM draw on canvas."""
    from .agreement_signing import record_signature
    from .disbursement import can_manage_conditions
    from .models import LoanAgreement, LoanAgreementSignature

    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not _can_view_post_approval(request.user, loan_request):
        messages.warning(request, 'You do not have access to this post-approval workspace.')
        return redirect('view_loan_requests')
    agreement = get_object_or_404(
        LoanAgreement, pk=agreement_id, loan_request=loan_request,
    )
    can_sign = can_manage_conditions(request.user, loan_request)

    if request.method == 'POST':
        if not can_sign:
            messages.warning(request, 'You cannot capture signatures on this loan.')
            return redirect('post_approval_detail', loan_request_id=loan_request_id)

        if request.POST.get('send_remote_otp') == '1':
            from django.conf import settings as dj_settings
            from .remote_sign import issue_remote_sign_challenge
            try:
                challenge, code, path = issue_remote_sign_challenge(
                    agreement,
                    role=(request.POST.get('role') or '').strip(),
                    signer_name=(request.POST.get('signer_name') or '').strip(),
                    signer_phone=(request.POST.get('signer_phone') or '').strip(),
                    signer_id_number=(request.POST.get('signer_id_number') or '').strip(),
                    created_by=request.user,
                    request=request,
                )
                abs_url = request.build_absolute_uri(path)
                messages.success(
                    request,
                    f'Remote sign OTP sent to {challenge.signer_phone}. Link: {abs_url}',
                )
                if getattr(dj_settings, 'DEBUG', False):
                    messages.info(request, f'DEBUG OTP (tests only): {code}')
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect(
                'post_approval_agreement_sign',
                loan_request_id=loan_request_id,
                agreement_id=agreement.pk,
            )

        role = (request.POST.get('role') or '').strip()
        signer_name = (request.POST.get('signer_name') or '').strip()
        data_url = request.POST.get('signature_data') or ''
        # Staff roles bind to logged-in user when officer/BM signs
        signer_user = None
        if role in (
            LoanAgreementSignature.ROLE_OFFICER,
            LoanAgreementSignature.ROLE_BRANCH_MANAGER,
        ):
            signer_user = request.user
            if not signer_name:
                signer_name = (
                    getattr(request.user, 'get_full_name', lambda: '')()
                    or request.user.username
                )
        try:
            record_signature(
                agreement,
                role=role,
                signer_name=signer_name,
                data_url=data_url,
                request=request,
                signer_user=signer_user,
                typed_name=(request.POST.get('typed_name') or '').strip(),
                signer_id_number=(request.POST.get('signer_id_number') or '').strip(),
                declaration_accepted=request.POST.get('declaration_accepted') == '1',
            )
            messages.success(request, f'Signature recorded ({role}).')
        except ValueError as exc:
            messages.error(request, str(exc))
        agreement.refresh_from_db()
        if agreement.status == LoanAgreement.STATUS_SIGNED:
            messages.success(request, 'Agreement is fully signed.')
            return redirect('post_approval_detail', loan_request_id=loan_request_id)
        return redirect(
            'post_approval_agreement_sign',
            loan_request_id=loan_request_id,
            agreement_id=agreement.pk,
        )

    from .agreement_signing import signature_slots
    from .models import LoanRequestBasicInfo
    basic = LoanRequestBasicInfo.objects.filter(loan_request=loan_request).first()
    officer_name = (
        getattr(request.user, 'get_full_name', lambda: '')()
        or request.user.username
    )
    return render(request, 'loans/agreement_sign.html', {
        'loan_request': loan_request,
        'agreement': agreement,
        'signatures': list(agreement.signatures.filter(is_valid=True).order_by('signed_at')),
        'slots': signature_slots(agreement),
        'can_sign': can_sign,
        'applicant_tin': (basic.tin_number if basic else '') or '',
        'officer_name': officer_name,
        'ROLE_BORROWER': LoanAgreementSignature.ROLE_BORROWER,
        'ROLE_GUARANTOR': LoanAgreementSignature.ROLE_GUARANTOR,
        'ROLE_OFFICER': LoanAgreementSignature.ROLE_OFFICER,
        'ROLE_BRANCH_MANAGER': LoanAgreementSignature.ROLE_BRANCH_MANAGER,
        'role_choices': LoanAgreementSignature.ROLE_CHOICES,
    })


@require_http_methods(['GET', 'POST'])
def remote_agreement_sign(request, token):
    """Public (no login) remote OTP acceptance for a loan agreement."""
    from .models import LoanAgreementRemoteChallenge
    from .remote_sign import complete_remote_sign

    challenge = get_object_or_404(
        LoanAgreementRemoteChallenge.objects.select_related(
            'agreement', 'agreement__loan_request',
        ),
        token=token,
    )
    agreement = challenge.agreement
    loan_request = agreement.loan_request
    error = ''
    done = bool(challenge.consumed_at)

    if request.method == 'POST' and not done:
        try:
            complete_remote_sign(
                challenge,
                otp=request.POST.get('otp') or '',
                declaration_accepted=request.POST.get('declaration_accepted') == '1',
                request=request,
            )
            done = True
            challenge.refresh_from_db()
        except ValueError as exc:
            error = str(exc)

    return render(request, 'loans/remote_agreement_sign.html', {
        'challenge': challenge,
        'agreement': agreement,
        'loan_request': loan_request,
        'error': error,
        'done': done,
    })


@login_required
def post_approval_agreement_print(request, loan_request_id, agreement_id):
    from .agreement_signing import signature_slots
    from .models import LoanAgreement

    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not _can_view_post_approval(request.user, loan_request):
        messages.warning(request, 'You do not have access to this post-approval workspace.')
        return redirect('view_loan_requests')
    agreement = get_object_or_404(
        LoanAgreement, pk=agreement_id, loan_request=loan_request,
    )
    return render(request, 'loans/agreement_print.html', {
        'loan_request': loan_request,
        'agreement': agreement,
        'slots': signature_slots(agreement),
        'is_pdf': False,
    })


@login_required
def post_approval_agreement_pdf(request, loan_request_id, agreement_id):
    from .agreement_pdf import agreement_pdf_response
    from .models import LoanAgreement

    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not _can_view_post_approval(request.user, loan_request):
        messages.warning(request, 'You do not have access to this post-approval workspace.')
        return redirect('view_loan_requests')
    agreement = get_object_or_404(
        LoanAgreement, pk=agreement_id, loan_request=loan_request,
    )
    return agreement_pdf_response(agreement, request=request)


@login_required
@require_http_methods(['POST'])
def post_approval_collateral_legal_upload(request, loan_request_id):
    from .disbursement import can_manage_conditions
    from .models import LoanCollateralLegalDocument

    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not can_manage_conditions(request.user, loan_request):
        messages.warning(request, 'You cannot upload collateral legal documents on this loan.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)

    kind = (request.POST.get('kind') or '').strip()
    if kind not in dict(LoanCollateralLegalDocument.KIND_CHOICES):
        messages.warning(request, 'Select a valid legal document type.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)

    upload = request.FILES.get('file')
    if not upload:
        messages.warning(request, 'Attach a scan or photo of the paper.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)

    from .collateral_legal import validate_legal_upload
    payload = {
        'reference_number': (request.POST.get('reference_number') or '').strip()[:120],
        'issuing_office': (request.POST.get('issuing_office') or '').strip()[:255],
        'grantor_name': (request.POST.get('grantor_name') or '').strip()[:255],
        'attorney_name': (request.POST.get('attorney_name') or '').strip()[:255],
    }
    err = validate_legal_upload(kind, payload)
    if err:
        messages.warning(request, err)
        return redirect('post_approval_detail', loan_request_id=loan_request_id)

    def _parse_date(raw):
        raw = (raw or '').strip()
        if not raw:
            return None
        from datetime import datetime
        try:
            return datetime.strptime(raw, '%Y-%m-%d').date()
        except ValueError:
            return None

    LoanCollateralLegalDocument.objects.create(
        loan_request=loan_request,
        kind=kind,
        reference_number=payload['reference_number'],
        issuing_office=payload['issuing_office'],
        issue_date=_parse_date(request.POST.get('issue_date')),
        expiry_date=_parse_date(request.POST.get('expiry_date')),
        grantor_name=payload['grantor_name'],
        attorney_name=payload['attorney_name'],
        parcel_reference=(request.POST.get('parcel_reference') or '').strip()[:160],
        property_location=(request.POST.get('property_location') or '').strip()[:255],
        notes=(request.POST.get('notes') or '').strip(),
        file=upload,
        uploaded_by=request.user,
        status=LoanCollateralLegalDocument.STATUS_UPLOADED,
    )
    messages.success(request, 'Legal paper uploaded — pending verification.')
    return redirect('post_approval_detail', loan_request_id=loan_request_id)


@login_required
@require_http_methods(['POST'])
def post_approval_collateral_legal_verify(request, loan_request_id, doc_id):
    from .collateral_legal import verify_legal_document
    from .disbursement import can_manage_conditions
    from .legal_desk import user_can_manage_legal
    from .models import LoanCollateralLegalDocument

    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not (
        can_manage_conditions(request.user, loan_request)
        or user_can_manage_legal(request.user)
    ):
        messages.warning(request, 'You cannot verify collateral legal documents on this loan.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    doc = get_object_or_404(
        LoanCollateralLegalDocument, pk=doc_id, loan_request=loan_request,
    )
    approve = request.POST.get('approve') == '1'
    note = (request.POST.get('note') or '').strip()
    try:
        verify_legal_document(doc, request.user, approve=approve, note=note)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    messages.success(
        request,
        'Legal paper verified.' if approve else 'Legal paper rejected.',
    )
    return redirect('post_approval_detail', loan_request_id=loan_request_id)


@login_required
def post_approval_regen_schedule(request, loan_request_id):
    from .disbursement import can_confirm_schedule
    from .models import LoanRequestBasicInfo

    if request.method != 'POST':
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not can_confirm_schedule(request.user, loan_request):
        messages.warning(request, 'You cannot regenerate the schedule for this loan.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    if not appraisal:
        messages.error(request, 'No appraisal found.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    basic_info = LoanRequestBasicInfo.objects.filter(loan_request=loan_request).first()
    _generate_amortization_schedule(appraisal, basic_info, loan_request)
    loan_request.schedule_confirmed_at = None
    loan_request.schedule_confirmed_by = None
    if loan_request.disbursement_status in (
        LoanRequest.DISBURSE_SCHEDULE_CONFIRMED,
        LoanRequest.DISBURSE_READY,
    ):
        loan_request.disbursement_status = LoanRequest.DISBURSE_AWAITING_CONDITIONS
        loan_request.ready_for_disbursement_at = None
        loan_request.ready_for_disbursement_by = None
    loan_request.save(update_fields=[
        'schedule_confirmed_at', 'schedule_confirmed_by', 'disbursement_status',
        'ready_for_disbursement_at', 'ready_for_disbursement_by',
    ])
    messages.success(request, 'Repayment schedule regenerated from final approved terms. Please confirm it.')
    return redirect('post_approval_detail', loan_request_id=loan_request_id)


@login_required
def post_approval_confirm_schedule(request, loan_request_id):
    from .disbursement import can_confirm_schedule, confirm_schedule

    if request.method != 'POST':
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not can_confirm_schedule(request.user, loan_request):
        messages.warning(request, 'You cannot confirm the schedule for this loan.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    ok, errors = confirm_schedule(loan_request, request.user)
    if not ok:
        for err in errors:
            messages.error(request, err)
    else:
        messages.success(request, 'Repayment schedule confirmed.')
    return redirect('post_approval_detail', loan_request_id=loan_request_id)


@login_required
def post_approval_mark_ready(request, loan_request_id):
    from .disbursement import can_mark_ready, mark_ready_for_disbursement

    if request.method != 'POST':
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not can_mark_ready(request.user, loan_request):
        messages.warning(request, 'You cannot mark this loan ready for disbursement.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    notes = request.POST.get('disbursement_notes', '').strip()
    ok, errors = mark_ready_for_disbursement(loan_request, request.user, notes=notes)
    if not ok:
        for err in errors:
            messages.error(request, err)
    else:
        messages.success(request, 'Loan marked ready for disbursement. Accountant / ops notified.')
    return redirect('post_approval_detail', loan_request_id=loan_request_id)


@login_required
def post_approval_mark_disbursed(request, loan_request_id):
    from .disbursement import can_mark_disbursed, mark_disbursed

    if request.method != 'POST':
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not can_mark_disbursed(request.user, loan_request):
        messages.warning(request, 'You cannot mark this loan as disbursed.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    notes = request.POST.get('disbursement_notes', '').strip()
    ok, errors = mark_disbursed(loan_request, request.user, notes=notes)
    if not ok:
        for err in errors:
            messages.error(request, err)
    else:
        messages.success(request, 'Loan marked as disbursed.')
    return redirect('post_approval_detail', loan_request_id=loan_request_id)


@login_required
@require_http_methods(['POST'])
def post_approval_verify_equity(request, loan_request_id):
    from decimal import Decimal, InvalidOperation
    from .disbursement import can_manage_conditions, verify_own_contribution

    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not can_manage_conditions(request.user, loan_request):
        messages.warning(request, 'You cannot verify own-contribution on this loan.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    note = (request.POST.get('own_contribution_note') or '').strip()
    raw = request.POST.get('own_contribution_amount') or ''
    amount = None
    try:
        if raw.strip():
            amount = Decimal(raw)
    except (InvalidOperation, TypeError):
        amount = None
    verify_own_contribution(loan_request, request.user, amount=amount, note=note)
    messages.success(request, 'Own-contribution verified.')
    return redirect('post_approval_detail', loan_request_id=loan_request_id)


@login_required
@require_http_methods(['POST'])
def post_approval_add_tranche(request, loan_request_id):
    from decimal import Decimal, InvalidOperation
    from .disbursement import add_disbursement_tranche, can_manage_conditions

    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not can_manage_conditions(request.user, loan_request):
        messages.warning(request, 'You cannot add tranches on this loan.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    from loans.process_policy import tranches_enabled
    if not tranches_enabled():
        messages.warning(request, 'Staged disbursement is turned off in Settings → Process policy.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    raw = (request.POST.get('amount') or '').strip()
    try:
        amount = Decimal(raw)
    except (InvalidOperation, TypeError):
        messages.error(request, 'Enter a valid tranche amount.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    if amount <= 0:
        messages.error(request, 'Tranche amount must be greater than zero.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    note = (request.POST.get('note') or '').strip()
    add_disbursement_tranche(loan_request, amount, note=note)
    messages.success(request, 'Tranche added.')
    return redirect('post_approval_detail', loan_request_id=loan_request_id)


@login_required
def appraisal_features_json(request, loan_request_id):
    """Download appraisal_features_v1 JSON (officer assigned or committee viewer)."""
    from django.http import JsonResponse
    from .appraisal_features import build_appraisal_features

    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    role = getattr(request.user, 'role', None)
    allowed = False
    if role == 'loan_officer' and loan_request.assigned_loan_officer_id == request.user.id:
        allowed = True
    elif user_can_view_committee_loan(request.user, loan_request):
        allowed = True
    elif role in ('admin', 'superadmin'):
        allowed = True
    if not allowed:
        messages.warning(request, 'You do not have access to this appraisal feature export.')
        return redirect('view_loan_requests')

    appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    basic_info = LoanRequestBasicInfo.objects.filter(loan_request=loan_request).first()
    snap = None
    if appraisal and appraisal.feature_snapshot:
        snap = appraisal.feature_snapshot
    else:
        snap = build_appraisal_features(loan_request, appraisal=appraisal, basic_info=basic_info)
    filename = f'appraisal-features-{loan_request.loan_request_id}.json'
    response = JsonResponse(snap, json_dumps_params={'indent': 2, 'ensure_ascii': False})
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def loan_notifications_list(request):
    from .models import LoanNotification

    kind_filter = (request.GET.get('kind') or '').strip()
    notifications = LoanNotification.objects.filter(user=request.user).select_related('loan_request')
    if kind_filter:
        notifications = notifications.filter(kind=kind_filter)
    if request.method == 'POST' and request.POST.get('mark_all_read'):
        LoanNotification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        messages.success(request, 'All notifications marked as read.')
        return redirect('loan_notifications_list')
    from loans.pagination import page_querystring, paginate
    page_obj = paginate(request, notifications)
    return render(request, 'loans/loan_notifications.html', {
        'notifications': page_obj,
        'page_obj': page_obj,
        'kind_choices': LoanNotification.KIND_CHOICES,
        'selected_kind': kind_filter,
        'querystring': page_querystring(request),
    })


@login_required
def loan_notification_mark_read(request, notification_id):
    from .models import LoanNotification

    n = get_object_or_404(LoanNotification, pk=notification_id, user=request.user)
    n.is_read = True
    n.save(update_fields=['is_read'])
    if n.url:
        return redirect(n.url)
    return redirect('loan_notifications_list')


def _is_district_loan_officer(user) -> bool:
    return (
        getattr(user, 'role', None) == 'loan_officer'
        and bool(getattr(user, 'district_id', None))
        and not getattr(user, 'branch_id', None)
    )


def _loan_list_is_filter_first(user) -> bool:
    """Wide scopes: do not dump all district/HO/branch loans until a filter is applied."""
    role = getattr(user, 'role', None)
    if role in ('credit_head', 'district_manager'):
        return True
    return _is_district_loan_officer(user)


def _loan_requests_queryset_for_user(user):
    """Personal / default list scope (branch BM, assigned officer, etc.)."""
    role = getattr(user, 'role', None)
    if getattr(user, 'is_superuser', False) or role in ('superadmin', 'admin'):
        qs = LoanRequest.objects.all()
    elif role == 'credit_head':
        # Filter-first: empty until branch/district/search — see browse helper.
        qs = LoanRequest.objects.none()
    elif role == 'engineering_head':
        if allows_engineering_team():
            qs = LoanRequest.objects.filter(sent_to_engineering_at__isnull=False)
        else:
            qs = LoanRequest.objects.none()
    elif role in ('loan_officer', 'credit_loan_officer'):
        # District LO: assigned only by default (branch browse via filters).
        qs = LoanRequest.objects.filter(assigned_loan_officer=user)
    elif role == 'engineer':
        if allows_engineering_team():
            qs = LoanRequest.objects.filter(assigned_engineer=user)
        else:
            qs = LoanRequest.objects.none()
    elif role == 'branch_manager':
        if getattr(user, 'branch_id', None):
            qs = LoanRequest.objects.filter(branch=user.branch)
        elif getattr(user, 'district_id', None):
            # District-level BM without branch: filter-first browse.
            qs = LoanRequest.objects.none()
        else:
            qs = LoanRequest.objects.none()
    elif role == 'district_manager':
        qs = LoanRequest.objects.none()
    else:
        qs = LoanRequest.objects.none()

    from loans.delegation import (
        loan_visibility_q_for_assign_principals,
        officer_loan_filter_q,
    )
    extra_q = officer_loan_filter_q(user)
    assign_q = loan_visibility_q_for_assign_principals(user)
    if assign_q is not None:
        extra_q = extra_q | assign_q
    return LoanRequest.objects.filter(
        Q(pk__in=qs.values('pk')) | extra_q
    ).distinct()


def _loan_browse_queryset_for_user(user, *, branch_id=None, district_id=None):
    """
    Scope available when the user applies geo/search filters.
    District officers → their district branches; Credit head → any branch/district or HO.
    """
    role = getattr(user, 'role', None)
    qs = LoanRequest.objects.none()

    if _is_district_loan_officer(user):
        qs = LoanRequest.objects.filter(branch__district_id=user.district_id)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
    elif role == 'district_manager' and getattr(user, 'district_id', None):
        qs = LoanRequest.objects.filter(branch__district_id=user.district_id)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
    elif role == 'branch_manager' and not getattr(user, 'branch_id', None) and getattr(user, 'district_id', None):
        qs = LoanRequest.objects.filter(branch__district_id=user.district_id)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
    elif role == 'credit_head':
        if branch_id:
            qs = LoanRequest.objects.filter(branch_id=branch_id)
        elif district_id:
            qs = LoanRequest.objects.filter(
                Q(district_id=district_id) | Q(branch__district_id=district_id)
            )
        else:
            # Search-only: HO credit book
            qs = LoanRequest.objects.filter(origin_level=LoanRequest.ORIGIN_HEAD_OFFICE)
    elif getattr(user, 'is_superuser', False) or role in ('superadmin', 'admin'):
        qs = LoanRequest.objects.all()
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        elif district_id:
            qs = qs.filter(Q(district_id=district_id) | Q(branch__district_id=district_id))

    return qs


def _filter_choices_for_loan_list(user, district_id=None):
    """District/branch pickers for filter-first roles. Branches follow selected district."""
    from loans.models import Branch, District

    role = getattr(user, 'role', None)
    districts = District.objects.none()
    branches = Branch.objects.none()
    can_pick_district = False
    can_pick_branch = False

    if _is_district_loan_officer(user) or role == 'district_manager':
        districts = District.objects.filter(pk=user.district_id)
        branches = Branch.objects.filter(district_id=user.district_id).order_by('name')
        can_pick_branch = True
    elif role == 'branch_manager' and not user.branch_id and user.district_id:
        districts = District.objects.filter(pk=user.district_id)
        branches = Branch.objects.filter(district_id=user.district_id).order_by('name')
        can_pick_branch = True
    elif role == 'credit_head' or getattr(user, 'is_superuser', False) or role in ('superadmin', 'admin'):
        districts = District.objects.order_by('name')
        can_pick_district = True
        can_pick_branch = True
        if district_id:
            branches = Branch.objects.filter(district_id=district_id).order_by('name')
        else:
            # Do not list every branch until a district is chosen.
            branches = Branch.objects.none()

    return {
        'filter_districts': districts,
        'filter_branches': branches,
        'can_pick_district': can_pick_district,
        'can_pick_branch': can_pick_branch,
    }


@login_required
@user_passes_test(_user_can_view_loan_list)
def view_loan_requests(request):
    if getattr(request.user, 'role', None) == 'engineering_head' and allows_engineering_team():
        return redirect('loans_sent_for_collateral')
    if getattr(request.user, 'role', None) == 'engineer' and allows_engineering_team():
        return redirect(reverse('collateral:dashboard'))

    user = request.user
    query = (request.GET.get('q') or '').strip()
    date_requested = request.GET.get('date_requested')
    status = request.GET.get('status')
    loan_request_id = request.GET.get('loan_request_id')
    branch_id = request.GET.get('branch') or request.GET.get('branch_id')
    district_id = request.GET.get('district') or request.GET.get('district_id')

    filter_first = _loan_list_is_filter_first(user)
    has_browse_filter = bool(
        branch_id or district_id or query or loan_request_id or date_requested or status
    )

    personal = _loan_requests_queryset_for_user(user)
    if filter_first and has_browse_filter:
        browse = _loan_browse_queryset_for_user(
            user, branch_id=branch_id or None, district_id=district_id or None,
        )
        loan_requests = LoanRequest.objects.filter(
            Q(pk__in=personal.values('pk')) | Q(pk__in=browse.values('pk'))
        ).distinct()
    else:
        loan_requests = personal

    loan_requests = loan_requests.select_related(
        'branch', 'assigned_loan_officer',
    ).order_by('-date_requested', '-id')

    if query:
        loan_requests = loan_requests.filter(
            Q(applicant_name__icontains=query) |
            Q(phone_number__icontains=query) |
            Q(loan_request_id__icontains=query)
        )
    if date_requested:
        loan_requests = loan_requests.filter(date_requested__date=date_requested)
    if loan_request_id:
        loan_requests = loan_requests.filter(loan_request_id__icontains=loan_request_id)
    if status:
        loan_requests = loan_requests.filter(status__iexact=status)
    if branch_id and not filter_first:
        loan_requests = loan_requests.filter(branch_id=branch_id)
    if district_id and not filter_first:
        loan_requests = loan_requests.filter(
            Q(district_id=district_id) | Q(branch__district_id=district_id)
        )

    paginator = Paginator(loan_requests, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    filter_choices = _filter_choices_for_loan_list(user, district_id=district_id or None)

    context = {
        'page_obj': page_obj,
        'loan_requests': loan_requests,
        'query': query,
        'selected_date_requested': date_requested,
        'selected_loan_request_id': loan_request_id,
        'selected_status': status,
        'selected_branch': branch_id or '',
        'selected_district': district_id or '',
        'collateral_estimation_mode': get_collateral_estimation_mode(),
        'loan_list_filter_first': filter_first,
        'loan_list_needs_filter': filter_first and not has_browse_filter,
        **filter_choices,
    }
    return render(request, 'loans/view_loan_requests.html', context)


@login_required
@user_passes_test(lambda u: getattr(u, 'is_superuser', False) or u.role in ['branch_manager', 'loan_officer', 'credit_loan_officer', 'credit_head', 'district_manager', 'superadmin', 'admin'])
def filter_loan_requests(request):
    loan_requests = _loan_requests_queryset_for_user(request.user)

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if start_date and end_date:
        loan_requests = loan_requests.filter(date_requested__range=[start_date, end_date])

    return render(request, 'loans/view_loan_requests.html', {'loan_requests': loan_requests})

@login_required
# @user_passes_test(lambda u: u.role in ['branch_manager', 'operation_manager', 'finance_manager', 'credit_committee', 'loan_officer'])
def load_branches_op(request):
    district_id = request.GET.get('district')
    user = request.user

    branches = Branch.objects.filter(district_id=district_id, district=user.district) if district_id else Branch.objects.none()
    branch_list = [{"id": branch.id, "name": branch.name} for branch in branches]
    return JsonResponse(branch_list, safe=False)

@login_required
@user_passes_test(_user_is_cooperative_manager)
def view_loan_requests_operation_manager(request):
    user = request.user  # Fetch the logged-in user
    district_id = request.GET.get('district')
    branch_id = request.GET.get('branch')
    date_requested = request.GET.get('date_requested')
    loan_request_id = request.GET.get('loan_request_id')
    status = request.GET.get('status')

    # Branch-originated loans only (HO Credit skips Cooperative intake).
    loan_requests = LoanRequest.objects.filter(
        origin_level=LoanRequest.ORIGIN_BRANCH,
    ).order_by('-date_requested', '-id')
    query = request.GET.get("q")
    if query:
        loan_requests = loan_requests.filter(
            Q(applicant_name__icontains=query) |
            Q(phone_number__icontains=query) |
            Q(loan_request_id__icontains=query)
        )
    if district_id:
        loan_requests = loan_requests.filter(district_id=district_id)
    if branch_id:
        loan_requests = loan_requests.filter(branch_id=branch_id)
    if date_requested:
        loan_requests = loan_requests.filter(date_requested__date=date_requested)
    if loan_request_id:
        loan_requests = loan_requests.filter(loan_request_id__icontains=loan_request_id)
    if status:
        loan_requests = loan_requests.filter(status__iexact=status)
    show = request.GET.get('show') or 'pending'
    if show == 'pending':
        loan_requests = loan_requests.filter(operation_manager_approval=False).exclude(
            status__iexact='Rejected',
        )
    elif show == 'approved':
        loan_requests = loan_requests.filter(operation_manager_approval=True)
    paginator = Paginator(loan_requests, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    from .cooperative_performance import annotate_intake_aging
    annotate_intake_aging(list(page_obj.object_list))
    districts = District.objects.all()
    branches = Branch.objects.filter(district_id=district_id) if district_id else Branch.objects.none()
    context = {
        'page_obj': page_obj,
        'loan_requests': loan_requests,
        "query": query or "",
        'districts': districts,
        'branches': branches,
        'selected_district': district_id,
        'selected_branch': branch_id,
        'selected_date_requested': date_requested,
        'selected_loan_request_id': loan_request_id,
        'selected_status': status,
        'selected_show': show,
    }
    return render(request, 'loans/view_loan_requests_operation_manager.html', context)


@login_required
@user_passes_test(_user_is_finance_manager)
def view_loan_requests_finance_manager(request):
    """Finance disbursement approval queue (not intake)."""
    from .disbursement import finance_disbursement_queue_queryset

    query = request.GET.get("q")
    district_id = request.GET.get('district')
    branch_id = request.GET.get('branch')
    date_requested = request.GET.get('date_requested')
    loan_request_id = request.GET.get('loan_request_id')
    show = request.GET.get('show') or 'pending'

    if show == 'all_ready':
        loan_requests = LoanRequest.objects.filter(
            committee_status=LoanRequest.COMMITTEE_APPROVED,
            disbursement_status=LoanRequest.DISBURSE_READY,
        )
    else:
        loan_requests = finance_disbursement_queue_queryset(request.user)

    if district_id:
        loan_requests = loan_requests.filter(district_id=district_id)
    if branch_id:
        loan_requests = loan_requests.filter(branch_id=branch_id)
    if date_requested:
        loan_requests = loan_requests.filter(date_requested__date=date_requested)
    if loan_request_id:
        loan_requests = loan_requests.filter(loan_request_id__icontains=loan_request_id)
    if query:
        loan_requests = loan_requests.filter(
            Q(applicant_name__icontains=query) |
            Q(phone_number__icontains=query) |
            Q(loan_request_id__icontains=query)
        )
    loan_requests = loan_requests.select_related('branch', 'assigned_loan_officer').order_by(
        '-ready_for_disbursement_at', '-id'
        )
    paginator = Paginator(loan_requests, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    districts = District.objects.all()
    branches = Branch.objects.filter(district_id=district_id) if district_id else Branch.objects.none()
    context = {
        'page_obj': page_obj,
        'loan_requests': loan_requests,
        'districts': districts,
        'branches': branches,
        'selected_district': district_id,
        'selected_branch': branch_id,
        'selected_date_requested': date_requested,
        'selected_loan_request_id': loan_request_id,
        'selected_status': '',
        'show': show,
        "query": query or "",
        'finance_disbursement_queue': True,
    }
    return render(request, 'loans/view_loan_requests_finance_manager.html', context)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_districts(request):
    districts = District.objects.all().order_by('name')
    if request.method == 'POST':
        form = DistrictForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('manage_districts')
    else:
        form = DistrictForm()
    from loans.pagination import page_querystring, paginate
    page_obj = paginate(request, districts)
    return render(request, 'loans/manage_districts.html', {
        'districts': page_obj,
        'page_obj': page_obj,
        'form': form,
        'querystring': page_querystring(request),
    })


@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_departments(request):
    departments = Department.objects.all().order_by('sort_order', 'name')
    if request.method == 'POST':
        form = DepartmentForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Department saved.')
            return redirect('manage_departments')
    else:
        form = DepartmentForm()
    from loans.pagination import page_querystring, paginate
    page_obj = paginate(request, departments)
    return render(request, 'loans/manage_departments.html', {
        'departments': page_obj,
        'page_obj': page_obj,
        'form': form,
        'querystring': page_querystring(request),
    })


@login_required
@user_passes_test(lambda u: u.is_superuser)
def edit_department(request, department_id):
    department = get_object_or_404(Department, pk=department_id)
    if request.method == 'POST':
        form = DepartmentForm(request.POST, instance=department)
        if form.is_valid():
            form.save()
            messages.success(request, 'Department updated.')
            return redirect('manage_departments')
    else:
        form = DepartmentForm(instance=department)
    return render(request, 'loans/edit_department.html', {
        'form': form,
        'department': department,
    })


@login_required
def view_loan_requests_manager(request):
    from urllib.parse import urlencode

    from loans.nav import user_can_access_committee_queues

    if not user_can_access_committee_queues(request.user):
        messages.warning(request, 'Committee approval queues are not part of your role.')
        return redirect('home')

    district_id = request.GET.get('district')
    branch_id = request.GET.get('branch')
    date_requested = request.GET.get('date_requested')
    loan_request_id = request.GET.get('loan_request_id')
    status = request.GET.get('status')
    committee_status = request.GET.get('committee_status')
    queue = request.GET.get('queue')
    # Always use the voter queue for non-admins — avoid a second “committee loans” list.
    if (
        queue == 'my_votes'
        or not (
            getattr(request.user, 'is_superuser', False)
            or request.user.role in ('superadmin', 'admin')
        )
    ):
        loan_requests = committee_queue_queryset(request.user)
        queue = 'my_votes'
    else:
        loan_requests = LoanRequest.objects.filter(
            ~Q(committee_status='') & ~Q(committee_status__isnull=True)
        )
    loan_requests = loan_requests.select_related(
        'branch', 'current_approval_level', 'appraisal',
    )
    query = request.GET.get("q")
    if query:
        loan_requests = loan_requests.filter(
            Q(applicant_name__icontains=query) |
            Q(phone_number__icontains=query) |
            Q(loan_request_id__icontains=query)
        )
    if district_id:
        loan_requests = loan_requests.filter(district_id=district_id)
    if branch_id:
        loan_requests = loan_requests.filter(branch_id=branch_id)
    if date_requested:
        loan_requests = loan_requests.filter(date_requested__date=date_requested)
    if loan_request_id:
        loan_requests = loan_requests.filter(loan_request_id__icontains=loan_request_id)
    if status:
        loan_requests = loan_requests.filter(status__iexact=status)
    if committee_status:
        loan_requests = loan_requests.filter(committee_status=committee_status)
    paginator = Paginator(loan_requests, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    districts = committee_filter_districts(request.user)
    branches = committee_filter_branches(request.user, district_id)
    scope_limited = not (
        getattr(request.user, 'is_superuser', False)
        or request.user.role in ('superadmin', 'admin')
    )
    list_params = request.GET.copy()
    list_params.pop('page', None)
    context = {
        'page_obj': page_obj,
        'loan_requests': loan_requests,
        "query": query or "",
        'districts': districts,
        'branches': branches,
        'selected_district': district_id,
        'selected_branch': branch_id,
        'selected_date_requested': date_requested,
        'selected_loan_request_id': loan_request_id,
        'selected_status': status,
        'selected_committee_status': committee_status,
        'committee_status_choices': LoanRequest.COMMITTEE_STATUS_CHOICES,
        'queue_my_votes': queue == 'my_votes',
        'is_participant': user_is_approval_participant(request.user),
        'scope_limited': scope_limited,
        'list_query': urlencode(list_params, doseq=True),
    }
    return render(request, 'loans/view_loan_requests_manager.html', context)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def edit_district(request, district_id):
    district = get_object_or_404(District, pk=district_id)
    if request.method == 'POST':
        form = DistrictForm(request.POST, instance=district)
        if form.is_valid():
            form.save()
            return redirect('manage_districts')
    else:
        form = DistrictForm(instance=district)
    return render(request, 'loans/edit_district.html', {'form': form, 'district': district})


@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_regions(request):
    regions = Region.objects.all()
    if request.method == 'POST':
        form = RegionForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('manage_regions')
    else:
        form = RegionForm()
    return render(request, 'loans/manage_regions.html', {'regions': regions, 'form': form})


@login_required
@user_passes_test(lambda u: u.is_superuser)
def edit_region(request, region_id):
    region = get_object_or_404(Region, pk=region_id)
    if request.method == 'POST':
        form = RegionForm(request.POST, instance=region)
        if form.is_valid():
            form.save()
            return redirect('manage_regions')
    else:
        form = RegionForm(instance=region)
    return render(request, 'loans/edit_region.html', {'form': form, 'region': region})


@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_geo_zones(request):
    zones = Zone.objects.select_related('region').all()
    if request.method == 'POST':
        form = ZoneForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('manage_geo_zones')
    else:
        form = ZoneForm()
    return render(request, 'loans/manage_geo_zones.html', {'zones': zones, 'form': form})


@login_required
@user_passes_test(lambda u: u.is_superuser)
def edit_geo_zone(request, zone_id):
    zone = get_object_or_404(Zone, pk=zone_id)
    if request.method == 'POST':
        form = ZoneForm(request.POST, instance=zone)
        if form.is_valid():
            form.save()
            return redirect('manage_geo_zones')
    else:
        form = ZoneForm(instance=zone)
    return render(request, 'loans/edit_geo_zone.html', {'form': form, 'zone': zone})


@login_required
def load_zones_by_region(request):
    """AJAX: return zones for a region (for Region → Zone → City cascade)."""
    region_id = request.GET.get('region_id')
    zones = Zone.objects.filter(region_id=region_id).order_by('name') if region_id else []
    return JsonResponse(list(zones.values('id', 'name')), safe=False)


@login_required
def load_cities_by_zone(request):
    """AJAX: return cities (woredas) for a zone (for Region → Zone → City cascade)."""
    zone_id = request.GET.get('zone_id')
    cities = City.objects.filter(zone_id=zone_id).order_by('name') if zone_id else []
    return JsonResponse(list(cities.values('id', 'name')), safe=False)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_cities(request):
    cities = City.objects.select_related('zone', 'zone__region').all()
    if request.method == 'POST':
        form = CityForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('manage_cities')
    else:
        form = CityForm()
        form.fields['zone'].queryset = Zone.objects.none()
    regions = Region.objects.all().order_by('name')
    return render(request, 'loans/manage_cities.html', {'cities': cities, 'form': form, 'regions': regions})


@login_required
@user_passes_test(lambda u: u.is_superuser)
def edit_city(request, city_id):
    city = get_object_or_404(City, pk=city_id)
    if request.method == 'POST':
        form = CityForm(request.POST, instance=city)
        if form.is_valid():
            form.save()
            return redirect('manage_cities')
    else:
        form = CityForm(instance=city)
        form.fields['zone'].queryset = Zone.objects.filter(region=city.zone.region).order_by('name')
    regions = Region.objects.all().order_by('name')
    return render(request, 'loans/edit_city.html', {'form': form, 'city': city, 'regions': regions})


@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_branches(request):
    branches = Branch.objects.select_related('district').all()
    
    paginator = Paginator(branches, 10)  # Show 10 branches per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    if request.method == 'POST':
        form = BranchForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('manage_branches')
    else:
        form = BranchForm()

    context = {
        'form': form,
        'page_obj': page_obj
    }
    return render(request, 'loans/manage_branches.html', context)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def edit_branch(request, branch_id):
    branch = get_object_or_404(Branch, pk=branch_id)
    if request.method == 'POST':
        form = BranchForm(request.POST, instance=branch)
        if form.is_valid():
            form.save()
            return redirect('manage_branches')
    else:
        form = BranchForm(instance=branch)
    return render(request, 'loans/edit_branch.html', {'form': form, 'branch': branch})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_loan_categories(request):
    categories = LoanCategory.objects.all()
    
    paginator = Paginator(categories, 10)  # Show 10 branches per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    if request.method == 'POST':
        form = LoanCategoryForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('manage_loan_categories')
    else:
        form = LoanCategoryForm()
        
    context = {
        'form': form,
        'page_obj': page_obj
    }   
    return render(request, 'loans/manage_loan_categories.html', context)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_loan_category_documents(request, category_id):
    """Configure which document types apply to a loan category (loan type)."""
    category = get_object_or_404(LoanCategory, pk=category_id)
    from .models import LoanCategoryDocumentRequirement
    from .document_checklist import ensure_default_requirements_for_category

    if request.method == 'POST':
        action = (request.POST.get('action') or 'save').strip()
        if action == 'seed_defaults':
            n = ensure_default_requirements_for_category(category)
            messages.success(
                request,
                f'Added {n} document type(s) from the global catalog (or pack was already set).',
            )
            return redirect('manage_loan_category_documents', category_id=category.id)

        # Full replace of pack from posted type ids
        selected = request.POST.getlist('document_type_id')
        required_ids = set(request.POST.getlist('is_required'))
        order_map = {}
        for key, val in request.POST.items():
            if key.startswith('order_'):
                try:
                    tid = int(key.replace('order_', '', 1))
                    order_map[tid] = int(val or 0)
                except (ValueError, TypeError):
                    continue

        LoanCategoryDocumentRequirement.objects.filter(category=category).delete()
        created = 0
        for raw_id in selected:
            try:
                tid = int(raw_id)
            except (TypeError, ValueError):
                continue
            if not LoanApplicationDocumentType.objects.filter(pk=tid).exists():
                continue
            LoanCategoryDocumentRequirement.objects.create(
                category=category,
                document_type_id=tid,
                is_required=str(tid) in required_ids,
                order=order_map.get(tid, 0),
            )
            created += 1

        messages.success(request, f'Saved document pack for “{category.name}” ({created} type(s)).')
        return redirect('manage_loan_category_documents', category_id=category.id)

    all_types = list(LoanApplicationDocumentType.objects.order_by('order', 'name'))
    existing = {
        r.document_type_id: r
        for r in category.document_requirements.select_related('document_type')
    }
    rows = []
    for dt in all_types:
        req = existing.get(dt.id)
        rows.append({
            'document_type': dt,
            'selected': req is not None,
            'is_required': req.is_required if req else dt.is_required,
            'order': req.order if req else dt.order,
        })
    # Selected-only types that may have been deleted from catalog won't appear — ok
    return render(request, 'loans/manage_loan_category_documents.html', {
        'category': category,
        'rows': rows,
        'pack_count': len(existing),
    })


@login_required
@user_passes_test(lambda u: u.is_superuser)
def edit_loan_category(request, category_id):
    category = get_object_or_404(LoanCategory, pk=category_id)
    if request.method == 'POST':
        form = LoanCategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            return redirect('manage_loan_categories')
    else:
        form = LoanCategoryForm(instance=category)
    return render(request, 'loans/edit_loan_category.html', {'form': form, 'category': category})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_collateral_types(request):
    collateral_types = CollateralType.objects.all()
    
    paginator = Paginator(collateral_types, 10)  # Show 10 branches per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    if request.method == 'POST':
        form = CollateralTypeForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('manage_collateral_types')
    else:
        form = CollateralTypeForm()
        
    context = {
        'form': form,
        'page_obj': page_obj
    }  
    return render(request, 'loans/manage_collateral_types.html', context)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def edit_collateral_type(request, collateral_type_id):
    collateral_type = get_object_or_404(CollateralType, pk=collateral_type_id)
    if request.method == 'POST':
        form = CollateralTypeForm(request.POST, instance=collateral_type)
        if form.is_valid():
            form.save()
            return redirect('manage_collateral_types')
    else:
        form = CollateralTypeForm(instance=collateral_type)
    return render(request, 'loans/edit_collateral_type.html', {'form': form, 'collateral_type': collateral_type})


@login_required
@user_passes_test(_user_can_configure_committees)
def manage_approval_committees(request):
    """Settings: list approval committee levels and who may vote at each."""
    levels = list(
        ApprovalCommitteeLevel.objects.prefetch_related('member_rules')
        .order_by('sequence_order', 'id')
    )
    active_count = sum(1 for lv in levels if lv.is_active)
    level_count = len(levels)
    return render(request, 'loans/manage_approval_committees.html', {
        'levels': levels,
        'level_count': level_count,
        'active_count': active_count,
        'inactive_count': level_count - active_count,
    })


@login_required
@user_passes_test(_user_can_configure_committees)
def add_approval_committee_level(request):
    """Settings: create a level with full options (same as edit, including voters)."""
    from django.db import transaction

    RuleFormSet = get_approval_committee_member_rule_formset(extra=2)
    next_order = 1
    last = ApprovalCommitteeLevel.objects.order_by('-sequence_order').first()
    if last:
        next_order = last.sequence_order + 1

    if request.method == 'POST':
        form = ApprovalCommitteeLevelCreateForm(request.POST)
        formset = RuleFormSet(request.POST, instance=ApprovalCommitteeLevel())
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                level = form.save()
                formset.instance = level
                formset.save()
            messages.success(request, f'Created level “{level.name}”.')
            return redirect('manage_approval_committees')
        messages.error(request, 'Please fix the errors below.')
        scope_help = dict(ApprovalCommitteeLevel.VOTER_SCOPE_CHOICES).get(
            form.data.get('voter_scope') or ApprovalCommitteeLevel.SCOPE_ORGANIZATION, ''
        )
    else:
        form = ApprovalCommitteeLevelCreateForm(initial={
            'sequence_order': next_order,
            'is_active': True,
            'min_approvals_required': 2,
            'min_declines_required': 2,
            'voter_scope': ApprovalCommitteeLevel.SCOPE_ORGANIZATION,
        })
        formset = RuleFormSet(instance=ApprovalCommitteeLevel())
        scope_help = ApprovalCommitteeLevel(
            voter_scope=ApprovalCommitteeLevel.SCOPE_ORGANIZATION,
        ).member_scope_description

    return render(request, 'loans/edit_approval_committee_level.html', {
        'is_create': True,
        'level': None,
        'form': form,
        'formset': formset,
        'scope_help': scope_help,
    })


@login_required
@user_passes_test(_user_can_configure_committees)
def edit_approval_committee_level(request, level_id):
    """Settings: edit thresholds + member rules for one committee level."""
    level = get_object_or_404(ApprovalCommitteeLevel, pk=level_id)
    RuleFormSet = get_approval_committee_member_rule_formset(extra=1)
    if request.method == 'POST':
        form = ApprovalCommitteeLevelForm(request.POST, instance=level)
        formset = RuleFormSet(request.POST, instance=level)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, f'Saved “{level.name}” and its voting rules.')
            return redirect('manage_approval_committees')
        messages.error(request, 'Please fix the errors below.')
    else:
        form = ApprovalCommitteeLevelForm(instance=level)
        formset = RuleFormSet(instance=level)
    return render(request, 'loans/edit_approval_committee_level.html', {
        'is_create': False,
        'level': level,
        'form': form,
        'formset': formset,
        'scope_help': level.member_scope_description,
    })


@login_required
@user_passes_test(_user_can_configure_committees)
def delete_approval_committee_level(request, level_id):
    """Delete a level only when unused by votes / in-progress loans."""
    if request.method != 'POST':
        return redirect('manage_approval_committees')
    level = get_object_or_404(ApprovalCommitteeLevel, pk=level_id)
    from .models import LoanCommitteeVote, LoanApprovalLevelProgress, LoanRequest

    in_use = (
        LoanCommitteeVote.objects.filter(approval_level=level).exists()
        or LoanApprovalLevelProgress.objects.filter(level=level).exists()
        or LoanRequest.objects.filter(current_approval_level=level).exists()
    )
    if in_use:
        messages.error(
            request,
            f'Cannot delete “{level.name}” — it has votes or loans in progress. Deactivate it instead.',
        )
        return redirect('edit_approval_committee_level', level_id=level.id)
    name = level.name
    level.delete()
    messages.success(request, f'Deleted level “{name}”.')
    return redirect('manage_approval_committees')


@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_loan_application_document_types(request):
    """Superadmin: document types + per-type auth rules + bank-wide defaults."""
    document_types = LoanApplicationDocumentType.objects.all()
    paginator = Paginator(document_types, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    defaults_form = DocumentAuthenticationDefaultsForm()
    form = LoanApplicationDocumentTypeForm()
    if request.method == 'POST':
        if request.POST.get('form_kind') == 'defaults':
            defaults_form = DocumentAuthenticationDefaultsForm(request.POST)
            if defaults_form.is_valid():
                defaults_form.save()
                messages.success(request, 'Bank-wide document defaults saved.')
                return redirect('manage_loan_application_document_types')
        else:
            form = LoanApplicationDocumentTypeForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, 'Document type added.')
                return redirect('manage_loan_application_document_types')
    total_types = LoanApplicationDocumentType.objects.count()
    required_count = LoanApplicationDocumentType.objects.filter(is_required=True).count()
    ref_sample_count = LoanApplicationDocumentType.objects.exclude(
        reference_sample='',
    ).exclude(reference_sample=None).count()
    return render(request, 'loans/manage_loan_application_document_types.html', {
        'form': form,
        'defaults_form': defaults_form,
        'page_obj': page_obj,
        'total_types': total_types,
        'required_count': required_count,
        'ref_sample_count': ref_sample_count,
    })


@login_required
@user_passes_test(lambda u: u.is_superuser)
def edit_loan_application_document_type(request, document_type_id):
    from .services.reference_sample import process_reference_sample

    doc_type = get_object_or_404(LoanApplicationDocumentType, pk=document_type_id)
    analysis_report = None
    if request.method == 'POST':
        form = LoanApplicationDocumentTypeEditForm(
            request.POST, request.FILES, instance=doc_type,
        )
        if form.is_valid():
            obj = form.save()
            reanalyze = request.POST.get('reanalyze_reference') == '1'
            force_reseed = request.POST.get('force_reseed_phrases') == '1'
            if obj.reference_sample and (reanalyze or 'reference_sample' in request.FILES):
                analysis_report = process_reference_sample(
                    obj,
                    seed_empty_fields=not force_reseed,
                    force_reseed_phrases=force_reseed,
                )
                if analysis_report.get('error'):
                    messages.warning(request, f'Reference sample: {analysis_report["error"]}')
                else:
                    n = len(analysis_report.get('validation_phrases') or [])
                    messages.success(
                        request,
                        f'Reference sample analyzed — {n} validation phrase(s) learned from OCR.',
                    )
            else:
                messages.success(request, 'Document type updated.')
            return redirect('edit_loan_application_document_type', document_type_id=obj.id)
    else:
        form = LoanApplicationDocumentTypeEditForm(instance=doc_type)
    profile = doc_type.reference_sample_profile or {}
    return render(request, 'loans/edit_loan_application_document_type.html', {
        'form': form,
        'doc_type': doc_type,
        'reference_profile': profile,
        'analysis_report': analysis_report,
    })


@login_required
@user_passes_test(lambda u: u.is_superuser)
def serve_document_type_reference_sample(request, document_type_id):
    """Superadmin: view official reference sample inline."""
    from django.http import FileResponse, Http404
    import mimetypes

    doc_type = get_object_or_404(LoanApplicationDocumentType, pk=document_type_id)
    if not doc_type.reference_sample:
        raise Http404()
    name = doc_type.reference_sample.name.split('/')[-1]
    content_type, _ = mimetypes.guess_type(name)
    if not content_type:
        content_type = 'application/octet-stream'
    response = FileResponse(doc_type.reference_sample.open('rb'), content_type=content_type)
    response['Content-Disposition'] = f'inline; filename="{name}"'
    return response


@login_required
def load_branches(request):
    district_id = request.GET.get('district') or request.GET.get('district_id')
    branches = Branch.objects.filter(district_id=district_id).order_by('name') if district_id else Branch.objects.none()
    return JsonResponse(list(branches.values('id', 'name')), safe=False)

@login_required
@user_passes_test(user_can_access_reports)
def view_report(request):
    from .reporting import filter_choices_for_user, filtered_reporting_queryset

    params = request.GET
    loan_requests = filtered_reporting_queryset(request.user, params)
    paginator = Paginator(loan_requests, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    choices = filter_choices_for_user(request.user, district_id=params.get('district_id') or None)
    return render(request, 'loans/view_report.html', {
        'page_obj': page_obj,
        'filters': {
            'status': params.get('status', ''),
            'committee_status': params.get('committee_status', ''),
            'disbursement_status': params.get('disbursement_status', ''),
            'branch_id': params.get('branch_id', ''),
            'district_id': params.get('district_id', ''),
            'date_from': params.get('date_from', ''),
            'date_to': params.get('date_to', ''),
        },
        **choices,
    })


@login_required
@user_passes_test(user_can_access_reports)
def generate_report(request):
    """Export filtered loan pipeline as Excel (.xlsx)."""
    from .reporting import (
        build_pipeline_workbook, excel_response, filtered_reporting_queryset, pipeline_export_filename,
    )

    params = request.GET
    qs = filtered_reporting_queryset(request.user, params)
    fmt = (params.get('format') or 'xlsx').lower()
    if fmt == 'csv':
        # Legacy CSV kept for compatibility
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="loan_pipeline.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'ID', 'Applicant', 'Branch', 'Amount', 'Status', 'Committee',
            'Disbursement', 'Date requested', 'Date reviewed',
        ])
        for lr in qs[:5000]:
            writer.writerow([
                lr.loan_request_id,
                lr.applicant_name,
                lr.branch.name if lr.branch_id else '',
                lr.amount_requested,
                lr.status,
                lr.get_committee_status_display() if lr.committee_status else '',
                lr.get_disbursement_status_display() if lr.disbursement_status else '',
                lr.date_requested,
                lr.date_reviewed,
            ])
        return response

    bio = build_pipeline_workbook(qs)
    return excel_response(bio, pipeline_export_filename(params))


@login_required
@user_passes_test(user_can_access_reports)
def view_report_options(request):
    from .reporting import (
        branch_dashboard_stats, engineering_workload_stats, filter_choices_for_user,
        filtered_reporting_queryset, is_engineering_reporter,
    )

    choices = filter_choices_for_user(request.user)
    qs = filtered_reporting_queryset(request.user, {})
    stats = branch_dashboard_stats(qs)
    eng_stats = None
    if is_engineering_reporter(request.user) or choices.get('show_engineering_workload'):
        eng_stats = engineering_workload_stats(qs)
    return render(request, 'loans/view_report_options.html', {
        **choices,
        'stats': stats,
        'eng_stats': eng_stats,
    })


@login_required
@user_passes_test(user_can_access_reports)
def branch_report_dashboard(request):
    """Branch / portfolio MIS dashboard with export links."""
    from .reporting import (
        branch_dashboard_stats, engineering_workload_stats, filter_choices_for_user,
        filtered_reporting_queryset, is_engineering_reporter,
    )

    params = request.GET
    qs = filtered_reporting_queryset(request.user, params)
    stats = branch_dashboard_stats(qs)
    choices = filter_choices_for_user(request.user, district_id=params.get('district_id') or None)
    eng_stats = None
    if is_engineering_reporter(request.user) or choices.get('show_engineering_workload'):
        eng_stats = engineering_workload_stats(qs)
    recent = list(qs[:12])
    return render(request, 'loans/branch_report_dashboard.html', {
        'stats': stats,
        'eng_stats': eng_stats,
        'recent_loans': recent,
        'filters': {
            'status': params.get('status', ''),
            'committee_status': params.get('committee_status', ''),
            'disbursement_status': params.get('disbursement_status', ''),
            'branch_id': params.get('branch_id', ''),
            'district_id': params.get('district_id', ''),
            'date_from': params.get('date_from', ''),
            'date_to': params.get('date_to', ''),
        },
        'querystring': request.GET.urlencode(),
        **choices,
    })

@login_required(login_url='login')  # redirect to login page if not logged in
def home(request):
    """Role home: one product landing — not a second dashboard beside CI/Reports."""
    from django.shortcuts import redirect

    role = getattr(request.user, 'role', None)
    if role in ('cooperative_manager', 'operation_manager'):
        return redirect('view_loan_requests_operation_manager')
    if role == 'risk_compliance':
        return redirect('risk_desk')
    if role == 'legal_officer':
        return redirect('legal_desk')
    if role == 'finance_manager':
        return redirect('view_loan_requests_finance_manager')

    from .views_credit_intelligence import credit_intelligence_overview
    return credit_intelligence_overview(request)


@login_required(login_url='login')
def classic_home(request):
    """Legacy status-count dashboard (kept for comparison / fallback)."""
    user = request.user
    role = getattr(user, 'role', None)

    if getattr(user, 'is_superuser', False) or role in ('superadmin', 'admin'):
        loans = LoanRequest.objects.all()
        scope_label = 'Organization-wide'
    elif role == 'loan_officer':
        loans = LoanRequest.objects.filter(assigned_loan_officer=user)
        scope_label = 'Assigned to you'
    elif role == 'branch_manager':
        branch = getattr(user, 'branch', None)
        if branch:
            loans = LoanRequest.objects.filter(branch=branch)
            scope_label = branch.name
        elif getattr(user, 'district_id', None):
            loans = LoanRequest.objects.filter(branch__district=user.district)
            scope_label = getattr(user.district, 'name', 'Your district')
        else:
            loans = LoanRequest.objects.none()
            scope_label = 'No branch assigned'
    else:
        loans = LoanRequest.objects.all()
        scope_label = 'Organization-wide'

    loans = loans.select_related('branch', 'category')
    total_loans = loans.count()
    approved_loans = loans.filter(status='Approved').count()
    pending_loans = loans.filter(status='Pending').count()
    rejected_loans = loans.filter(status='Rejected').count()
    queue_approved = loans.filter(queue_approved=True).count()
    in_appraisal = loans.filter(appraisal_completed_at__isnull=True, assigned_loan_officer__isnull=False).exclude(
        status='Rejected'
    ).count()
    total_amount = loans.aggregate(total=Sum('amount_requested'))['total'] or 0
    approval_rate = round((approved_loans / total_loans) * 100, 1) if total_loans else 0

    if role == 'loan_officer':
        branch_names, branch_counts = ['Assigned to me'], [total_loans]
    elif role == 'branch_manager' and getattr(user, 'branch', None):
        branch_names, branch_counts = [user.branch.name], [total_loans]
    else:
        branch_data = list(
            loans.values('branch__name').annotate(total=Count('id')).order_by('-total')[:12]
        )
        branch_names = [b['branch__name'] or 'Unassigned' for b in branch_data]
        branch_counts = [b['total'] for b in branch_data]

    recent_loans = list(loans.order_by('-date_requested')[:8])

    context = {
        'total_loans': total_loans,
        'approved_loans': approved_loans,
        'pending_loans': pending_loans,
        'rejected_loans': rejected_loans,
        'queue_approved': queue_approved,
        'in_appraisal': in_appraisal,
        'total_amount': total_amount,
        'approval_rate': approval_rate,
        'scope_label': scope_label,
        'recent_loans': recent_loans,
        'branch_names_json': json.dumps(branch_names),
        'branch_counts_json': json.dumps(branch_counts),
    }
    return render(request, 'home.html', context)

EXCEL_UPLOAD_PAGES = {
    'regions': {
        'kind': 'regions',
        'title': 'Upload regions',
        'columns': 'name',
        'url_name': 'upload_regions',
    },
    'zones': {
        'kind': 'zones',
        'title': 'Upload geographic zones',
        'columns': 'region, name  —  for operational districts use Upload districts',
        'url_name': 'upload_zones',
    },
    'cities': {
        'kind': 'cities',
        'title': 'Upload cities / woredas',
        'columns': 'region, zone, name',
        'url_name': 'upload_cities',
    },
    'districts': {
        'kind': 'districts',
        'title': 'Upload districts',
        'columns': 'name  —  legacy name-only “zones” files belong here',
        'url_name': 'upload_districts',
    },
    'branches': {
        'kind': 'branches',
        'title': 'Upload branches',
        'columns': 'district, name  (legacy column “zone” is treated as district)',
        'url_name': 'upload_branches',
    },
    'loan_categories': {
        'kind': 'loan_categories',
        'title': 'Upload loan categories',
        'columns': 'name, appraisal_mode (msme or corporate)',
        'url_name': 'upload_loan_categories',
    },
    'collateral_types': {
        'kind': 'collateral_types',
        'title': 'Upload collateral types',
        'columns': 'name (or collateral), kind (building / land / movable / mixed)',
        'url_name': 'upload_collaterals',
    },
    'users': {
        'kind': 'users',
        'title': 'Upload users',
        'columns': 'username, email, phone_number, role, district, branch, department',
        'url_name': 'upload_users',
        'needs_password': True,
    },
    'loan_requests': {
        'kind': 'loan_requests',
        'title': 'Upload loan requests',
        'columns': 'applicant_name, category, collateral, amount_requested, branch, …',
        'url_name': 'upload_loan_requests',
    },
}


def _excel_upload_view(page_key):
    spec = EXCEL_UPLOAD_PAGES[page_key]

    @login_required
    @user_passes_test(lambda u: u.is_superuser)
    def view(request):
        from loans.excel_import import import_pack, run_import

        if request.method == 'POST' and request.FILES.get('file'):
            uploaded = request.FILES['file']
            update = request.POST.get('update') == '1'
            default_password = (request.POST.get('default_password') or '').strip()
            try:
                if spec.get('pack'):
                    result = import_pack(uploaded, update=update, default_password=default_password)
                else:
                    result = run_import(
                        spec['kind'], uploaded,
                        update=update, default_password=default_password,
                    )
            except Exception as exc:
                messages.error(request, str(exc))
                return redirect(spec['url_name'])
            messages.info(request, result.summary())
            for warning in result.warnings:
                messages.warning(request, warning)
            for error in result.errors:
                messages.error(request, error)
            return redirect(spec['url_name'])
        return render(request, 'backup/upload_excel.html', {'spec': spec})

    view.__name__ = f'upload_{page_key}'
    view.__doc__ = spec['title']
    return view


upload_regions = _excel_upload_view('regions')
upload_zones = _excel_upload_view('zones')
upload_cities = _excel_upload_view('cities')
upload_districts = _excel_upload_view('districts')
upload_branches = _excel_upload_view('branches')
upload_loan_categories = _excel_upload_view('loan_categories')
upload_users = _excel_upload_view('users')
upload_loan_requests = _excel_upload_view('loan_requests')
upload_collaterals = _excel_upload_view('collateral_types')