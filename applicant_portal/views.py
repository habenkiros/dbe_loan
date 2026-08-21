"""Applicant digital-apply portal views (session identity, not staff auth)."""

from __future__ import annotations

from django.contrib import messages
from django.core.files.base import ContentFile
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from applicant_portal.auth import (
    applicant_login_required,
    get_portal_applicant,
    login_applicant,
    logout_applicant,
)
from applicant_portal.forms import (
    ApplicantChangePasswordForm,
    ApplicantLoginForm,
    ApplicantRegisterForm,
    ApplicationDetailsForm,
    PasswordResetConfirmForm,
    PasswordResetRequestForm,
)
from applicant_portal.models import (
    ApplicantAuthEvent,
    ApplicantNotification,
    OnlineApplication,
    OnlineApplicationDocument,
)
from applicant_portal.security import (
    check_register_rate,
    log_auth_event,
    note_register_attempt,
    portal_enabled,
    processing_fee_amount,
)
from applicant_portal.services import (
    can_proceed_to_payment,
    can_submit,
    missing_required_documents,
    submit_online_application,
    withdraw_application,
)


def _portal_or_closed(request):
    if not portal_enabled():
        return render(request, 'applicant_portal/closed.html', status=503)
    return None


def _get_owned_app(request, public_id) -> OnlineApplication:
    return get_object_or_404(
        OnlineApplication.objects.select_related(
            'category', 'branch', 'collateral', 'loan_request', 'applicant',
            'loan_request__category', 'loan_request__branch',
            'loan_request__assigned_loan_officer',
        ),
        public_id=public_id,
        applicant=request.portal_applicant,
    )


def _draft_continue_url(app) -> str:
    from django.urls import reverse

    if app.loan_request_id:
        return ''
    if app.status == OnlineApplication.STATUS_DOCUMENTS and app.category_id:
        return reverse('applicant_portal:apply_documents', args=[app.public_id])
    if app.status == OnlineApplication.STATUS_PAYMENT:
        return reverse('applicant_portal:apply_payment', args=[app.public_id])
    if app.status == OnlineApplication.STATUS_SUBMITTED and not app.loan_request_id:
        return reverse('applicant_portal:apply_submit', args=[app.public_id])
    return reverse('applicant_portal:apply_details', args=[app.public_id])


def landing(request):
    closed = _portal_or_closed(request)
    if closed:
        return closed
    account = get_portal_applicant(request)
    if account:
        return redirect('applicant_portal:home')
    return render(request, 'applicant_portal/landing.html')


@require_http_methods(['GET', 'POST'])
def register(request):
    closed = _portal_or_closed(request)
    if closed:
        return closed
    if get_portal_applicant(request):
        return redirect('applicant_portal:home')

    form = ApplicantRegisterForm(request.POST or None)
    if request.method == 'POST':
        ok, rate_msg = check_register_rate(request)
        if not ok:
            messages.error(request, rate_msg)
            return render(request, 'applicant_portal/register.html', {
                'form': form,
                'password_hints': form.fields['password'].help_text,
            })
        note_register_attempt(request)
        if form.is_valid():
            account = form.save()
            log_auth_event(
                ApplicantAuthEvent.EVT_REGISTER,
                request=request,
                account=account,
                phone=account.phone_number,
            )
            login_applicant(request, account)
            messages.success(request, 'Account created. Start your loan application when ready.')
            return redirect('applicant_portal:home')
    return render(request, 'applicant_portal/register.html', {
        'form': form,
        'password_hints': form.fields['password'].help_text,
    })


@require_http_methods(['GET', 'POST'])
def login_view(request):
    closed = _portal_or_closed(request)
    if closed:
        return closed
    if get_portal_applicant(request):
        return redirect('applicant_portal:home')

    form = ApplicantLoginForm(request.POST or None, request=request)
    if request.method == 'POST' and form.is_valid():
        login_applicant(request, form.account)
        messages.success(request, f'Welcome back, {form.account.full_name}.')
        next_url = (request.GET.get('next') or '').strip()
        if next_url.startswith('/') and not next_url.startswith('//'):
            return redirect(next_url)
        return redirect('applicant_portal:home')
    return render(request, 'applicant_portal/login.html', {'form': form})


def logout_view(request):
    account = get_portal_applicant(request)
    logout_applicant(request, account=account, reason='logout')
    messages.info(request, 'Signed out.')
    return redirect('applicant_portal:landing')


@applicant_login_required
@require_http_methods(['GET', 'POST'])
def change_password(request):
    closed = _portal_or_closed(request)
    if closed:
        return closed
    form = ApplicantChangePasswordForm(
        request.POST or None,
        account=request.portal_applicant,
    )
    if request.method == 'POST' and form.is_valid():
        form.save()
        log_auth_event(
            ApplicantAuthEvent.EVT_PASSWORD_CHANGED,
            request=request,
            account=request.portal_applicant,
            phone=request.portal_applicant.phone_number,
        )
        # Re-login with fresh session after password change
        login_applicant(request, request.portal_applicant)
        messages.success(request, 'Password updated.')
        return redirect('applicant_portal:home')
    return render(request, 'applicant_portal/change_password.html', {
        'form': form,
        'password_hints': form.fields['new_password'].help_text,
    })


@applicant_login_required
def home(request):
    closed = _portal_or_closed(request)
    if closed:
        return closed
    apps = list(
        OnlineApplication.objects
        .filter(applicant=request.portal_applicant)
        .exclude(status=OnlineApplication.STATUS_CANCELLED)
        .select_related(
            'category', 'branch', 'loan_request',
            'loan_request__category', 'loan_request__branch',
            'loan_request__assigned_loan_officer',
        )
        .order_by('-updated_at')[:40]
    )
    from applicant_portal.status import enrich_applications

    return render(request, 'applicant_portal/home.html', {
        'rows': enrich_applications(apps),
        'applicant': request.portal_applicant,
    })


@applicant_login_required
@require_http_methods(['GET'])
def notices(request):
    """Dedicated notices inbox — not shown on the applications dashboard."""
    closed = _portal_or_closed(request)
    if closed:
        return closed
    qs = (
        ApplicantNotification.objects
        .filter(account=request.portal_applicant)
        .select_related('application')
        .order_by('-created_at')[:80]
    )
    return render(request, 'applicant_portal/notices.html', {
        'applicant': request.portal_applicant,
        'notices': list(qs),
        'unread_count': sum(1 for n in qs if not n.is_read),
    })


@applicant_login_required
@require_http_methods(['GET', 'POST'])
def apply_start(request):
    closed = _portal_or_closed(request)
    if closed:
        return closed
    account = request.portal_applicant
    if request.method == 'POST':
        from loans.services.customer import refresh_customer_profile_for_account

        try:
            refresh_customer_profile_for_account(account)
            account.refresh_from_db()
        except Exception:
            pass
        profile = account.customer_profile_snapshot or {}
        app = OnlineApplication.objects.create(
            applicant=account,
            applicant_name=(profile.get('name') or account.full_name or '')[:255],
            phone_number=account.phone_number,
            email=(profile.get('email') or account.email or '')[:254],
            customer_number=account.customer_number or '',
            customer_history='existing' if (profile.get('status') or '').upper() not in ('', 'NEW') else 'existing',
            branch=account.preferred_branch,
            processing_fee_amount=processing_fee_amount(),
            status=OnlineApplication.STATUS_DRAFT,
        )
        return redirect('applicant_portal:apply_details', public_id=app.public_id)
    return render(request, 'applicant_portal/apply_start.html', {
        'fee': processing_fee_amount(),
        'profile': account.customer_profile_snapshot or {},
    })


@applicant_login_required
def ajax_branches(request):
    """JSON branches for the selected district (applicant portal cascade)."""
    from django.http import JsonResponse
    from loans.models import Branch

    district_id = request.GET.get('district_id') or request.GET.get('district')
    if not district_id:
        return JsonResponse({'branches': []})
    try:
        district_id = int(district_id)
    except (TypeError, ValueError):
        return JsonResponse({'branches': []})
    qs = Branch.objects.filter(district_id=district_id).order_by('name')
    return JsonResponse({
        'branches': [{'id': b.id, 'name': b.name} for b in qs],
    })


@require_http_methods(['GET'])
def ajax_lookup_customer(request):
    """
    Public (rate-limited) customer lookup for registration prefill.
    Uses DECSI party API when DECSI_BASE_URL is set.
    """
    from django.http import JsonResponse
    from loans.services.customer import customer_api_is_live, portal_customer_lookup
    from applicant_portal.security import (
        check_register_rate,
        normalize_customer_number,
        validate_customer_number_format,
    )

    closed = _portal_or_closed(request)
    if closed:
        return JsonResponse({'ok': False, 'error': 'Portal closed'}, status=503)

    ok_rate, rate_msg = check_register_rate(request)
    if not ok_rate:
        return JsonResponse({'ok': False, 'error': rate_msg}, status=429)

    raw = (request.GET.get('customer_number') or request.GET.get('cn') or '').strip()
    try:
        cn = normalize_customer_number(raw)
        validate_customer_number_format(cn)
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    profile, msg = portal_customer_lookup(cn, require=False)
    if not profile:
        return JsonResponse({
            'ok': False,
            'error': msg or 'Customer not found',
            'live': customer_api_is_live(),
        }, status=404)

    # Do not leak full raw keys publicly; return applicant-useful fields only.
    return JsonResponse({
        'ok': True,
        'live': customer_api_is_live(),
        'message': msg,
        'profile': {
            'customer_number': profile.get('customer_number') or cn,
            'name': profile.get('name') or '',
            'phone_number': profile.get('phone_number') or '',
            'email': profile.get('email') or '',
            'home_address': profile.get('home_address') or '',
            'tin_number': profile.get('tin_number') or '',
            'status': profile.get('status') or '',
            'customer_status': profile.get('customer_status') or '',
            'gender': profile.get('gender') or '',
            'date_of_birth': profile.get('date_of_birth') or '',
            'marital_status': profile.get('marital_status') or '',
            'city': profile.get('city') or '',
            'provider': profile.get('provider') or '',
        },
    })


@applicant_login_required
@require_http_methods(['GET', 'POST'])
def apply_details(request, public_id):
    closed = _portal_or_closed(request)
    if closed:
        return closed
    app = _get_owned_app(request, public_id)
    if app.loan_request_id or app.status == OnlineApplication.STATUS_SUBMITTED:
        return redirect('applicant_portal:apply_status', public_id=app.public_id)

    form = ApplicationDetailsForm(request.POST or None, instance=app)
    if request.method == 'POST' and form.is_valid():
        form.save()
        app.refresh_from_db()
        app.status = OnlineApplication.STATUS_DOCUMENTS
        app.save(update_fields=['status', 'updated_at'])
        messages.success(request, 'Details saved. Upload your documents next.')
        return redirect('applicant_portal:apply_documents', public_id=app.public_id)
    return render(request, 'applicant_portal/apply_details.html', {
        'application': app,
        'form': form,
        'step': 1,
    })


@applicant_login_required
@require_http_methods(['GET', 'POST'])
def apply_documents(request, public_id):
    closed = _portal_or_closed(request)
    if closed:
        return closed
    app = _get_owned_app(request, public_id)
    if app.loan_request_id:
        return redirect('applicant_portal:apply_status', public_id=app.public_id)
    if not app.category_id:
        messages.warning(request, 'Choose a loan product first.')
        return redirect('applicant_portal:apply_details', public_id=app.public_id)

    from loans.document_checklist import checklist_for_category
    from loans.models import LoanApplicationDocumentType
    from loans.services.document_auth import _read_upload_bytes, validate_upload_bytes

    checklist = checklist_for_category(app.category)
    existing = {
        d.document_type_id: d
        for d in app.documents.select_related('document_type')
    }

    if request.method == 'POST':
        action = (request.POST.get('action') or 'upload').strip()
        if action == 'continue':
            ok, reason = can_proceed_to_payment(app)
            if not ok:
                messages.error(request, reason)
            else:
                app.status = OnlineApplication.STATUS_PAYMENT
                app.save(update_fields=['status', 'updated_at'])
                return redirect('applicant_portal:apply_payment', public_id=app.public_id)
        else:
            uploaded = 0
            for key, f in request.FILES.items():
                if not key.startswith('doc_type_') or not f:
                    continue
                try:
                    tid = int(key.replace('doc_type_', ''))
                except ValueError:
                    continue
                if tid not in {i.id for i in checklist}:
                    messages.error(request, 'That document is not required for this loan type.')
                    continue
                try:
                    doc_type = LoanApplicationDocumentType.objects.get(pk=tid)
                except LoanApplicationDocumentType.DoesNotExist:
                    continue
                raw = _read_upload_bytes(f)
                if not raw:
                    messages.error(request, f'{doc_type.name}: could not read file.')
                    continue
                ok, errs = validate_upload_bytes(raw, f.name, doc_type, loan_request=None)
                if not ok:
                    for err in errs:
                        messages.error(request, f'{doc_type.name}: {err}')
                    continue
                OnlineApplicationDocument.objects.filter(
                    application=app, document_type=doc_type,
                ).delete()
                doc = OnlineApplicationDocument(
                    application=app,
                    document_type=doc_type,
                    original_filename=f.name,
                    file_size=len(raw),
                )
                doc.file.save(f.name, ContentFile(raw), save=False)
                doc.save()
                uploaded += 1
            if uploaded:
                app.status = OnlineApplication.STATUS_DOCUMENTS
                app.save(update_fields=['status', 'updated_at'])
                messages.success(request, f'{uploaded} document(s) uploaded.')
            return redirect('applicant_portal:apply_documents', public_id=app.public_id)

    rows = []
    for item in checklist:
        doc = existing.get(item.id)
        rows.append({
            'item': item,
            'document': doc,
            'is_required': item.is_required,
            'have': doc is not None,
        })
    missing = missing_required_documents(app)
    return render(request, 'applicant_portal/apply_documents.html', {
        'application': app,
        'rows': rows,
        'missing': missing,
        'step': 2,
        'can_continue': not missing,
    })


@applicant_login_required
@require_http_methods(['GET', 'POST'])
def apply_payment(request, public_id):
    from applicant_portal.chapa import (
        apply_verified_payment,
        chapa_live_enabled,
        initialize_checkout,
        inline_checkout_config,
        verify_transaction,
    )
    from applicant_portal.notify import notify_applicant

    closed = _portal_or_closed(request)
    if closed:
        return closed
    app = _get_owned_app(request, public_id)
    if app.loan_request_id:
        return redirect('applicant_portal:apply_status', public_id=app.public_id)

    ok, reason = can_proceed_to_payment(app)
    if not ok:
        messages.error(request, reason)
        return redirect('applicant_portal:apply_documents', public_id=app.public_id)

    # Zero-fee: auto mark waived
    fee = app.processing_fee_amount or processing_fee_amount()
    if fee <= 0 and not app.payment_satisfied():
        app.payment_status = OnlineApplication.PAY_WAIVED
        app.payment_method = 'waived'
        app.payment_paid_at = __import__('django.utils.timezone', fromlist=['timezone']).timezone.now()
        app.status = OnlineApplication.STATUS_PAYMENT
        app.save(update_fields=[
            'payment_status', 'payment_method', 'payment_paid_at', 'status', 'updated_at',
        ])
        return redirect('applicant_portal:apply_submit', public_id=app.public_id)

    if request.method == 'POST':
        action = (request.POST.get('action') or 'pay').strip()
        if action == 'pay' and not app.payment_satisfied():
            ok_init, msg, checkout = initialize_checkout(app, request=request)
            if not ok_init:
                messages.error(request, msg)
                return redirect('applicant_portal:apply_payment', public_id=app.public_id)
            if checkout:
                if chapa_live_enabled():
                    messages.success(request, 'Enter your payment details below. You will stay on this page.')
                    return redirect('applicant_portal:apply_payment', public_id=app.public_id)
                return redirect(checkout)
            messages.info(request, msg)
            return redirect('applicant_portal:apply_payment', public_id=app.public_id)
        if action == 'verify' and app.chapa_tx_ref and not app.payment_satisfied():
            ok_v, data = verify_transaction(app.chapa_tx_ref)
            if ok_v:
                apply_verified_payment(app, app.chapa_tx_ref, data)
                notify_applicant(
                    request.portal_applicant,
                    title='Processing fee paid',
                    message=f'Payment confirmed (ref {app.payment_reference or app.chapa_tx_ref}). You may submit.',
                    kind='success',
                    application=app,
                )
                messages.success(request, 'Payment verified. Continue to submit.')
                return redirect('applicant_portal:apply_submit', public_id=app.public_id)
            messages.error(request, 'Payment not confirmed yet. Finish on Chapa, then verify again.')
            return redirect('applicant_portal:apply_payment', public_id=app.public_id)
        if action == 'submit_if_paid' and app.payment_satisfied():
            return redirect('applicant_portal:apply_submit', public_id=app.public_id)

    app.refresh_from_db()
    return render(request, 'applicant_portal/apply_payment.html', {
        'application': app,
        'fee': fee,
        'paid': app.payment_satisfied(),
        'pending': app.payment_status == OnlineApplication.PAY_PENDING,
        'chapa_live': chapa_live_enabled(),
        'chapa_inline': inline_checkout_config(app, request=request) if not app.payment_satisfied() else None,
        'step': 3,
    })


@applicant_login_required
def apply_payment_return(request, public_id):
    """Chapa return_url (and mock checkout landing)."""
    from applicant_portal.chapa import (
        apply_verified_payment,
        tx_ref_from_request,
        verify_transaction,
    )
    from applicant_portal.notify import notify_applicant

    closed = _portal_or_closed(request)
    if closed:
        return closed
    app = _get_owned_app(request, public_id)
    if app.payment_satisfied():
        messages.success(request, 'Fee already recorded.')
        return redirect('applicant_portal:apply_submit', public_id=app.public_id)

    tx_ref = tx_ref_from_request(request, app)
    status = (request.GET.get('status') or '').lower()
    if not tx_ref:
        messages.error(request, 'Missing payment reference.')
        return redirect('applicant_portal:apply_payment', public_id=app.public_id)

    # When Chapa reports cancelled, just return.
    if status in ('cancelled', 'failed', 'error'):
        messages.warning(request, 'Payment was not completed. You can try again.')
        return redirect('applicant_portal:apply_payment', public_id=app.public_id)

    ok_v, data = verify_transaction(tx_ref)
    if ok_v:
        apply_verified_payment(app, tx_ref, data)
        notify_applicant(
            request.portal_applicant,
            title='Processing fee paid',
            message=f'Chapa payment confirmed. Reference: {app.payment_reference or tx_ref}.',
            kind='success',
            application=app,
            also_sms=True,
        )
        messages.success(request, 'Payment successful. Submit your application to the branch queue.')
        return redirect('applicant_portal:apply_submit', public_id=app.public_id)

    messages.warning(
        request,
        'We could not verify the payment yet. If you completed checkout, use “Verify payment”.',
    )
    return redirect('applicant_portal:apply_payment', public_id=app.public_id)


@csrf_exempt
@require_http_methods(['POST', 'GET'])
def chapa_webhook(request):
    """Chapa callback (server-to-server). Requires matching tx_ref."""
    from django.http import HttpResponse, HttpResponseBadRequest
    from applicant_portal.chapa import apply_verified_payment, tx_ref_from_request, verify_transaction
    from applicant_portal.notify import notify_applicant

    tx_ref = tx_ref_from_request(request)
    if request.method == 'GET' and not tx_ref:
        return HttpResponse('ok')

    payload = {}
    if request.method == 'POST':
        if request.content_type and 'application/json' in request.content_type:
            import json
            try:
                payload = json.loads(request.body.decode('utf-8') or '{}')
            except Exception:
                payload = {}
        else:
            payload = request.POST.dict()
        data = payload.get('data') if isinstance(payload.get('data'), dict) else payload
        tx_ref = (
            tx_ref
            or (data.get('tx_ref') or data.get('trx_ref') or payload.get('tx_ref') or '')
        ).strip()

    if not tx_ref:
        return HttpResponseBadRequest('missing tx_ref')

    app = OnlineApplication.objects.filter(chapa_tx_ref=tx_ref).select_related('applicant').first()
    if not app:
        return HttpResponse('unknown', status=404)

    ok_v, verified = verify_transaction(tx_ref)
    if ok_v and not app.payment_satisfied():
        apply_verified_payment(app, tx_ref, verified)
        try:
            notify_applicant(
                app.applicant,
                title='Processing fee paid',
                message=f'Payment confirmed via Chapa (ref {app.payment_reference}).',
                kind='success',
                application=app,
            )
        except Exception:
            pass
    return HttpResponse('ok')


@applicant_login_required
@require_http_methods(['GET', 'POST'])
def apply_submit(request, public_id):
    closed = _portal_or_closed(request)
    if closed:
        return closed
    app = _get_owned_app(request, public_id)
    if app.loan_request_id:
        return redirect('applicant_portal:apply_status', public_id=app.public_id)

    ok, reason = can_submit(app)
    if request.method == 'POST':
        if not ok:
            messages.error(request, reason)
            if 'document' in reason.lower():
                return redirect('applicant_portal:apply_documents', public_id=app.public_id)
            if 'fee' in reason.lower() or 'Pay' in reason:
                return redirect('applicant_portal:apply_payment', public_id=app.public_id)
            return redirect('applicant_portal:apply_details', public_id=app.public_id)
        try:
            loan = submit_online_application(app)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect('applicant_portal:apply_submit', public_id=app.public_id)
        messages.success(
            request,
            f'LOAN REQUESTED. Your queue ID is {loan.loan_request_id}.',
        )
        return redirect('applicant_portal:apply_status', public_id=app.public_id)

    return render(request, 'applicant_portal/apply_submit.html', {
        'application': app,
        'can_submit': ok,
        'block_reason': reason,
        'step': 4,
    })


@applicant_login_required
def apply_status(request, public_id):
    """Loan / application status tracker for the logged-in applicant."""
    closed = _portal_or_closed(request)
    if closed:
        return closed
    app = _get_owned_app(request, public_id)
    from applicant_portal.status import build_applicant_status

    status = build_applicant_status(app)
    return render(request, 'applicant_portal/apply_status.html', {
        'application': app,
        'status': status,
        'continue_url': _draft_continue_url(app) if status.can_continue_draft else '',
        'step': 4 if app.loan_request_id else app.step_index(),
        'can_withdraw': (
            app.status != OnlineApplication.STATUS_CANCELLED
            and (
                not app.loan_request_id
                or not (
                    app.loan_request
                    and (
                        app.loan_request.queue_approved
                        or app.loan_request.appraisal_completed_at
                        or app.loan_request.disbursed_at
                    )
                )
            )
        ),
    })


@applicant_login_required
def apply_schedule(request, public_id):
    """Customer repayment schedule (read-only amortization after credit approval)."""
    closed = _portal_or_closed(request)
    if closed:
        return closed
    app = _get_owned_app(request, public_id)
    from applicant_portal.schedule import build_repayment_schedule
    from applicant_portal.status import build_applicant_status

    status = build_applicant_status(app)
    schedule = build_repayment_schedule(app)
    return render(request, 'applicant_portal/apply_schedule.html', {
        'application': app,
        'status': status,
        'schedule': schedule,
    })


@applicant_login_required
@require_http_methods(['POST'])
def apply_withdraw(request, public_id):
    closed = _portal_or_closed(request)
    if closed:
        return closed
    app = _get_owned_app(request, public_id)
    reason = (request.POST.get('reason') or '').strip()
    try:
        withdraw_application(app, reason=reason)
        messages.info(request, 'Application withdrawn.')
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('applicant_portal:apply_status', public_id=app.public_id)
    return redirect('applicant_portal:home')


@require_http_methods(['GET', 'POST'])
def password_reset_request(request):
    closed = _portal_or_closed(request)
    if closed:
        return closed
    if get_portal_applicant(request):
        return redirect('applicant_portal:home')
    form = PasswordResetRequestForm(request.POST or None)
    debug_code = ''
    if request.method == 'POST' and form.is_valid():
        account = getattr(form, 'account', None)
        # Always soft success to limit enumeration
        if account:
            from applicant_portal.password_reset import issue_password_reset
            from django.conf import settings as dj_settings

            code = issue_password_reset(account, request=request)
            log_auth_event(
                ApplicantAuthEvent.EVT_PASSWORD_RESET_REQUEST,
                request=request,
                account=account,
                phone=account.phone_number,
            )
            if dj_settings.DEBUG:
                debug_code = code
        messages.success(
            request,
            'If that account exists, a reset code was sent to the registered phone (or logged for staff when SMS is not configured).',
        )
        if debug_code:
            messages.info(request, f'DEBUG only — reset code: {debug_code}')
        return redirect('applicant_portal:password_reset_confirm')
    return render(request, 'applicant_portal/password_reset_request.html', {'form': form})


@require_http_methods(['GET', 'POST'])
def password_reset_confirm(request):
    closed = _portal_or_closed(request)
    if closed:
        return closed
    if get_portal_applicant(request):
        return redirect('applicant_portal:home')
    form = PasswordResetConfirmForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        from applicant_portal.password_reset import verify_and_reset_password

        ok = verify_and_reset_password(
            form.account,
            form.cleaned_data['code'],
            form.cleaned_data['new_password'],
        )
        if ok:
            log_auth_event(
                ApplicantAuthEvent.EVT_PASSWORD_RESET_OK,
                request=request,
                account=form.account,
                phone=form.account.phone_number,
            )
            messages.success(request, 'Password updated. You can sign in.')
            return redirect('applicant_portal:login')
        messages.error(request, 'Invalid or expired code.')
    return render(request, 'applicant_portal/password_reset_confirm.html', {
        'form': form,
        'password_hints': form.fields['new_password'].help_text if form else '',
    })


@applicant_login_required
@require_http_methods(['POST'])
def mark_notices_read(request):
    ApplicantNotification.objects.filter(
        account=request.portal_applicant, is_read=False,
    ).update(is_read=True)
    return redirect(request.META.get('HTTP_REFERER') or 'applicant_portal:notices')
