"""Staff hub screens for applicant portal configuration & online intake."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect, render

from applicant_portal.forms import ApplicantPortalSettingsForm
from applicant_portal.models import ApplicantAccount, OnlineApplication
from applicant_portal.security import get_portal_settings
from loans.models import LoanRequest


def _can_view_online_intake(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'role', None) in (
        'superadmin', 'admin', 'branch_manager', 'credit_head',
        'credit_loan_officer', 'loan_officer',
    ):
        return True
    return False


@login_required
@user_passes_test(lambda u: getattr(u, 'is_superuser', False) or getattr(u, 'role', None) in ('admin', 'superadmin'))
def manage_applicant_portal_settings(request):
    """Settings → Digital apply (hub), not Django admin."""
    from applicant_portal.chapa import chapa_live_enabled, chapa_public_key

    policy = get_portal_settings()
    if request.method == 'POST':
        form = ApplicantPortalSettingsForm(request.POST, instance=policy)
        if form.is_valid():
            form.save()
            messages.success(request, 'Digital apply settings saved.')
            return redirect('manage_applicant_portal_settings')
    else:
        form = ApplicantPortalSettingsForm(instance=policy)
    return render(request, 'applicant_portal/hub_settings.html', {
        'form': form,
        'policy': policy,
        'chapa_live': chapa_live_enabled(),
        'chapa_public_key': chapa_public_key(),
    })


@login_required
@user_passes_test(_can_view_online_intake)
def online_loan_intake(request):
    """Staff list of digital-apply loans + drafts needing attention."""
    role = getattr(request.user, 'role', None)
    branch = getattr(request.user, 'branch', None)

    loans = (
        LoanRequest.objects
        .filter(source_channel=LoanRequest.SOURCE_ONLINE)
        .select_related('branch', 'district', 'category', 'assigned_loan_officer')
        .order_by('-date_requested')
    )
    drafts = (
        OnlineApplication.objects
        .exclude(status=OnlineApplication.STATUS_CANCELLED)
        .filter(loan_request__isnull=True)
        .select_related('branch', 'category', 'applicant')
        .order_by('-updated_at')
    )

    # Scope non-superusers to their branch when available
    if not request.user.is_superuser and role not in ('credit_head', 'admin', 'superadmin'):
        if branch:
            loans = loans.filter(branch=branch)
            drafts = drafts.filter(branch=branch)
        else:
            loans = loans.none()
            drafts = drafts.none()

    q = (request.GET.get('q') or '').strip()
    if q:
        loans = loans.filter(
            Q(loan_request_id__icontains=q)
            | Q(applicant_name__icontains=q)
            | Q(phone_number__icontains=q)
            | Q(customer_number__icontains=q)
        )
        drafts = drafts.filter(
            Q(applicant_name__icontains=q)
            | Q(phone_number__icontains=q)
            | Q(customer_number__icontains=q)
            | Q(applicant__full_name__icontains=q)
        )

    loan_page = Paginator(loans, 10).get_page(request.GET.get('page'))
    draft_page = Paginator(drafts, 10).get_page(request.GET.get('draft_page'))

    accounts_count = ApplicantAccount.objects.filter(is_active=True).count()
    return render(request, 'applicant_portal/hub_online_intake.html', {
        'loan_page': loan_page,
        'draft_page': draft_page,
        'q': q,
        'accounts_count': accounts_count,
        'submitted_count': loans.count(),
        'draft_count': drafts.count(),
    })
