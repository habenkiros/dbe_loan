"""Submit online applications into the core loan queue."""

from __future__ import annotations

from typing import Tuple

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from applicant_portal.security import portal_enabled, processing_fee_amount  # noqa: F401


def default_collateral_type(category=None):
    from loans.models import CollateralType
    from loans.registration import collateral_for_category

    first = collateral_for_category(category).first()
    if first:
        return first
    obj, _ = CollateralType.objects.get_or_create(
        name='To be determined (online apply)',
    )
    return obj


def missing_required_documents(application) -> list:
    from loans.document_checklist import checklist_for_category, required_items

    if not application.category_id:
        return ['Loan product not selected']
    checklist = checklist_for_category(application.category)
    have = set(
        application.documents.values_list('document_type_id', flat=True),
    )
    return [i.name for i in required_items(checklist) if i.id not in have]


def can_proceed_to_payment(application) -> Tuple[bool, str]:
    from applicant_portal.access import ACTOR_INSTITUTION, actor_kind_of

    if not application.category_id or not application.branch_id:
        return False, 'Complete product, branch, and amount first.'
    if not application.collateral_id and actor_kind_of(application.applicant) != ACTOR_INSTITUTION:
        return False, 'Select a collateral type.'
    if not application.amount_requested or application.amount_requested <= 0:
        return False, 'Enter a valid amount requested.'
    if not (application.applicant_name or '').strip():
        return False, 'Enter applicant name.'
    if not (application.phone_number or '').strip():
        return False, 'Enter phone number.'
    if not (application.reason or '').strip():
        return False, 'Enter loan purpose / reason.'
    missing = missing_required_documents(application)
    if missing:
        return False, 'Upload required documents: ' + ', '.join(missing)
    from loans.kyc_identity import identity_fee_blockers
    fee_blocks = identity_fee_blockers(application)
    if fee_blocks:
        return False, fee_blocks[0]
    return True, ''


def can_submit(application) -> Tuple[bool, str]:
    ok, reason = can_proceed_to_payment(application)
    if not ok:
        return False, reason
    if not application.payment_satisfied():
        return False, 'Pay the processing fee before submitting.'
    if application.status == application.STATUS_SUBMITTED and application.loan_request_id:
        return False, 'Already submitted.'
    return True, ''


@transaction.atomic
def mark_fee_paid(
    application,
    *,
    method: str = 'demo',
    reference: str = '',
    waive: bool = False,
) -> None:
    if application.status == application.STATUS_SUBMITTED and application.loan_request_id:
        raise ValueError('Application already submitted.')
    if application.processing_fee_amount <= 0 or waive:
        application.payment_status = application.PAY_WAIVED
    else:
        application.payment_status = application.PAY_PAID
    application.payment_method = (method or 'demo')[:40]
    application.payment_reference = (reference or f'DEMO-{application.public_id.hex[:10].upper()}')[:64]
    application.payment_paid_at = timezone.now()
    if application.status in (application.STATUS_DOCUMENTS, application.STATUS_DRAFT):
        application.status = application.STATUS_PAYMENT
    application.save(update_fields=[
        'payment_status', 'payment_method', 'payment_reference', 'payment_paid_at',
        'status', 'updated_at',
    ])
    from django.conf import settings
    if getattr(settings, 'DECSI_AUTO_QUEUE_ON_PAID', True) and not application.loan_request_id:
        ok, _ = can_submit(application)
        if ok:
            submit_online_application(application)


@transaction.atomic
def submit_online_application(application) -> object:
    """Create LoanRequest + copy documents; return loan."""
    from loans.models import LoanRequest
    from loans.ids import generate_incremental_loan_request_id
    from applicant_portal.notify import assign_default_officer

    ok, reason = can_submit(application)
    if not ok:
        raise ValueError(reason)

    application = type(application).objects.select_for_update().get(pk=application.pk)
    application = (
        type(application).objects
        .select_related('category', 'branch', 'collateral', 'applicant')
        .get(pk=application.pk)
    )
    if application.loan_request_id:
        loan = application.loan_request
        _copy_online_documents(application, loan)
        application.queue_id = loan.loan_request_id
        application.status = application.STATUS_SUBMITTED
        application.submitted_at = timezone.now()
        application.save(update_fields=[
            'queue_id', 'status', 'submitted_at', 'updated_at',
        ])
        _notify_submit(loan)
        return loan

    branch = application.branch
    collateral = application.collateral or default_collateral_type(application.category)
    loan_id = generate_incremental_loan_request_id()

    loan = LoanRequest(
        loan_request_id=loan_id,
        applicant_name=(application.applicant_name or application.applicant.full_name).strip(),
        phone_number=(application.phone_number or application.applicant.phone_number).strip()[:15],
        email=(application.email or application.applicant.email or None) or None,
        customer_number=(application.customer_number or None) or None,
        category=application.category,
        collateral=collateral,
        amount_requested=application.amount_requested,
        reason=application.reason.strip(),
        branch=branch,
        district=getattr(branch, 'district', None),
        origin_level=LoanRequest.ORIGIN_BRANCH,
        customer_history=application.customer_history or 'new',
        source_channel=LoanRequest.SOURCE_ONLINE,
        operation_manager_approval=False,
        queue_approved=False,
    )
    # Carry core-banking snapshot onto the staff loan when present
    profile = {}
    if application.applicant_id and getattr(application.applicant, 'customer_profile_snapshot', None):
        profile = application.applicant.customer_profile_snapshot or {}
    if profile.get('home_address'):
        loan.declared_address_text = str(profile['home_address'])[:2000]
        loan.declared_address_source = 'home'
    if profile.get('name') and not (application.applicant_name or '').strip():
        loan.applicant_name = str(profile['name'])[:255]
    from loans.services.customer import attach_profile_snapshot_to_loan
    attach_profile_snapshot_to_loan(loan, profile)
    loan.save()
    try:
        from loans.kyc_desk import ensure_intake_screenings
        ensure_intake_screenings(loan)
    except Exception:
        pass
    assign_default_officer(loan)
    _attach_identity_case(application, loan)
    _copy_online_documents(application, loan)

    application.loan_request = loan
    application.queue_id = loan.loan_request_id
    application.status = application.STATUS_SUBMITTED
    application.submitted_at = timezone.now()
    application.save(update_fields=[
        'loan_request', 'queue_id', 'status', 'submitted_at', 'updated_at',
    ])
    _notify_submit(loan)
    return loan


def ensure_working_loan(application):
    """Mint a LoanRequest early so applicants can fill product overlays before fee/submit."""
    from loans.models import LoanRequest
    from loans.ids import generate_incremental_loan_request_id
    from applicant_portal.notify import assign_default_officer

    if application.loan_request_id:
        return application.loan_request
    if not application.category_id or not application.branch_id:
        return None
    branch = application.branch
    loan = LoanRequest(
        loan_request_id=generate_incremental_loan_request_id(),
        applicant_name=(application.applicant_name or application.applicant.full_name).strip(),
        phone_number=(application.phone_number or application.applicant.phone_number).strip()[:15],
        email=(application.email or application.applicant.email or None) or None,
        customer_number=(application.customer_number or None) or None,
        category=application.category,
        collateral=application.collateral or default_collateral_type(application.category),
        amount_requested=application.amount_requested or 0,
        reason=(application.reason or '').strip() or 'Digital apply — product file in progress',
        branch=branch,
        district=getattr(branch, 'district', None),
        origin_level=LoanRequest.ORIGIN_BRANCH,
        customer_history=application.customer_history or 'new',
        source_channel=LoanRequest.SOURCE_ONLINE,
        operation_manager_approval=False,
        queue_approved=False,
    )
    acct = application.applicant
    if getattr(acct, 'institution_name', ''):
        loan.applicant_name = (acct.institution_name or loan.applicant_name)[:255]
    loan.save()
    try:
        from loans.kyc_desk import ensure_intake_screenings
        ensure_intake_screenings(loan)
    except Exception:
        pass
    assign_default_officer(loan)
    application.loan_request = loan
    application.queue_id = loan.loan_request_id
    application.save(update_fields=['loan_request', 'queue_id', 'updated_at'])
    _attach_identity_case(application, loan)
    return loan


def _attach_identity_case(application, loan) -> None:
    try:
        from loans.kyc_identity import ensure_identity_case, recompute_identity_case
        case = ensure_identity_case(loan_request=loan, online_application=application)
        recompute_identity_case(case)
    except Exception:
        pass


def sync_portal_document_to_loan(online_doc, loan) -> None:
    """Attach or refresh the staff-side LoanRequestDocument for a portal upload."""
    from loans.models import LoanRequestDocument
    from loans.services.document_auth import (
        apply_saved_checks_to_loan_document,
        replace_documents_for_type,
        run_automated_document_checks,
    )

    if loan is None or not online_doc.file:
        return
    existing = LoanRequestDocument.objects.filter(
        loan_request=loan, document_type_id=online_doc.document_type_id,
    ).first()
    sha = online_doc.file_sha256 or ''
    if existing and sha and existing.file_sha256 == sha and existing.automated_checks:
        return
    replace_documents_for_type(loan, online_doc.document_type)
    online_doc.file.open('rb')
    try:
        raw = online_doc.file.read()
    finally:
        online_doc.file.close()
    name = online_doc.original_filename or online_doc.file.name.split('/')[-1]
    doc = LoanRequestDocument(
        loan_request=loan,
        document_type=online_doc.document_type,
        original_filename=name,
        file_size=online_doc.file_size or len(raw),
        uploaded_by=None,
    )
    doc.file.save(name, ContentFile(raw), save=False)
    doc.save()
    if online_doc.automated_checks and sha:
        apply_saved_checks_to_loan_document(
            doc, online_doc.automated_checks, sha256=sha,
        )
        doc.quality_score = online_doc.quality_score
        doc.authenticity_score = online_doc.authenticity_score
        if online_doc.quality_score is not None or online_doc.authenticity_score is not None:
            doc.save(update_fields=['quality_score', 'authenticity_score'])
    else:
        try:
            run_automated_document_checks(doc)
            online_doc.automated_checks = doc.automated_checks or {}
            online_doc.file_sha256 = doc.file_sha256
            online_doc.auth_status = doc.auth_status
            online_doc.quality_score = doc.quality_score
            online_doc.authenticity_score = doc.authenticity_score
            online_doc.save(update_fields=[
                'automated_checks', 'file_sha256', 'auth_status',
                'quality_score', 'authenticity_score',
            ])
        except Exception:
            pass


def _copy_online_documents(application, loan) -> None:
    from loans.models import LoanRequestDocument
    from loans.services.document_auth import (
        apply_saved_checks_to_loan_document,
        run_automated_document_checks,
    )

    have = {
        d.document_type_id: d
        for d in loan.application_documents.all()
    }
    for online_doc in application.documents.select_related('document_type'):
        if not online_doc.file:
            continue
        existing = have.get(online_doc.document_type_id)
        sha = online_doc.file_sha256 or ''
        if existing and sha and existing.file_sha256 == sha:
            if not existing.automated_checks and online_doc.automated_checks:
                apply_saved_checks_to_loan_document(
                    existing, online_doc.automated_checks, sha256=sha,
                )
            continue
        if existing:
            continue
        online_doc.file.open('rb')
        try:
            raw = online_doc.file.read()
        finally:
            online_doc.file.close()
        name = online_doc.original_filename or online_doc.file.name.split('/')[-1]
        doc = LoanRequestDocument(
            loan_request=loan,
            document_type=online_doc.document_type,
            original_filename=name,
            file_size=online_doc.file_size or len(raw),
            uploaded_by=None,
        )
        doc.file.save(name, ContentFile(raw), save=False)
        doc.save()
        if online_doc.automated_checks and sha:
            apply_saved_checks_to_loan_document(
                doc, online_doc.automated_checks, sha256=sha,
            )
        else:
            try:
                run_automated_document_checks(doc)
            except Exception:
                pass
    try:
        from loans.services.document_extraction_defaults import sync_sheet1_from_documents
        sync_sheet1_from_documents(loan, only_empty=True)
    except Exception:
        pass
    _attach_identity_case(application, loan)


def _notify_submit(loan) -> None:
    from applicant_portal.notify import notify_applicant_loan_event, notify_staff_online_intake

    try:
        from loans.compliance.case_engine import screen_loan_and_open_case
        from loans.models import ComplianceCase
        screen_loan_and_open_case(
            loan,
            source=ComplianceCase.SOURCE_DIGITAL_APPLY,
        )
    except Exception:
        pass
    try:
        notify_staff_online_intake(loan)
    except Exception:
        pass
    try:
        notify_applicant_loan_event(loan, event='requested')
    except Exception:
        pass


def withdraw_application(application, *, reason: str = '') -> None:
    from applicant_portal.notify import cancel_submitted_application, notify_applicant

    if application.loan_request_id:
        loan = application.loan_request
        advanced = bool(
            loan
            and (
                loan.queue_approved
                or loan.appraisal_completed_at
                or getattr(loan, 'collateral_submitted_at', None)
                or loan.disbursed_at
            )
        )
        if advanced:
            raise ValueError(
                'This application is already being processed and cannot be withdrawn online. '
                'Contact your branch.',
            )
    cancel_submitted_application(application, reason=reason or 'Withdrawn by applicant')
    try:
        notify_applicant(
            application.applicant,
            title='Application withdrawn',
            message=reason or 'You withdrew this application.',
            kind='warn',
            application=application,
        )
    except Exception:
        pass
