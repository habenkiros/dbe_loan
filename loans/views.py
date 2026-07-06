# loans/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.clickjacking import xframe_options_sameorigin
from .services import fetch_customer_by_number
from django.utils import timezone
from .models import (
    Region, Zone, City, District, Branch, LoanCategory, CollateralType,
    LoanApplicationDocumentType, LoanRequestDocument, LoanDocumentRequest, LoanAppraisal,
    LoanRequest, CustomUser, LatestLoanRequestID, CollateralEstimationConfig,
    LoanRequestBasicInfo, AppraisalCreditHistoryEntry, AppraisalQualitativeFactor, QUALITATIVE_FACTOR_KEYS,
    AppraisalAmortizationEntry,
)
from .forms import (
    CustomUserCreationForm, CustomUserChangeForm, LoanRequestForm, AssignLoanOfficerForm, AssignEngineerForm,
    DistrictForm, BranchForm, RegionForm, ZoneForm, CityForm,
    LoanCategoryForm, CollateralTypeForm, LoanApplicationDocumentTypeForm,
    DocumentAuthenticationDefaultsForm, LoanApplicationDocumentTypeEditForm, LoanAppraisalForm,
    LoanRequestBasicInfoForm, get_credit_history_formset, get_qualitative_factors_formset,
    CollateralEstimationConfigForm,
    AppraisalSheet2Form, AppraisalSheet3Form,
    AppraisalESForm, AppraisalCollateralForm, AppraisalSummaryForm,
    CommitteeVoteForm,
)
from .appraisal_pack import build_committee_appraisal_pack
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
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.http import HttpResponse
import csv
from django.core.files.storage import FileSystemStorage
from django.contrib import messages
import pandas as pd

@login_required
def home(request):
    return render(request, 'loans/home.html')

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
        "roles": CustomUser.ROLE_CHOICES,
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
@user_passes_test(lambda u: u.role == 'branch_manager')
def create_loan_request(request):
    if request.method == 'POST':
        form = LoanRequestForm(request.POST)
        if form.is_valid():
            loan_request = form.save(commit=False)
            loan_request.district = request.user.district
            loan_request.branch = request.user.branch
            loan_request.loan_request_id = generate_incremental_loan_request_id()
            loan_request.save()
            messages.success(request, 'Loan request created. You can now add application documents.')
            return redirect('upload_loan_request_documents', loan_request_id=loan_request.id)
    else:
        form = LoanRequestForm()
    return render(request, 'loans/create_loan_request.html', {'form': form})


@login_required
@user_passes_test(lambda u: u.role == 'branch_manager')
def upload_loan_request_documents(request, loan_request_id):
    """Upload or view application documents for a loan request. Branch manager only; own branch only."""
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if request.user.role == 'branch_manager' and loan_request.branch_id != request.user.branch_id:
        messages.warning(request, 'You can only manage documents for loans in your branch.')
        return redirect('view_loan_requests')
    document_types = LoanApplicationDocumentType.objects.all()
    existing = loan_request.application_documents.select_related(
        'document_type', 'uploaded_by',
    ).order_by('-uploaded_at')
    existing_by_type = {}
    for doc in existing:
        if doc.document_type_id not in existing_by_type:
            existing_by_type[doc.document_type_id] = doc
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
                if doc_type.content_extraction_mappings.strip():
                    from .services.appraisal_prefill import sync_appraisal_from_sources
                    sync_appraisal_from_sources(loan_request, only_empty=True, include_collateral=False)
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
    return render(request, 'loans/upload_loan_request_documents.html', {
        'loan_request': loan_request,
        'document_types': document_types,
        'existing_documents': list(existing_by_type.values()),
        'existing_by_type': existing_by_type,
        'document_requests': document_requests,
    })


def generate_incremental_loan_request_id():
    latest_id_instance, created = LatestLoanRequestID.objects.get_or_create(pk=1)
    latest_id = latest_id_instance.latest_id + 1
    latest_id_instance.latest_id = latest_id
    latest_id_instance.save()
    return f"HK-{latest_id:09d}"

# loans/views.py

@login_required
@user_passes_test(lambda u: u.role in ['operation_manager', 'finance_manager'])  # approval roles
def update_loan_request_status(request, loan_request_id):
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if request.method == 'POST':
        if 'operation_manager' in request.POST and request.user.role == 'operation_manager':
            loan_request.operation_manager_approval = request.POST.get('operation_manager_approval') == 'True'
        elif 'finance_manager' in request.POST and request.user.role == 'finance_manager':
            loan_request.finance_approval = request.POST.get('finance_approval') == 'True'
        loan_request.save()
        if loan_request.managers_queue_approved():
            messages.success(
                request,
                'Loan approved by operation and finance managers. Branch can assign loan officer and proceed.',
            )
        return redirect('view_loan_requests')
    return render(request, 'loans/update_loan_request_status.html', {'loan_request': loan_request})

@login_required
@user_passes_test(lambda u: u.role == 'operation_manager')
def update_operation_manager_approval(request, loan_request_id):
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if request.method == 'POST':
        loan_request.operation_manager_approval = request.POST.get('operation_manager_approval') == 'True'
        loan_request.save()
        if loan_request.managers_queue_approved():
            messages.success(
                request,
                'Loan approved by both managers. Status is Approved — branch can assign loan officer.',
            )
        else:
            messages.success(request, 'Operation manager approval saved.')
        return redirect('view_loan_requests_operation_manager')
    return render(request, 'loans/update_operation_manager_approval.html', {'loan_request': loan_request})

@login_required
@user_passes_test(lambda u: u.role == 'finance_manager')
def update_finance_manager_approval(request, loan_request_id):
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if request.method == 'POST':
        loan_request.finance_approval = request.POST.get('finance_approval') == 'True'
        loan_request.save()
        if loan_request.managers_queue_approved():
            messages.success(
                request,
                'Loan approved by both managers. Status is Approved — branch can assign loan officer.',
            )
        else:
            messages.success(request, 'Finance manager approval saved.')
        return redirect('view_loan_requests_finance_manager')
    return render(request, 'loans/update_finance_manager_approval.html', {'loan_request': loan_request})


def _is_assigned_officer_or_engineer(user, loan_request):
    """True if this user is the assigned loan officer or engineer for this loan."""
    if user.role == 'loan_officer' and loan_request.assigned_loan_officer_id == user.id:
        return True
    if user.role == 'engineer' and loan_request.assigned_engineer_id == user.id:
        return True
    return False


def _user_can_access_loan_documents(user, loan_request) -> bool:
    if getattr(user, 'is_superuser', False) or getattr(user, 'role', None) in ('superadmin', 'admin'):
        return True
    if getattr(user, 'role', None) == 'branch_manager' and user.branch_id == loan_request.branch_id:
        return True
    if _is_assigned_officer_or_engineer(user, loan_request):
        return True
    if getattr(user, 'role', None) in ('operation_manager', 'finance_manager'):
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
@user_passes_test(lambda u: u.role in ['branch_manager', 'operation_manager', 'finance_manager', 'loan_officer', 'engineer', 'engineering_head', 'superadmin', 'admin'])
def loan_request_detail(request, loan_request_id):
    user = request.user
    if user.role == 'loan_officer':
        loan_request = get_object_or_404(LoanRequest, pk=loan_request_id, assigned_loan_officer=user)
    elif user.role == 'engineer':
        loan_request = get_object_or_404(LoanRequest, pk=loan_request_id, assigned_engineer=user)
    else:
        loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    collateral_mode = get_collateral_estimation_mode()
    document_types = LoanApplicationDocumentType.objects.all()
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
    can_request_documents = _is_assigned_officer_or_engineer(user, loan_request)
    document_types_missing = [dt for dt in document_types if dt.id not in uploaded_type_ids] if document_types else []
    appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    committee_submit = officer_can_submit_to_committee(loan_request) if (
        user.role == 'loan_officer' and loan_request.assigned_loan_officer_id == user.id
    ) else None
    committee_tally = get_committee_tally(loan_request, current_user=user)
    from .services.document_auth import loan_documents_collateral_readiness

    doc_readiness = loan_documents_collateral_readiness(loan_request)
    can_authenticate_documents = _is_assigned_officer_or_engineer(user, loan_request)
    collateral_readiness = None
    collateral_totals = None
    collateral_blockers = []
    if loan_request.documents_reviewed_at or loan_request.queue_approved or (loan_request.status or '').lower() == 'approved':
        from collateral.field_utils import get_loan_collateral_readiness, collateral_submit_blockers
        from loans.services.appraisal_prefill import compute_collateral_totals

        collateral_readiness = get_loan_collateral_readiness(loan_request)
        collateral_totals = compute_collateral_totals(loan_request)
        if not collateral_readiness.get('locked'):
            collateral_blockers = collateral_submit_blockers(loan_request)
    coverage = None
    if collateral_readiness:
        from collateral.coverage import compute_coverage_adequacy
        coverage = compute_coverage_adequacy(loan_request)
    return render(request, 'loans/loan_request_detail.html', {
        'loan_request': loan_request,
        'collateral_estimation_mode': collateral_mode,
        'document_types': document_types,
        'application_documents': application_documents,
        'pending_document_requests': pending_document_requests,
        'can_request_documents': can_request_documents,
        'can_authenticate_documents': can_authenticate_documents,
        'document_types_missing': document_types_missing,
        'requested_type_ids': requested_type_ids,
        'doc_readiness': doc_readiness,
        'collateral_readiness': collateral_readiness,
        'collateral_totals': collateral_totals,
        'collateral_blockers': collateral_blockers,
        'coverage': coverage,
        'appraisal': appraisal,
        'committee_submit': committee_submit,
        'committee_tally': committee_tally,
    })


@login_required
@user_passes_test(lambda u: u.role in ['loan_officer', 'engineer'])
def request_loan_document(request, loan_request_id):
    """Assigned loan officer or engineer requests a document type (branch manager can then upload)."""
    if request.method != 'POST':
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    if request.user.role == 'loan_officer':
        loan_request = get_object_or_404(LoanRequest, pk=loan_request_id, assigned_loan_officer=request.user)
    else:
        loan_request = get_object_or_404(LoanRequest, pk=loan_request_id, assigned_engineer=request.user)
    doc_type_id = request.POST.get('document_type_id')
    if not doc_type_id:
        messages.warning(request, 'Please select a document type.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    try:
        doc_type = LoanApplicationDocumentType.objects.get(pk=doc_type_id)
    except LoanApplicationDocumentType.DoesNotExist:
        messages.warning(request, 'Invalid document type.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    LoanDocumentRequest.objects.update_or_create(
        loan_request=loan_request,
        document_type=doc_type,
        defaults={'requested_by': request.user, 'requested_at': timezone.now()},
    )
    from .services.document_notifications import notify_document_requested

    notify_document_requested(loan_request, doc_type, request.user)
    messages.success(request, f'Request for "{doc_type.name}" recorded. Branch manager will be notified to upload it.')
    return redirect('loan_request_detail', loan_request_id=loan_request_id)


@login_required
@user_passes_test(lambda u: u.role in ['loan_officer', 'engineer'])
def proceed_to_collateral(request, loan_request_id):
    """Assigned loan officer or engineer marks documents reviewed and proceeds to collateral estimation."""
    if request.method != 'POST':
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    if request.user.role == 'loan_officer':
        loan_request = get_object_or_404(LoanRequest, pk=loan_request_id, assigned_loan_officer=request.user)
    else:
        loan_request = get_object_or_404(LoanRequest, pk=loan_request_id, assigned_engineer=request.user)
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
@user_passes_test(lambda u: u.role in ['loan_officer', 'engineer'])
def authenticate_loan_document(request, loan_request_id, document_id):
    """Loan officer / engineer: verify or reject document authenticity."""
    if request.method != 'POST':
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    if request.user.role == 'loan_officer':
        loan_request = get_object_or_404(LoanRequest, pk=loan_request_id, assigned_loan_officer=request.user)
    else:
        loan_request = get_object_or_404(LoanRequest, pk=loan_request_id, assigned_engineer=request.user)
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
        messages.warning(request, f'"{doc.document_type.name}" rejected.')
    elif action == 'requeue':
        try:
            from .services.document_auth import run_automated_document_checks
            run_automated_document_checks(doc)
            doc.refresh_from_db()
            if doc.auth_status == LRD.AUTH_NEEDS_REVIEW:
                notify_document_needs_review(doc)
            else:
                notify_document_uploaded(doc)
            messages.info(request, f'Automated checks re-run for "{doc.document_type.name}".')
        except Exception as exc:
            messages.error(request, f'Could not re-run checks: {exc}')
    else:
        messages.warning(request, 'Unknown action.')
    return redirect('loan_request_detail', loan_request_id=loan_request_id)


@login_required
@user_passes_test(lambda u: u.role == 'loan_officer')
def loan_appraisal_steps(request):
    """Loan officers only: static clickable steps from Cashflow based MSME loan appraisal tool (V1.8.3). Presentation only."""
    return render(request, 'loans/loan_appraisal_steps.html')


def _ensure_qualitative_factors(appraisal):
    """Ensure exactly 10 qualitative factor rows exist for this appraisal (Sheet 2)."""
    existing_keys = set(
        appraisal.qualitative_factors.values_list('factor_key', flat=True)
    )
    for order, (key, name) in enumerate(QUALITATIVE_FACTOR_KEYS):
        if key not in existing_keys:
            AppraisalQualitativeFactor.objects.create(
                appraisal=appraisal,
                factor_key=key,
                factor_name=name,
                display_order=order,
            )


APPRAISAL_STEPS = [
    (1, 'Basic Info & loan request'),
    (2, 'Business & character assessment'),
    (3, 'Cashflow analysis'),
    (4, 'E&S assessment'),
    (5, 'Collateral worksheet'),
    (6, 'Summary & decision'),
    (7, 'Repayment & amortization'),
]
TOTAL_APPRAISAL_STEPS = len(APPRAISAL_STEPS)


@login_required
@user_passes_test(lambda u: u.role == 'loan_officer')
def loan_appraisal_edit(request, loan_request_id):
    """Redirect to step-based appraisal (step 1)."""
    return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=1)


@login_required
@user_passes_test(lambda u: u.role == 'loan_officer')
def loan_appraisal_step(request, loan_request_id, step):
    """
    Page-based loan appraisal: one sheet per step (1–4).
    GET: show that step's form. POST: save and redirect to next step (or stay on error).
    """
    if step < 1 or step > TOTAL_APPRAISAL_STEPS:
        return redirect('loan_appraisal_edit', loan_request_id=loan_request_id)

    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id, assigned_loan_officer=request.user)
    basic_info, _ = LoanRequestBasicInfo.objects.get_or_create(loan_request=loan_request)
    appraisal, _ = LoanAppraisal.objects.get_or_create(
        loan_request=loan_request,
        defaults={'created_by': request.user},
    )
    _ensure_qualitative_factors(appraisal)

    CreditHistoryFormSet = get_credit_history_formset()
    QualitativeFormSet = get_qualitative_factors_formset()

    common_ctx = {
        'loan_request': loan_request,
        'appraisal': appraisal,
        'basic_info': basic_info,
        'step': step,
        'total_steps': TOTAL_APPRAISAL_STEPS,
        'steps': APPRAISAL_STEPS,
        'step_title': APPRAISAL_STEPS[step - 1][1],
    }

    if request.method == 'POST':
        if step == 1 and request.POST.get('import_sources'):
            from .services.appraisal_prefill import sync_appraisal_from_sources

            prefill_report = sync_appraisal_from_sources(loan_request, only_empty=True)
            n = prefill_report.get('total_fields', 0)
            if n:
                messages.success(request, f'Imported {n} field(s) from registration, documents, and collateral.')
            else:
                messages.info(request, 'No new fields to import — existing data kept, or sources are empty.')
            basic_info.refresh_from_db()
            appraisal.refresh_from_db()
            return render(request, 'loans/loan_appraisal_step1.html', {
                **common_ctx,
                'basic_form': LoanRequestBasicInfoForm(instance=basic_info),
                'prefill_report': prefill_report,
            })

        if step == 1:
            basic_form = LoanRequestBasicInfoForm(request.POST, instance=basic_info)
            if basic_form.is_valid():
                basic_form.save()
                messages.success(request, 'Sheet 1 saved.')
                return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=2)
            return render(request, 'loans/loan_appraisal_step1.html', {
                **common_ctx, 'basic_form': basic_form,
            })

        if step == 2:
            form = AppraisalSheet2Form(request.POST, instance=appraisal)
            credit_formset = CreditHistoryFormSet(request.POST, instance=appraisal, prefix='credit')
            qual_formset = QualitativeFormSet(request.POST, instance=appraisal, prefix='qual')
            if form.is_valid() and credit_formset.is_valid() and qual_formset.is_valid():
                form.save()
                credit_formset.save()
                qual_formset.save()
                messages.success(request, 'Sheet 2 saved.')
                return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=3)
            return render(request, 'loans/loan_appraisal_step2.html', {
                **common_ctx, 'form': form, 'credit_formset': credit_formset, 'qual_formset': qual_formset,
            })

        if step == 3:
            form = AppraisalSheet3Form(request.POST, instance=appraisal)
            if form.is_valid():
                form.save()
                messages.success(request, 'Sheet 3 saved.')
                return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=4)
            return render(request, 'loans/loan_appraisal_step3.html', {
                **common_ctx, 'form': form,
            })

        if step == 4:
            form = AppraisalESForm(request.POST, instance=appraisal)
            if form.is_valid():
                form.save()
                messages.success(request, 'Sheet 4 (E&S) saved.')
                return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=5)
            return render(request, 'loans/loan_appraisal_step4.html', { **common_ctx, 'form': form })

        if step == 5:
            form = AppraisalCollateralForm(request.POST, instance=appraisal)
            if form.is_valid():
                form.save()
                messages.success(request, 'Sheet 5 (Collateral) saved.')
                return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=6)
            return render(request, 'loans/loan_appraisal_step5.html', { **common_ctx, 'form': form })

        if step == 6:
            form = AppraisalSummaryForm(request.POST, instance=appraisal)
            if form.is_valid():
                obj = form.save(commit=False)
                if not obj.created_by_id:
                    obj.created_by = request.user
                obj.save()
                messages.success(request, 'Sheet 6 (Summary & decision) saved.')
                return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=7)
            return render(request, 'loans/loan_appraisal_step6.html', { **common_ctx, 'form': form })

        if step == 7:
            if request.POST.get('generate_schedule'):
                _generate_amortization_schedule(appraisal, basic_info, loan_request)
                messages.success(request, 'Repayment schedule generated.')
                return redirect('loan_appraisal_step', loan_request_id=loan_request_id, step=7)
            if request.POST.get('finish'):
                loan_request.appraisal_completed_at = timezone.now()
                loan_request.save(update_fields=['appraisal_completed_at'])
                messages.success(
                    request,
                    'Appraisal complete. Review Sheet 6 recommended amount, then submit to the approval committee from the loan detail page.',
                )
                return redirect('loan_request_detail', loan_request_id=loan_request_id)
            return render(request, 'loans/loan_appraisal_step7.html', common_ctx)

    # GET — auto-import empty appraisal fields from registration / documents / collateral
    if step == 1:
        from .services.appraisal_prefill import sync_appraisal_from_sources

        prefill_report = sync_appraisal_from_sources(loan_request, only_empty=True)
        if prefill_report.get('total_fields'):
            basic_info.refresh_from_db()
            appraisal.refresh_from_db()
        common_ctx['prefill_report'] = prefill_report
        basic_form = LoanRequestBasicInfoForm(instance=basic_info)
        return render(request, 'loans/loan_appraisal_step1.html', {
            **common_ctx, 'basic_form': basic_form,
        })
    if step == 2:
        form = AppraisalSheet2Form(instance=appraisal)
        credit_formset = CreditHistoryFormSet(instance=appraisal, prefix='credit')
        qual_formset = QualitativeFormSet(instance=appraisal, prefix='qual')
        return render(request, 'loans/loan_appraisal_step2.html', {
            **common_ctx, 'form': form, 'credit_formset': credit_formset, 'qual_formset': qual_formset,
        })
    if step == 3:
        form = AppraisalSheet3Form(instance=appraisal)
        return render(request, 'loans/loan_appraisal_step3.html', { **common_ctx, 'form': form })
    if step == 4:
        form = AppraisalESForm(instance=appraisal)
        return render(request, 'loans/loan_appraisal_step4.html', { **common_ctx, 'form': form })
    if step == 5:
        from .services.appraisal_prefill import sync_collateral_to_appraisal

        collateral_prefill = sync_collateral_to_appraisal(loan_request, appraisal, only_empty=True)
        if collateral_prefill:
            appraisal.refresh_from_db()
        common_ctx['prefill_report'] = {'collateral': collateral_prefill}
        form = AppraisalCollateralForm(instance=appraisal)
        return render(request, 'loans/loan_appraisal_step5.html', { **common_ctx, 'form': form })
    if step == 6:
        form = AppraisalSummaryForm(instance=appraisal)
        return render(request, 'loans/loan_appraisal_step6.html', { **common_ctx, 'form': form })
    if step == 7:
        return render(request, 'loans/loan_appraisal_step7.html', common_ctx)

    return redirect('loan_appraisal_edit', loan_request_id=loan_request_id)


def _add_months(date, months):
    """Add months to a date (stdlib only)."""
    import calendar
    month = date.month - 1 + months
    year = date.year + month // 12
    month = month % 12 + 1
    day = min(date.day, calendar.monthrange(year, month)[1])
    return date.replace(year=year, month=month, day=day)


def _generate_amortization_schedule(appraisal, basic_info, loan_request):
    """Generate amortization entries from loan amount and basic info terms (declining balance)."""
    from decimal import Decimal
    from django.utils import timezone

    AppraisalAmortizationEntry.objects.filter(appraisal=appraisal).delete()
    amount = loan_request.amount_requested or Decimal('0')
    term_months = basic_info.term_months or 12
    annual_rate = (basic_info.interest_rate or Decimal('0')) / Decimal('100')
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
@user_passes_test(lambda u: u.role in ['branch_manager', 'admin', 'superadmin'])
def assign_loan_officer(request, loan_request_id):
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if request.user.role == 'branch_manager' and loan_request.branch_id != request.user.branch_id:
        return redirect('view_loan_requests')
    if not loan_request.queue_approved:
        messages.warning(
            request,
            'Assign a loan officer only after both operation and finance managers have approved the loan.',
        )
        return redirect('loan_request_detail', loan_request_id=loan_request.id)
    if loan_request.status and loan_request.status.strip().lower() != 'approved':
        messages.warning(request, 'You can assign a loan officer only when the loan request status is Approved.')
        return redirect('loan_request_detail', loan_request_id=loan_request.id)
    form = AssignLoanOfficerForm(branch=loan_request.branch)
    if request.method == 'POST':
        form = AssignLoanOfficerForm(request.POST, branch=loan_request.branch)
        if form.is_valid():
            loan_request.assigned_loan_officer_id = form.cleaned_data.get('assigned_loan_officer') or None
            loan_request.save()
            messages.success(request, 'Assigned loan officer updated.')
            return redirect('loan_request_detail', loan_request_id=loan_request.id)
    else:
        form = AssignLoanOfficerForm(
            initial={'assigned_loan_officer': loan_request.assigned_loan_officer},
            branch=loan_request.branch,
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
            'Send to engineering only after both operation and finance managers have approved the loan.',
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
    return render(request, 'loans/loans_sent_for_collateral.html', {
        'loan_requests': qs,
        'query': q or '',
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
            loan_request.assigned_engineer_id = form.cleaned_data.get('assigned_engineer') or None
            loan_request.save(update_fields=['assigned_engineer_id'])
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
@user_passes_test(lambda u: u.role == 'operation_manager')
def loan_request_detail_operation_manager(request, loan_request_id):
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    return render(request, 'loans/loan_request_detail_operation_manager.html', {'loan_request': loan_request})

@login_required
@user_passes_test(lambda u: u.role == 'finance_manager')
def loan_request_detail_finance(request, loan_request_id):
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    return render(request, 'loans/loan_request_detail_finance.html', {'loan_request': loan_request})
#manager
@login_required
def loan_request_detail_manager(request, loan_request_id):
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
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
    return render(request, 'loans/loan_request_detail_manager.html', {
        'loan_request': loan_request,
        'appraisal': appraisal,
        'basic_info': basic_info,
        'committee_tally': committee_tally,
        'vote_form': vote_form,
        'can_return_to_officer': can_return,
    })


@login_required
@user_passes_test(lambda u: u.role == 'loan_officer')
def submit_to_committee(request, loan_request_id):
    """Loan officer submits completed appraisal package to the approval committee."""
    if request.method != 'POST':
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    loan_request = get_object_or_404(
        LoanRequest, pk=loan_request_id, assigned_loan_officer=request.user,
    )
    check = officer_can_submit_to_committee(loan_request)
    if not check['ok']:
        for err in check['errors']:
            messages.error(request, err)
        return redirect('loan_request_detail', loan_request_id=loan_request_id)

    notes = request.POST.get('committee_submission_notes', '').strip()
    loan_request.submitted_to_committee_at = timezone.now()
    loan_request.submitted_to_committee_by = request.user
    loan_request.committee_submission_notes = notes
    loan_request.save(
        update_fields=[
            'submitted_to_committee_at',
            'submitted_to_committee_by',
            'committee_submission_notes',
        ]
    )
    start_approval_workflow(loan_request)
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

    from .models import LoanCommitteeVote

    LoanCommitteeVote.objects.create(
        loan_request=loan_request,
        approval_level=level,
        member=request.user,
        vote=form.cleaned_data['vote'],
        amount_supported=amount,
        comments=form.cleaned_data.get('comments') or '',
    )
    if try_finalize_committee_decision(loan_request):
        loan_request.refresh_from_db()
        if loan_request.committee_status == LoanRequest.COMMITTEE_APPROVED:
            messages.success(request, 'Required approvals reached — loan fully approved by all committee levels.')
        elif loan_request.committee_status == LoanRequest.COMMITTEE_DECLINED:
            messages.warning(request, 'Required declines reached — loan rejected at this committee level.')
        else:
            messages.success(request, f'Level “{level.name}” complete. Advanced to the next approval committee.')
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
    return render(request, 'loans/committee_appraisal_pack.html', pack)


@login_required
def loan_notifications_list(request):
    from .models import LoanNotification

    notifications = LoanNotification.objects.filter(user=request.user).select_related('loan_request')[:100]
    if request.method == 'POST' and request.POST.get('mark_all_read'):
        LoanNotification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        messages.success(request, 'All notifications marked as read.')
        return redirect('loan_notifications_list')
    return render(request, 'loans/loan_notifications.html', {
        'notifications': notifications,
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


def _loan_requests_queryset_for_user(user):
    """Base queryset: all for superadmin/admin/superuser; by branch for branch_manager; assigned for loan_officer or engineer (by config)."""
    if getattr(user, 'is_superuser', False) or getattr(user, 'role', None) in ('superadmin', 'admin'):
        return LoanRequest.objects.all()
    if getattr(user, 'role', None) == 'engineering_head':
        if allows_engineering_team():
            return LoanRequest.objects.filter(sent_to_engineering_at__isnull=False)
        return LoanRequest.objects.none()
    if getattr(user, 'role', None) == 'loan_officer':
        if allows_loan_officer():
            return LoanRequest.objects.filter(assigned_loan_officer=user)
        return LoanRequest.objects.none()
    if getattr(user, 'role', None) == 'engineer':
        if allows_engineering_team():
            return LoanRequest.objects.filter(assigned_engineer=user)
        return LoanRequest.objects.none()
    if getattr(user, 'role', None) == 'branch_manager':
        if getattr(user, 'branch_id', None):
            return LoanRequest.objects.filter(branch=user.branch)
        if getattr(user, 'district_id', None):
            return LoanRequest.objects.filter(branch__district=user.district)
        return LoanRequest.objects.none()
    return LoanRequest.objects.none()


@login_required
@user_passes_test(lambda u: getattr(u, 'is_superuser', False) or u.role in ['branch_manager', 'loan_officer', 'engineer', 'engineering_head', 'superadmin', 'admin'])
def view_loan_requests(request):
    if getattr(request.user, 'role', None) == 'engineering_head' and allows_engineering_team():
        return redirect('loans_sent_for_collateral')
    if getattr(request.user, 'role', None) == 'engineer' and allows_engineering_team():
        return redirect(reverse('collateral:dashboard'))
    loan_requests = _loan_requests_queryset_for_user(request.user)
    
    query = request.GET.get("q")
    # Filtering
    date_requested = request.GET.get('date_requested')
    status = request.GET.get('status')
    loan_request_id = request.GET.get('loan_request_id')
    
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

    # Pagination
    paginator = Paginator(loan_requests, 10)  # Show 10 loan requests per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'loan_requests': loan_requests,
        "query": query or "",
        'selected_date_requested': date_requested,
        'selected_loan_request_id': loan_request_id,
        'selected_status': status,
        'collateral_estimation_mode': get_collateral_estimation_mode(),
    }
    return render(request, 'loans/view_loan_requests.html', context)


@login_required
@user_passes_test(lambda u: getattr(u, 'is_superuser', False) or u.role in ['branch_manager', 'loan_officer', 'superadmin', 'admin'])
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
@user_passes_test(lambda u: u.role == 'operation_manager')
def view_loan_requests_operation_manager(request):
    user = request.user  # Fetch the logged-in user
    district_id = request.GET.get('district')
    branch_id = request.GET.get('branch')
    date_requested = request.GET.get('date_requested')
    loan_request_id = request.GET.get('loan_request_id')
    status = request.GET.get('status')

    loan_requests = LoanRequest.objects.all()
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
    paginator = Paginator(loan_requests, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
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
    }
    return render(request, 'loans/view_loan_requests_operation_manager.html', context)


@login_required
@user_passes_test(lambda u: u.role == 'finance_manager')
def view_loan_requests_finance_manager(request):
    query = request.GET.get("q")
    district_id = request.GET.get('district')
    branch_id = request.GET.get('branch')
    date_requested = request.GET.get('date_requested')
    loan_request_id = request.GET.get('loan_request_id')
    status = request.GET.get('status')
    loan_requests = LoanRequest.objects.all()
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
    if query:
        loan_requests = loan_requests.filter(
            Q(applicant_name__icontains=query) |
            Q(phone_number__icontains=query) |
            Q(loan_request_id__icontains=query)
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
        'selected_status': status,
        "query": query or "",
    }
    return render(request, 'loans/view_loan_requests_finance_manager.html', context)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_districts(request):
    districts = District.objects.all()
    if request.method == 'POST':
        form = DistrictForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('manage_districts')
    else:
        form = DistrictForm()
    return render(request, 'loans/manage_districts.html', {'districts': districts, 'form': form})

@login_required
def view_loan_requests_manager(request):
    district_id = request.GET.get('district')
    branch_id = request.GET.get('branch')
    date_requested = request.GET.get('date_requested')
    loan_request_id = request.GET.get('loan_request_id')
    status = request.GET.get('status')
    committee_status = request.GET.get('committee_status')
    queue = request.GET.get('queue')
    if queue == 'my_votes':
        loan_requests = committee_queue_queryset(request.user)
    elif (
        getattr(request.user, 'is_superuser', False)
        or request.user.role in ('superadmin', 'admin')
    ):
        loan_requests = LoanRequest.objects.filter(
            ~Q(committee_status='') & ~Q(committee_status__isnull=True)
        )
    else:
        loan_requests = committee_loan_requests_queryset(request.user)
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
    return render(request, 'loans/manage_loan_application_document_types.html', {
        'form': form,
        'defaults_form': defaults_form,
        'page_obj': page_obj,
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
@user_passes_test(lambda u: u.role in ['branch_manager', 'operation_manager', 'finance_manager', 'credit_committee', 'loan_officer'])
def view_report(request):
    status = request.GET.get('status')
    role = request.user.role
    branch = request.user.branch if role == 'branch_manager' else None

    loan_requests = LoanRequest.objects.all()
    
    if branch:
        loan_requests = loan_requests.filter(branch=branch)
    
    if status:
        loan_requests = loan_requests.filter(status__iexact=status)

    paginator = Paginator(loan_requests, 10)  # Show 10 loan requests per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'status': status,
        'districts': District.objects.all(),
        'branches': Branch.objects.all(),
    }
    return render(request, 'loans/view_report.html', context)

@login_required
@user_passes_test(lambda u: u.role in ['branch_manager', 'operation_manager', 'finance_manager', 'credit_committee', 'loan_officer'])
def generate_report(request):
    status = request.GET.get('status')
    role = request.user.role
    branch = request.user.branch if role == 'branch_manager' else None

    loan_requests = LoanRequest.objects.all()
    
    if branch:
        loan_requests = loan_requests.filter(branch=branch)
    
    if status:
        loan_requests = loan_requests.filter(status__iexact=status)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{status}_loan_requests.csv"'

    writer = csv.writer(response)
    writer.writerow(['ID', 'Applicant Name', 'Amount Requested', 'Status', 'Date Requested', 'Date Reviewed'])

    for loan_request in loan_requests:
        writer.writerow([
            loan_request.loan_request_id,
            loan_request.applicant_name,
            loan_request.amount_requested,
            loan_request.status,
            loan_request.date_requested,
            loan_request.date_reviewed
        ])

    return response

@login_required
@user_passes_test(lambda u: u.role in ['branch_manager', 'operation_manager', 'finance_manager', 'credit_committee', 'loan_officer'])
def view_report_options(request):
    return render(request, 'loans/view_report_options.html')

@login_required(login_url='login')  # redirect to login page if not logged in
def home(request):
    user = request.user

    # Default values
    total_loans = approved_loans = pending_loans = rejected_loans = 0
    branch_names, branch_counts = [], []

    # Superadmin / admin / superuser see all loans on dashboard
    if getattr(user, 'is_superuser', False) or getattr(user, 'role', None) in ('superadmin', 'admin'):
        total_loans = LoanRequest.objects.count()
        approved_loans = LoanRequest.objects.filter(status="Approved").count()
        pending_loans = LoanRequest.objects.filter(status="Pending").count()
        rejected_loans = LoanRequest.objects.filter(status="Rejected").count()
        branch_data = LoanRequest.objects.values('branch__name').annotate(total=Count('id'))
        branch_names = [b['branch__name'] for b in branch_data]
        branch_counts = [b['total'] for b in branch_data]
    elif user.role == "loan_officer":
        loans = LoanRequest.objects.filter(assigned_loan_officer=user)
        total_loans = loans.count()
        approved_loans = loans.filter(status="Approved").count()
        pending_loans = loans.filter(status="Pending").count()
        rejected_loans = loans.filter(status="Rejected").count()
        branch_names = ['Assigned to me']
        branch_counts = [total_loans]
    elif user.role == "branch_manager":
        branch = getattr(user, 'branch', None)
        loans = LoanRequest.objects.filter(branch=branch) if branch else LoanRequest.objects.none()
        if not branch and getattr(user, 'district_id', None):
            loans = LoanRequest.objects.filter(branch__district=user.district)
        total_loans = loans.count()
        approved_loans = loans.filter(status="Approved").count()
        pending_loans = loans.filter(status="Pending").count()
        rejected_loans = loans.filter(status="Rejected").count()
        branch_names = [branch.name] if branch else ['No branch assigned']
        branch_counts = [total_loans]
    else:
        total_loans = LoanRequest.objects.count()
        approved_loans = LoanRequest.objects.filter(status="Approved").count()
        pending_loans = LoanRequest.objects.filter(status="Pending").count()
        rejected_loans = LoanRequest.objects.filter(status="Rejected").count()
        branch_data = LoanRequest.objects.values('branch__name').annotate(total=Count('id'))
        branch_names = [b['branch__name'] for b in branch_data]
        branch_counts = [b['total'] for b in branch_data]

    context = {
        'total_loans': total_loans,
        'approved_loans': approved_loans,
        'pending_loans': pending_loans,
        'rejected_loans': rejected_loans,
        'branch_names': branch_names,
        'branch_counts': branch_counts,
    }
    return render(request, 'home.html', context)

def upload_zones(request):
    """Upload districts (Excel column 'name'). Kept URL name for backward compatibility."""
    if request.method == 'POST' and request.FILES.get('file'):
        file = request.FILES['file']
        fs = FileSystemStorage(location='backup/')
        filename = fs.save(file.name, file)
        file_path = fs.path(filename)
        data = pd.read_excel(file_path, engine='openpyxl')
        for index, row in data.iterrows():
            district, created = District.objects.get_or_create(name=row['name'])
            if created:
                messages.success(request, f'Successfully created district: {district.name}')
            else:
                messages.warning(request, f'District already exists: {district.name}')
        return redirect('upload_zones')
    return render(request, 'backup/upload_zones.html')


def upload_branches(request):
    if request.method == 'POST' and request.FILES.get('file'):
        file = request.FILES['file']
        fs = FileSystemStorage(location='backup/')
        filename = fs.save(file.name, file)
        file_path = fs.path(filename)
        data = pd.read_excel(file_path, engine='openpyxl')
        for index, row in data.iterrows():
            district_name = row.get('district', row.get('zone'))
            branch_name = row['name']
            try:
                district = District.objects.get(name=district_name)
                branch, created = Branch.objects.get_or_create(name=branch_name, district=district)
                if created:
                    messages.success(request, f'Successfully created branch: {branch.name} in district: {district.name}')
                else:
                    messages.warning(request, f'Branch already exists: {branch.name} in district: {district.name}')
            except District.DoesNotExist:
                messages.error(request, f'District does not exist: {district_name}')
        return redirect('upload_branches')
    return render(request, 'backup/upload_branches.html')

def upload_loan_categories(request):
    if request.method == 'POST' and request.FILES['file']:
        file = request.FILES['file']
        fs = FileSystemStorage(location='backup/')
        filename = fs.save(file.name, file)
        file_path = fs.path(filename)

        data = pd.read_excel(file_path, engine='openpyxl')
        for index, row in data.iterrows():
            category_name = row['name']

            loan_category, created = LoanCategory.objects.get_or_create(name=category_name)
            if created:
                messages.success(request, f'Successfully created loan category: {loan_category.name}')
            else:
                messages.warning(request, f'Loan category already exists: {loan_category.name}')

        return redirect('upload_loan_categories')

    return render(request, 'backup/upload_loan_categories.html')

def upload_users(request):
    if request.method == 'POST' and request.FILES.get('file'):
        file = request.FILES['file']
        fs = FileSystemStorage(location='backup/')
        filename = fs.save(file.name, file)
        file_path = fs.path(filename)

        data = pd.read_excel(file_path, engine='openpyxl')
        for index, row in data.iterrows():
            username = row['username']
            email = row['email']
            phone_number = row['phone_number']
            role = row['role']
            district_name = row.get('district', row.get('zone'))
            branch_name = row['branch']
            if str(role).lower() == "loan_officer":
                role = "branch_manager"
            try:
                district = District.objects.get(name=district_name)
                branch = Branch.objects.get(name=branch_name, district=district)
                user, created = CustomUser.objects.get_or_create(
                    username=username,
                    defaults={
                        'email': email,
                        'phone_number': phone_number,
                        'role': role,
                        'district': district,
                        'branch': branch
                    }
                )
                if created:
                    user.set_password('Zemeo@zemeo10')
                    user.save()
                    messages.success(request, f'Successfully created user: {username}')
                else:
                    if getattr(user, 'role', None) == "loan_officer":
                        user.role = "branch_manager"
                        user.save()
                        messages.info(request, f'Updated role for user: {username} → branch_manager')
                    else:
                        messages.warning(request, f'User already exists: {username}')
            except District.DoesNotExist:
                messages.error(request, f'District does not exist: {district_name}')
            except Branch.DoesNotExist:
                messages.error(request, f'Branch does not exist: {branch_name}')

        return redirect('upload_users')

    return render(request, 'backup/upload_users.html')


def upload_loan_requests(request):
    if request.method == 'POST' and request.FILES['file']:
        file = request.FILES['file']
        fs = FileSystemStorage(location='backup/')
        filename = fs.save(file.name, file)
        file_path = fs.path(filename)

        data = pd.read_excel(file_path, engine='openpyxl')
        for index, row in data.iterrows():
            try:
                applicant_name = row['applicant_name']
                email = row['email']
                phone_number = row['phone_number']
                category = LoanCategory.objects.get(name=row['category'])
                collateral = CollateralType.objects.get(name=row['collateral'])
                amount_requested = row['amount_requested']
                reason = row['reason']
                status = str(row['status']).strip().lower()  # normalize
                district = District.objects.get(name=row.get('district', row.get('zone')))
                branch = Branch.objects.get(name=row['branch'], district=district)
                customer_history = row['customer_history']
                date_requested = row['date_requested']

                # Default approvals
                operation_manager_approval = False
                finance_approval = False

                # If Excel says "Approved", mark both approvals True
                if status == "approved":
                    operation_manager_approval = True
                    finance_approval = True

                LoanRequest.objects.create(
                    loan_request_id=generate_incremental_loan_request_id(),
                    applicant_name=applicant_name,
                    email=email,
                    phone_number=phone_number,
                    category=category,
                    collateral=collateral,
                    amount_requested=amount_requested,
                    reason=reason,
                    status=status.capitalize(),   # keep proper case
                    district=district,
                    branch=branch,
                    customer_history=customer_history,
                    date_requested=date_requested,
                    operation_manager_approval=operation_manager_approval,
                    finance_approval=finance_approval
                )

                messages.success(request, f'Successfully imported loan request for: {applicant_name}')

            except LoanCategory.DoesNotExist:
                messages.error(request, f'Loan category does not exist: {category}')
            except CollateralType.DoesNotExist:
                messages.error(request, f'Collateral does not exist: {collateral}')
            except Branch.DoesNotExist:
                messages.error(request, f'Branch does not exist: {branch}')

        return redirect('upload_loan_requests')

    return render(request, 'backup/upload_loan_requests.html')


def upload_collaterals(request):
    if request.method == 'POST' and request.FILES['file']:
        file = request.FILES['file']
        fs = FileSystemStorage(location='backup/')
        filename = fs.save(file.name, file)
        file_path = fs.path(filename)

        data = pd.read_excel(file_path, engine='openpyxl')
        for index, row in data.iterrows():
            collateral_name = row['collateral']

            collateral, created = CollateralType.objects.get_or_create(name=collateral_name)
            if created:
                messages.success(request, f'Successfully created collateral: {collateral}')
            else:
                messages.warning(request, f'Collateral already exists: {collateral}')

        return redirect('upload_collaterals')

    return render(request, 'backup/upload_collaterals.html')