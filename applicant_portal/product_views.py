"""Applicant-facing product files — same overlays as the staff hub."""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from applicant_portal.access import (
    applicant_can_edit_product,
    applicant_can_edit_profile,
    family_of,
    needs_applicant_product,
)
from applicant_portal.auth import applicant_login_required
from applicant_portal.services import ensure_working_loan
from loans.product_family import (
    FAMILY_IDEA_EQUITY,
    FAMILY_IFB_IJARAH,
    FAMILY_IFB_MURABAHA,
    FAMILY_LEASE,
    FAMILY_PROJECT,
    FAMILY_WHOLESALE,
)


def _closed_or_app(request, public_id):
    from applicant_portal.views import _get_owned_app, _portal_or_closed

    closed = _portal_or_closed(request)
    if closed:
        return closed, None
    return None, _get_owned_app(request, public_id)


@applicant_login_required
@require_http_methods(['GET', 'POST'])
def apply_product(request, public_id):
    closed, app = _closed_or_app(request, public_id)
    if closed:
        return closed
    if not needs_applicant_product(app):
        return redirect('applicant_portal:apply_documents', public_id=app.public_id)

    loan = ensure_working_loan(app)
    if loan is None:
        messages.warning(request, 'Choose product, branch, and amount first.')
        return redirect('applicant_portal:apply_details', public_id=app.public_id)

    family = family_of(app)
    form, extra = _bind_product_form(request, loan, family)
    can_edit = applicant_can_edit_profile(app)
    if request.method == 'POST' and can_edit and form is not None:
        if form.is_valid():
            obj = form.save(commit=False)
            if hasattr(obj, 'updated_by'):
                obj.updated_by = None
            obj.save()
            messages.success(request, 'Product file saved. Staff see the same record.')
            if app.status == app.STATUS_DRAFT:
                app.status = app.STATUS_DOCUMENTS
                app.save(update_fields=['status', 'updated_at'])
            if not app.loan_request_id or app.status != app.STATUS_SUBMITTED:
                return redirect('applicant_portal:apply_documents', public_id=app.public_id)
            return redirect('applicant_portal:apply_product', public_id=app.public_id)
    elif form is None:
        extra['form'] = None

    return render(request, 'applicant_portal/apply_product.html', {
        'application': app,
        'loan_request': loan,
        'form': form,
        'family': family,
        'can_edit': can_edit,
        'can_extra': applicant_can_edit_product(app),
        'step': 2,
        'has_product': True,
        **extra,
    })


@applicant_login_required
@require_http_methods(['POST'])
def apply_product_line(request, public_id):
    closed, app = _closed_or_app(request, public_id)
    if closed:
        return closed
    if family_of(app) != FAMILY_PROJECT or not applicant_can_edit_profile(app):
        return redirect('applicant_portal:apply_product', public_id=app.public_id)
    loan = ensure_working_loan(app)
    from loans.models import ProjectProfile, ProjectSourceUseLine
    profile, _ = ProjectProfile.objects.get_or_create(loan_request=loan)
    side = (request.POST.get('side') or '').strip()
    purpose = (request.POST.get('purpose') or ProjectSourceUseLine.PURPOSE_OTHER).strip()
    try:
        amount = Decimal((request.POST.get('amount') or '').strip())
    except (InvalidOperation, TypeError, ValueError):
        amount = None
    if side not in (ProjectSourceUseLine.SIDE_SOURCE, ProjectSourceUseLine.SIDE_USE) or not amount:
        messages.error(request, 'Enter a source or use amount.')
        return redirect('applicant_portal:apply_product', public_id=app.public_id)
    ProjectSourceUseLine.objects.create(
        profile=profile, side=side, purpose=purpose,
        label=(request.POST.get('label') or '').strip(),
        amount=amount,
    )
    messages.success(request, 'Sources & uses line added.')
    return redirect('applicant_portal:apply_product', public_id=app.public_id)


@applicant_login_required
@require_http_methods(['POST'])
def apply_product_utilization(request, public_id):
    closed, app = _closed_or_app(request, public_id)
    if closed:
        return closed
    if family_of(app) != FAMILY_WHOLESALE or not applicant_can_edit_product(app):
        return redirect('applicant_portal:apply_product', public_id=app.public_id)
    loan = ensure_working_loan(app)
    from datetime import datetime
    from loans.models import PfiInstitutionProfile, PfiUtilizationReport

    profile, _ = PfiInstitutionProfile.objects.get_or_create(loan_request=loan)
    raw = (request.POST.get('as_of') or '').strip()
    try:
        as_of = datetime.strptime(raw, '%Y-%m-%d').date() if raw else None
    except ValueError:
        as_of = None
    if as_of is None:
        messages.error(request, 'Enter the report date.')
        return redirect('applicant_portal:apply_product', public_id=app.public_id)

    def _dec(name):
        raw_v = (request.POST.get(name) or '').strip()
        if not raw_v:
            return None
        try:
            return Decimal(raw_v)
        except (InvalidOperation, TypeError, ValueError):
            return None

    PfiUtilizationReport.objects.create(
        profile=profile,
        as_of=as_of,
        amount_onlent=_dec('amount_onlent') or 0,
        pfi_repaid_to_dbe=_dec('pfi_repaid_to_dbe') or 0,
        sub_par30_pct=_dec('sub_par30_pct'),
        sub_par90_pct=_dec('sub_par90_pct'),
        women_onlent_pct=_dec('women_onlent_pct'),
        youth_onlent_pct=_dec('youth_onlent_pct'),
        note=(request.POST.get('note') or '').strip(),
    )
    messages.success(request, 'Utilization report recorded. DBE staff see it on the PFI file.')
    return redirect('applicant_portal:apply_product', public_id=app.public_id)


@applicant_login_required
@require_http_methods(['POST'])
def apply_product_cap(request, public_id):
    closed, app = _closed_or_app(request, public_id)
    if closed:
        return closed
    if family_of(app) != FAMILY_IDEA_EQUITY or not applicant_can_edit_profile(app):
        return redirect('applicant_portal:apply_product', public_id=app.public_id)
    loan = ensure_working_loan(app)
    from loans.models import CapTableEntry, IdeaProfile

    profile, _ = IdeaProfile.objects.get_or_create(loan_request=loan)
    name = (request.POST.get('holder_name') or '').strip()
    try:
        pct = Decimal((request.POST.get('share_pct') or '').strip())
    except (InvalidOperation, TypeError, ValueError):
        pct = None
    if not name or pct is None:
        messages.error(request, 'Enter a holder and share %.')
        return redirect('applicant_portal:apply_product', public_id=app.public_id)
    CapTableEntry.objects.create(
        profile=profile, holder_name=name,
        role=(request.POST.get('role') or CapTableEntry.ROLE_FOUNDER),
        share_pct=pct,
        note=(request.POST.get('note') or '').strip(),
    )
    messages.success(request, 'Cap-table row added.')
    return redirect('applicant_portal:apply_product', public_id=app.public_id)


def _bind_product_form(request, loan, family):
    extra = {}
    data = request.POST if request.method == 'POST' else None
    if family == FAMILY_PROJECT:
        from loans.forms import ProjectProfileForm
        from loans.models import ProjectProfile
        from loans.project_overlay import PURPOSE_LABELS, sources_uses_totals

        profile, _ = ProjectProfile.objects.get_or_create(loan_request=loan)
        extra['lines'] = list(profile.lines.order_by('side', 'sequence', 'id'))
        extra['totals'] = sources_uses_totals(profile)
        extra['source_purposes'] = [
            ('promoter_cash', PURPOSE_LABELS['promoter_cash']),
            ('dbe_loan', PURPOSE_LABELS['dbe_loan']),
            ('other_bank', PURPOSE_LABELS['other_bank']),
            ('grant', PURPOSE_LABELS['grant']),
        ]
        extra['use_purposes'] = [
            ('civil', PURPOSE_LABELS['civil']),
            ('machinery', PURPOSE_LABELS['machinery']),
            ('working_capital', PURPOSE_LABELS['working_capital']),
            ('insurance', PURPOSE_LABELS['insurance']),
        ]
        return ProjectProfileForm(data, instance=profile), extra
    if family == FAMILY_WHOLESALE:
        from loans.forms import PfiInstitutionForm
        from loans.models import PfiInstitutionProfile

        profile, _ = PfiInstitutionProfile.objects.get_or_create(loan_request=loan)
        extra['reports'] = list(profile.utilization_reports.order_by('-as_of', '-id')[:12])
        return PfiInstitutionForm(data, instance=profile), extra
    if family in (FAMILY_LEASE, FAMILY_IFB_IJARAH):
        from loans.forms import LeaseAssetForm
        from loans.models import LeaseAssetProfile

        profile, _ = LeaseAssetProfile.objects.get_or_create(loan_request=loan)
        extra['is_ijarah'] = family == FAMILY_IFB_IJARAH
        extra['rents'] = list(profile.rent_lines.order_by('sequence', 'id')) if extra['is_ijarah'] else []
        return LeaseAssetForm(data, instance=profile), extra
    if family == FAMILY_IFB_MURABAHA:
        from loans.forms import MurabahaContractForm
        from loans.models import MurabahaContract

        contract, _ = MurabahaContract.objects.get_or_create(loan_request=loan)
        return MurabahaContractForm(data, instance=contract), extra
    if family == FAMILY_IDEA_EQUITY:
        from loans.forms import IdeaProfileForm
        from loans.models import IdeaProfile

        profile, _ = IdeaProfile.objects.get_or_create(loan_request=loan)
        extra['cap_rows'] = list(profile.cap_table.all())
        return IdeaProfileForm(data, instance=profile), extra
    return None, extra
