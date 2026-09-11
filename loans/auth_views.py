"""Staff login with lockout + TOTP MFA + password reset/change + audit export."""
from __future__ import annotations

import base64
import io
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_backends, login, update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import PasswordChangeForm, PasswordResetForm, SetPasswordForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordChangeView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from .middleware import SESSION_LAST_ACTIVITY, idle_timeout_seconds
from .models import CustomUser, SecurityAuditLog
from .security import (
    SESSION_MFA_BACKEND,
    SESSION_MFA_SETUP_SECRET,
    SESSION_MFA_USER_ID,
    clear_user_lockout,
    encrypt_mfa_secret,
    generate_mfa_secret,
    is_ip_locked,
    lockout_message,
    log_security_event,
    mfa_required,
    provisioning_uri,
    register_failed_login,
    register_successful_password,
    user_mfa_secret,
    verify_totp,
)
from .security_export import audit_csv_response, audit_xlsx_response, parse_audit_filters


def _qr_data_uri(otpauth_uri: str) -> str:
    try:
        import qrcode
    except ImportError:
        return ''
    img = qrcode.make(otpauth_uri)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    return f'data:image/png;base64,{b64}'


def _auth_backend_path(user) -> str:
    backend = getattr(user, 'backend', None)
    if backend:
        return backend
    backends = get_backends()
    return backends[0].__module__ + '.' + backends[0].__class__.__name__ if backends else ''


@method_decorator(ensure_csrf_cookie, name='dispatch')
class StaffLoginView(LoginView):
    template_name = 'login.html'
    # Do not auto-follow ?next= for users who are already signed in.
    # Permission denials redirect here with next=…; following that next causes
    # ERR_TOO_MANY_REDIRECTS (login → denied page → login). Successful POST
    # still honors next via get_success_url().
    redirect_authenticated_user = False

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(settings.LOGIN_REDIRECT_URL)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['mfa_required'] = mfa_required()
        ctx['auth_error'] = self.request.session.pop('auth_error', None)
        return ctx

    def post(self, request, *args, **kwargs):
        if is_ip_locked(request):
            request.session['auth_error'] = lockout_message()
            log_security_event(
                SecurityAuditLog.EVT_LOGIN_LOCKED,
                request=request,
                username=request.POST.get('username', ''),
                detail={'reason': 'ip_lockout'},
            )
            return redirect('login')

        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        user_obj = CustomUser.objects.filter(username__iexact=username).first()
        auth_username = user_obj.username if user_obj else username

        if user_obj and user_obj.is_login_locked():
            request.session['auth_error'] = lockout_message()
            log_security_event(
                SecurityAuditLog.EVT_LOGIN_LOCKED,
                request=request,
                user=user_obj,
                username=username,
                detail={'reason': 'user_lockout'},
            )
            return redirect('login')

        user = authenticate(request, username=auth_username, password=password)
        if user is None:
            register_failed_login(user_obj, request, username)
            request.session['auth_error'] = 'Invalid username or password.'
            return redirect('login')

        if not user.is_active:
            register_failed_login(user, request, username)
            request.session['auth_error'] = 'This account is disabled.'
            return redirect('login')

        from loans.delegation import principal_locked_out_by_delegation, principal_lockout_message
        locked, ends_at, _ = principal_locked_out_by_delegation(user)
        if locked:
            request.session['auth_error'] = principal_lockout_message(ends_at)
            log_security_event(
                SecurityAuditLog.EVT_LOGIN_LOCKED,
                request=request,
                user=user,
                username=username,
                detail={'reason': 'delegation_cover_active', 'ends_at': ends_at.isoformat() if ends_at else None},
            )
            return redirect('login')

        register_successful_password(user, request)
        needs_mfa = bool(user.mfa_enabled) or mfa_required()

        if needs_mfa and user.mfa_enabled:
            request.session[SESSION_MFA_USER_ID] = user.pk
            request.session[SESSION_MFA_BACKEND] = _auth_backend_path(user)
            request.session.cycle_key()
            log_security_event(
                SecurityAuditLog.EVT_MFA_CHALLENGE,
                request=request,
                user=user,
                username=user.username,
            )
            return redirect('mfa_verify')

        if needs_mfa and not user.mfa_enabled:
            request.session[SESSION_MFA_USER_ID] = user.pk
            request.session[SESSION_MFA_BACKEND] = _auth_backend_path(user)
            request.session.cycle_key()
            return redirect('mfa_setup')

        login(request, user, backend=_auth_backend_path(user))
        request.session[SESSION_LAST_ACTIVITY] = int(time.time())
        log_security_event(
            SecurityAuditLog.EVT_LOGIN_SUCCESS,
            request=request,
            user=user,
            username=user.username,
        )
        return redirect(self.get_success_url())


class StaffLogoutView(LogoutView):
    next_page = '/hub/login/'

    def dispatch(self, request, *args, **kwargs):
        user = request.user if getattr(request, 'user', None) and request.user.is_authenticated else None
        if user:
            log_security_event(
                SecurityAuditLog.EVT_LOGOUT,
                request=request,
                user=user,
                username=user.username,
            )
        request.session.pop(SESSION_MFA_USER_ID, None)
        request.session.pop(SESSION_MFA_BACKEND, None)
        request.session.pop(SESSION_MFA_SETUP_SECRET, None)
        return super().dispatch(request, *args, **kwargs)


def _pending_mfa_user(request):
    uid = request.session.get(SESSION_MFA_USER_ID)
    if not uid:
        return None
    return CustomUser.objects.filter(pk=uid, is_active=True).first()


@ensure_csrf_cookie
@require_http_methods(['GET', 'POST'])
def mfa_verify(request):
    user = _pending_mfa_user(request)
    if not user:
        messages.error(request, 'Your login session expired. Please sign in again.')
        return redirect('login')

    error = ''
    if request.method == 'POST':
        code = request.POST.get('otp_code') or ''
        secret = user_mfa_secret(user)
        if secret and verify_totp(secret, code):
            from loans.delegation import principal_locked_out_by_delegation, principal_lockout_message
            locked, ends_at, _ = principal_locked_out_by_delegation(user)
            if locked:
                request.session.pop(SESSION_MFA_USER_ID, None)
                request.session.pop(SESSION_MFA_BACKEND, None)
                messages.warning(request, principal_lockout_message(ends_at))
                return redirect('login')
            backend = request.session.get(SESSION_MFA_BACKEND) or _auth_backend_path(user)
            request.session.pop(SESSION_MFA_USER_ID, None)
            request.session.pop(SESSION_MFA_BACKEND, None)
            login(request, user, backend=backend)
            request.session[SESSION_LAST_ACTIVITY] = int(time.time())
            log_security_event(
                SecurityAuditLog.EVT_MFA_SUCCESS,
                request=request,
                user=user,
                username=user.username,
            )
            log_security_event(
                SecurityAuditLog.EVT_LOGIN_SUCCESS,
                request=request,
                user=user,
                username=user.username,
                detail={'via': 'mfa'},
            )
            return redirect(settings.LOGIN_REDIRECT_URL)
        log_security_event(
            SecurityAuditLog.EVT_MFA_FAILED,
            request=request,
            user=user,
            username=user.username,
        )
        error = 'Invalid authentication code.'

    return render(request, 'security/mfa_verify.html', {
        'error': error,
        'username': user.username,
    })


@ensure_csrf_cookie
@require_http_methods(['GET', 'POST'])
def mfa_setup(request):
    pending = _pending_mfa_user(request)
    if request.user.is_authenticated:
        user = request.user
        pending_flow = False
    elif pending:
        user = pending
        pending_flow = True
    else:
        messages.error(request, 'Please sign in first.')
        return redirect('login')

    if request.method == 'GET' or SESSION_MFA_SETUP_SECRET not in request.session:
        secret = generate_mfa_secret()
        request.session[SESSION_MFA_SETUP_SECRET] = secret
    else:
        secret = request.session.get(SESSION_MFA_SETUP_SECRET) or generate_mfa_secret()
        request.session[SESSION_MFA_SETUP_SECRET] = secret

    uri = provisioning_uri(user, secret)
    error = ''

    if request.method == 'POST':
        code = request.POST.get('otp_code') or ''
        if verify_totp(secret, code):
            user.mfa_secret_encrypted = encrypt_mfa_secret(secret)
            user.mfa_enabled = True
            user.save(update_fields=['mfa_secret_encrypted', 'mfa_enabled'])
            request.session.pop(SESSION_MFA_SETUP_SECRET, None)
            log_security_event(
                SecurityAuditLog.EVT_MFA_ENROLLED,
                request=request,
                user=user,
                username=user.username,
            )
            if pending_flow:
                backend = request.session.get(SESSION_MFA_BACKEND) or _auth_backend_path(user)
                request.session.pop(SESSION_MFA_USER_ID, None)
                request.session.pop(SESSION_MFA_BACKEND, None)
                login(request, user, backend=backend)
                request.session[SESSION_LAST_ACTIVITY] = int(time.time())
                log_security_event(
                    SecurityAuditLog.EVT_LOGIN_SUCCESS,
                    request=request,
                    user=user,
                    username=user.username,
                    detail={'via': 'mfa_enroll'},
                )
                messages.success(request, 'Two-factor authentication is now enabled.')
                return redirect(settings.LOGIN_REDIRECT_URL)
            messages.success(request, 'Two-factor authentication is now enabled.')
            return redirect('mfa_setup')
        error = 'Invalid code — scan the QR again and enter a fresh 6-digit code.'
        log_security_event(
            SecurityAuditLog.EVT_MFA_FAILED,
            request=request,
            user=user,
            username=user.username,
            detail={'during': 'enroll'},
        )

    return render(request, 'security/mfa_setup.html', {
        'error': error,
        'username': user.username,
        'secret': secret,
        'qr_data_uri': _qr_data_uri(uri),
        'otpauth_uri': uri,
        'pending_flow': pending_flow,
        'mfa_enabled': user.mfa_enabled,
    })


@login_required
@require_http_methods(['POST'])
def mfa_disable(request):
    if mfa_required() and not request.user.is_superuser:
        messages.error(request, 'MFA is required by policy and cannot be disabled.')
        return redirect('mfa_setup')
    code = request.POST.get('otp_code') or ''
    secret = user_mfa_secret(request.user)
    if not (secret and verify_totp(secret, code)):
        messages.error(request, 'Enter a valid authenticator code to disable MFA.')
        return redirect('mfa_setup')
    request.user.mfa_enabled = False
    request.user.mfa_secret_encrypted = ''
    request.user.save(update_fields=['mfa_enabled', 'mfa_secret_encrypted'])
    log_security_event(
        SecurityAuditLog.EVT_MFA_DISABLED,
        request=request,
        user=request.user,
        username=request.user.username,
    )
    messages.success(request, 'Two-factor authentication disabled.')
    return redirect('mfa_setup')


class AuditedPasswordResetForm(PasswordResetForm):
    def save(self, *args, **kwargs):
        request = kwargs.get('request')
        email = self.cleaned_data['email']
        users = list(self.get_users(email))
        for u in users:
            log_security_event(
                SecurityAuditLog.EVT_PASSWORD_RESET_REQUESTED,
                request=request,
                user=u,
                username=u.username,
                detail={'email': email},
            )
        if not users:
            log_security_event(
                SecurityAuditLog.EVT_PASSWORD_RESET_REQUESTED,
                request=request,
                username='',
                detail={'email': email, 'matched_users': 0},
            )
        return super().save(*args, **kwargs)


class StaffPasswordResetView(PasswordResetView):
    template_name = 'security/password_reset_form.html'
    email_template_name = 'security/password_reset_email.txt'
    subject_template_name = 'security/password_reset_subject.txt'
    form_class = AuditedPasswordResetForm
    success_url = reverse_lazy('password_reset_done')


class StaffPasswordResetDoneView(PasswordResetDoneView):
    template_name = 'security/password_reset_done.html'


class StaffPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'security/password_reset_confirm.html'
    success_url = reverse_lazy('password_reset_complete')
    form_class = SetPasswordForm

    def form_valid(self, form):
        response = super().form_valid(form)
        user = self.user
        log_security_event(
            SecurityAuditLog.EVT_PASSWORD_RESET_COMPLETED,
            request=self.request,
            user=user,
            username=getattr(user, 'username', ''),
        )
        if user:
            clear_user_lockout(user)
        return response


class StaffPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = 'security/password_reset_complete.html'


class StaffPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    template_name = 'security/password_change.html'
    success_url = reverse_lazy('password_change_done')
    form_class = PasswordChangeForm

    def form_valid(self, form):
        response = super().form_valid(form)
        update_session_auth_hash(self.request, form.user)
        log_security_event(
            SecurityAuditLog.EVT_PASSWORD_CHANGED,
            request=self.request,
            user=self.request.user,
            username=self.request.user.username,
        )
        messages.success(self.request, 'Your password was changed successfully.')
        return response


@login_required
def password_change_done(request):
    return render(request, 'security/password_change_done.html')


@login_required
@require_POST
def session_keepalive(request):
    now = int(time.time())
    request.session[SESSION_LAST_ACTIVITY] = now
    request.session.modified = True
    timeout = idle_timeout_seconds()
    return JsonResponse({
        'ok': True,
        'server_time': now,
        'idle_timeout': timeout,
        'expires_in': timeout,
    })


def _can_view_security_audit(user) -> bool:
    return bool(
        user.is_authenticated
        and (
            user.is_superuser
            or user.role in ('admin', 'auditor', 'risk_compliance', 'vp_it')
        )
    )


@login_required
@user_passes_test(_can_view_security_audit)
def security_audit_list(request):
    qs, meta = parse_audit_filters(request.GET)
    from loans.pagination import page_querystring, paginate
    page_obj = paginate(request, qs)
    return render(request, 'security/audit_log_list.html', {
        'events': page_obj,
        'page_obj': page_obj,
        'filters': meta,
        'event_choices': SecurityAuditLog.EVT_CHOICES,
        'result_count': page_obj.paginator.count,
        'export_query': request.GET.urlencode(),
        'querystring': page_querystring(request),
    })


@login_required
@user_passes_test(_can_view_security_audit)
def security_audit_export(request):
    qs, meta = parse_audit_filters(request.GET)
    qs = qs[:20000]
    fmt = (request.GET.get('format') or 'csv').lower()
    log_security_event(
        SecurityAuditLog.EVT_AUDIT_EXPORTED,
        request=request,
        user=request.user,
        username=request.user.username,
        detail={'format': fmt, 'filters': meta},
    )
    if fmt in ('xlsx', 'excel', 'xls'):
        return audit_xlsx_response(qs)
    return audit_csv_response(qs)


@login_required
@user_passes_test(lambda u: u.is_superuser or u.role in ('admin', 'vp_it'))
@require_http_methods(['POST'])
def unlock_user(request, user_id):
    target = get_object_or_404(CustomUser, pk=user_id)
    clear_user_lockout(target)
    log_security_event(
        SecurityAuditLog.EVT_USER_UNLOCKED,
        request=request,
        user=request.user,
        username=request.user.username,
        detail={'unlocked_user': target.username, 'unlocked_user_id': target.pk},
    )
    messages.success(request, f'Unlocked account “{target.username}”.')
    return redirect('edit_user', user_id=target.pk)
