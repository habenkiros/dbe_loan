# collateral/views.py
from collections import OrderedDict
from decimal import Decimal
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.utils import timezone
from loans.models import LoanRequest, Region
from loans.collateral_config import get_collateral_estimation_mode, allows_engineering_team
from .models import (
    MainWork, SubWork, SubSubWork, SubWorkUnitPrice,
    Building, BuildingValuation, BuildingImage, LandValuation, LandValuationImage,
    OtherCollateralItem, OtherCollateralItemImage,
    CollateralUnlockRequest,
)
from .forms import (
    BuildingForm, BuildingValuationForm, BuildingImageForm, LandValuationForm,
    SubWorkUnitPriceForm, _user_can_edit_unit_price,
    MainWorkForm, SubWorkForm, SubSubWorkForm,
    OtherCollateralItemForm,
)
from .constants import (
    FIELD_VISIT_STEPS, LAND_FIELD_STEPS, OTHER_FIELD_STEPS,
)
from .coverage import compute_coverage_adequacy
from .policy import get_collateral_policy
from .field_utils import (
    apply_site_gps_from_post,
    apply_site_gps_to_instance,
    build_field_boq_rows,
    collateral_is_locked,
    collateral_submit_blockers,
    get_building_readiness,
    get_land_readiness,
    get_loan_collateral_readiness,
    get_other_item_readiness,
    get_unit_price_for_building,
    save_field_visit_boq,
    save_field_visit_photo,
    save_land_field_photo,
    save_other_field_photo,
)
from .governance import block_if_collateral_locked, log_collateral_event
from .map_utils import building_map_data, haversine_m, land_map_data, other_item_map_data


def _policy_template_context():
    p = get_collateral_policy()
    return {
        'min_images': p.min_images_per_building,
        'min_images_per_building': p.min_images_per_building,
        'min_images_per_land': p.min_images_per_land,
        'min_images_per_other_item': p.min_images_per_other_item,
        'gps_weak_threshold_m': p.gps_accuracy_weak_threshold_m,
        'max_photo_distance_m': p.photo_max_distance_from_site_m,
        'collateral_policy': p,
    }


def _can_request_collateral_unlock(user, loan_request) -> bool:
    if not collateral_is_locked(loan_request):
        return False
    if CollateralUnlockRequest.objects.filter(
        loan_request=loan_request, status=CollateralUnlockRequest.STATUS_PENDING,
    ).exists():
        return False
    if user.role == 'loan_officer' and loan_request.assigned_loan_officer_id == user.id:
        return True
    if user.role == 'engineer' and loan_request.assigned_engineer_id == user.id:
        return True
    if loan_request.collateral_submitted_by_id == user.id:
        return True
    return False


def _can_review_collateral_unlock(user, loan_request) -> bool:
    role = getattr(user, 'role', None)
    if role in ('superadmin', 'admin'):
        return True
    if role == 'engineering_head':
        return True
    if role == 'branch_manager' and getattr(user, 'branch_id', None) == loan_request.branch_id:
        return True
    return False


def _can_access_collateral(user):
    """Roles that can work on collateral (loan officer, engineer, branch manager, etc.)."""
    return user.role in (
        'branch_manager', 'loan_officer', 'engineer', 'engineering_head',
        'operation_manager', 'finance_manager', 'credit_committee',
        'admin', 'superadmin',
    )


def _collateral_eligible_loans(user=None):
    """Loan requests eligible for collateral: queue_approved or status=Approved. By role and config (loan_officer / engineering_team / both)."""
    qs = LoanRequest.objects.filter(
        Q(queue_approved=True) | Q(status__iexact='Approved')
    )
    if user:
        role = getattr(user, 'role', None)
        mode = get_collateral_estimation_mode()
        if role == 'branch_manager' and getattr(user, 'branch_id', None):
            qs = qs.filter(branch=user.branch)
        elif role == 'loan_officer':
            if mode in ('loan_officer', 'both'):
                qs = qs.filter(assigned_loan_officer=user)
            else:
                qs = qs.none()
        elif role == 'engineer':
            if mode in ('engineering_team', 'both'):
                qs = qs.filter(assigned_engineer=user)
            else:
                qs = qs.none()
        elif role == 'engineering_head':
            if mode in ('engineering_team', 'both'):
                qs = qs.filter(sent_to_engineering_at__isnull=False)
            else:
                qs = qs.none()
    return qs


@login_required
@user_passes_test(_can_access_collateral)
def dashboard(request):
    """List loan requests eligible for collateral (queue_approved or Approved); link to their collateral. Branch managers see only their branch."""
    if getattr(request.user, 'role', None) == 'engineering_head' and allows_engineering_team():
        return redirect(reverse('loans_sent_for_collateral'))
    loan_requests = _collateral_eligible_loans(request.user).select_related(
        'branch', 'district', 'collateral', 'collateral_submitted_by'
    ).order_by('-date_requested')
    q = request.GET.get('q')
    if q:
        loan_requests = loan_requests.filter(
            Q(loan_request_id__icontains=q) |
            Q(applicant_name__icontains=q) |
            Q(phone_number__icontains=q)
        )
    is_engineer = getattr(request.user, 'role', None) == 'engineer'
    is_loan_officer = getattr(request.user, 'role', None) == 'loan_officer'
    from .pipeline import STAGE_LABELS, annotate_loans_pipeline, pipeline_counts

    loan_list = list(loan_requests)
    pipeline_rows = annotate_loans_pipeline(loan_list)
    stage_filter = (request.GET.get('stage') or '').strip()
    if stage_filter:
        pipeline_rows = [r for r in pipeline_rows if r['pipeline_stage'] == stage_filter]
    counts = pipeline_counts(loan_list)
    pipeline_filters = [
        {'stage': stage, 'label': STAGE_LABELS.get(stage, stage), 'count': counts.get(stage, 0)}
        for stage in STAGE_LABELS
        if counts.get(stage, 0)
    ]
    return render(request, 'collateral/dashboard.html', {
        'pipeline_rows': pipeline_rows,
        'pipeline_filters': pipeline_filters,
        'stage_filter': stage_filter,
        'query': q or '',
        'is_engineer': is_engineer,
        'is_loan_officer': is_loan_officer,
    })


@login_required
@user_passes_test(lambda u: getattr(u, 'role', None) == 'superadmin')
def collateral_list_superadmin(request):
    """Superadmin only: list all collateral-eligible loans (like other list pages) with search, filters, pagination."""
    qs = LoanRequest.objects.filter(
        Q(queue_approved=True) | Q(status__iexact='Approved')
    ).select_related(
        'branch', 'collateral', 'collateral_submitted_by',
        'assigned_loan_officer', 'assigned_engineer',
    ).order_by('-date_requested')
    q = request.GET.get('q')
    if q:
        qs = qs.filter(
            Q(loan_request_id__icontains=q) |
            Q(applicant_name__icontains=q) |
            Q(phone_number__icontains=q)
        )
    status_filter = request.GET.get('status')
    if status_filter:
        qs = qs.filter(status__iexact=status_filter)
    paginator = Paginator(qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'collateral/collateral_list_superadmin.html', {
        'page_obj': page_obj,
        'loan_requests': page_obj,
        'query': q or '',
        'selected_status': status_filter or '',
    })


@login_required
@user_passes_test(_can_access_collateral)
def building_list(request, loan_request_id):
    """List buildings for a loan request; add building."""
    loan_request = get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_request_id)
    buildings = Building.objects.filter(loan_request=loan_request).select_related('city')
    ct = (loan_request.collateral.name or '').lower()
    building_rows = []
    for b in buildings:
        building_rows.append({'building': b, 'readiness': get_building_readiness(b)})
    return render(request, 'collateral/building_list.html', {
        'loan_request': loan_request,
        'buildings': buildings,
        'building_rows': building_rows,
        'collateral_type_lower': ct,
        'locked': collateral_is_locked(loan_request),
    })


@login_required
@user_passes_test(_can_access_collateral)
def building_add(request, loan_request_id):
    """Add a building to a loan request. City/woreda chosen via Region → Zone → City cascade."""
    loan_request = get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_request_id)
    if request.method == 'POST':
        blocked = block_if_collateral_locked(request, loan_request, 'collateral:building_list', loan_request_id)
        if blocked:
            return blocked
        form = BuildingForm(request.POST)
        if form.is_valid():
            building = form.save(commit=False)
            building.loan_request = loan_request
            building.save()
            messages.success(request, f'Building "{building.name}" added.')
            return redirect('collateral:field_visit', building_id=building.pk)
    else:
        form = BuildingForm()
    form.fields['city'].queryset = form.fields['city'].queryset.order_by('zone__region', 'zone', 'name')
    return render(request, 'collateral/building_form.html', {
        'loan_request': loan_request,
        'form': form,
        'is_edit': False,
        'regions': Region.objects.all().order_by('name'),
        'zones_url': request.build_absolute_uri(reverse('ajax_load_zones_by_region')),
        'cities_url': request.build_absolute_uri(reverse('ajax_load_cities_by_zone')),
    })


@login_required
@user_passes_test(_can_access_collateral)
def building_edit(request, building_id):
    """Edit a building. City/woreda chosen via Region → Zone → City cascade."""
    building = get_object_or_404(Building, pk=building_id)
    loan_request = building.loan_request
    if request.method == 'POST':
        blocked = block_if_collateral_locked(request, loan_request, 'collateral:building_list', loan_request.id)
        if blocked:
            return blocked
        form = BuildingForm(request.POST, instance=building)
        if form.is_valid():
            form.save()
            messages.success(request, 'Building updated.')
            return redirect('collateral:building_list', loan_request_id=loan_request.id)
    else:
        form = BuildingForm(instance=building)
    form.fields['city'].queryset = form.fields['city'].queryset.order_by('zone__region', 'zone', 'name')
    return render(request, 'collateral/building_form.html', {
        'loan_request': loan_request,
        'building': building,
        'form': form,
        'is_edit': True,
        'regions': Region.objects.all().order_by('name'),
        'zones_url': request.build_absolute_uri(reverse('ajax_load_zones_by_region')),
        'cities_url': request.build_absolute_uri(reverse('ajax_load_cities_by_zone')),
    })


@login_required
@user_passes_test(_can_access_collateral)
def valuation_list(request, building_id):
    """List valuation rows for a building; show total; add row."""
    building = get_object_or_404(Building, pk=building_id)
    rows = BuildingValuation.objects.filter(building=building).select_related(
        'sub_work', 'sub_work__main_work',
        'sub_sub_work', 'sub_sub_work__sub_work', 'sub_sub_work__sub_work__main_work'
    ).order_by('sub_work__main_work__order', 'sub_work__order', 'sub_sub_work__order')
    total = sum(r.total for r in rows)
    return render(request, 'collateral/valuation_list.html', {
        'building': building,
        'rows': rows,
        'building_total': total,
        'locked': collateral_is_locked(building.loan_request),
    })


def _get_unit_price_for_building(building, sub_work=None, sub_sub_work=None):
    """Get unit price from SubWorkUnitPrice for building's city (woreda) and sub_work or sub_sub_work."""
    return get_unit_price_for_building(building, sub_work=sub_work, sub_sub_work=sub_sub_work)


def _get_work_item_ids_with_unit_price(city):
    """Return (sub_work_ids, sub_sub_work_ids) that have a SubWorkUnitPrice for the given city (woreda)."""
    if not city:
        return set(), set()
    sub_work_ids = set(
        SubWorkUnitPrice.objects.filter(
            city=city, sub_work__isnull=False, sub_sub_work__isnull=True
        ).values_list('sub_work_id', flat=True)
    )
    sub_sub_work_ids = set(
        SubWorkUnitPrice.objects.filter(
            city=city, sub_sub_work__isnull=False
        ).values_list('sub_sub_work_id', flat=True)
    )
    return sub_work_ids, sub_sub_work_ids


def _build_work_choices(existing_sub_work_ids, existing_sub_sub_work_ids, allowed_sub_work_ids=None, allowed_sub_sub_work_ids=None):
    """Build optgroup choices for work item dropdown. If allowed_* are given, only include items that have a unit price for the building's city."""
    groups = OrderedDict()
    for mw in MainWork.objects.all().order_by('order', 'name'):
        for sw in SubWork.objects.filter(main_work=mw).order_by('order', 'name'):
            key = f"{mw.name} → {sw.name}"
            options = []
            if sw.id not in existing_sub_work_ids:
                if allowed_sub_work_ids is None or sw.id in allowed_sub_work_ids:
                    options.append((f"sub_work:{sw.id}", f"{sw.name} (sub work only)"))
            for ssw in SubSubWork.objects.filter(sub_work=sw).order_by('order', 'name'):
                if ssw.id not in existing_sub_sub_work_ids:
                    if allowed_sub_sub_work_ids is None or ssw.id in allowed_sub_sub_work_ids:
                        options.append((f"sub_sub_work:{ssw.id}", ssw.name))
            if options:
                groups[key] = options
    return list(groups.items())


def _parse_work_item(work_item):
    """Return (sub_work_id, sub_sub_work_id) from work_item value 'sub_work:5' or 'sub_sub_work:10'."""
    if not work_item or ':' not in work_item:
        return None, None
    kind, pk = work_item.split(':', 1)
    try:
        pk = int(pk)
    except ValueError:
        return None, None
    if kind == 'sub_work':
        return pk, None
    if kind == 'sub_sub_work':
        return None, pk
    return None, None


def _build_work_items_flat(existing_sub_work_ids, existing_sub_sub_work_ids, allowed_sub_work_ids=None, allowed_sub_sub_work_ids=None):
    """Flat list of (key, label) for work items not yet added, in display order. If allowed_* are given, only items with unit price for building's city."""
    items = []
    for mw in MainWork.objects.all().order_by('order', 'name'):
        for sw in SubWork.objects.filter(main_work=mw).order_by('order', 'name'):
            if sw.id not in existing_sub_work_ids:
                if allowed_sub_work_ids is None or sw.id in allowed_sub_work_ids:
                    items.append((f'sub_work:{sw.id}', f'{mw.name} → {sw.name} (sub work only)'))
            for ssw in SubSubWork.objects.filter(sub_work=sw).order_by('order', 'name'):
                if ssw.id not in existing_sub_sub_work_ids:
                    if allowed_sub_sub_work_ids is None or ssw.id in allowed_sub_sub_work_ids:
                        items.append((f'sub_sub_work:{ssw.id}', f'{mw.name} → {sw.name} → {ssw.name}'))
    return items


@login_required
@user_passes_test(_can_access_collateral)
def valuation_add(request, building_id):
    """Add a valuation row. Loan officers enter only quantity; unit price comes from catalog. Engineers can override."""
    building = get_object_or_404(Building, pk=building_id)
    loan_request = building.loan_request
    can_edit_unit_price = _user_can_edit_unit_price(request.user)
    existing_sub_work_ids = set(
        BuildingValuation.objects.filter(building=building).exclude(sub_work__isnull=True).values_list('sub_work_id', flat=True)
    )
    existing_sub_sub_work_ids = set(
        BuildingValuation.objects.filter(building=building).exclude(sub_sub_work__isnull=True).values_list('sub_sub_work_id', flat=True)
    )
    # Only show sub works / sub-sub works that have a unit price for this building's city (woreda)
    allowed_sub_work_ids, allowed_sub_sub_work_ids = _get_work_item_ids_with_unit_price(building.city) if building.city_id else (set(), set())
    work_choices = _build_work_choices(
        existing_sub_work_ids, existing_sub_sub_work_ids,
        allowed_sub_work_ids=allowed_sub_work_ids, allowed_sub_sub_work_ids=allowed_sub_sub_work_ids,
    )
    if request.method == 'POST':
        blocked = block_if_collateral_locked(request, loan_request, 'collateral:valuation_list', building_id)
        if blocked:
            return blocked
        work_item = request.POST.get('work_item', '').strip()
        if not work_item:
            messages.error(request, 'Please select a work item from the list.')
        sub_work_id, sub_sub_work_id = _parse_work_item(work_item)
        data = request.POST.copy()
        # Pass string PKs so form binding works correctly
        data['sub_work'] = str(sub_work_id) if sub_work_id else ''
        data['sub_sub_work'] = str(sub_sub_work_id) if sub_sub_work_id else ''
        form = BuildingValuationForm(data, can_edit_unit_price=can_edit_unit_price)
        if form.is_valid():
            sub_work = form.cleaned_data.get('sub_work')
            sub_sub_work = form.cleaned_data.get('sub_sub_work')
            if sub_work and sub_work.id in existing_sub_work_ids:
                messages.error(request, 'This item is already added for this building.')
                form.fields.pop('sub_work', None)
                form.fields.pop('sub_sub_work', None)
                return render(request, 'collateral/valuation_form.html', {
                    'building': building, 'form': form, 'work_choices': work_choices,
                    'building_has_city': bool(building.city_id), 'is_edit': False,
                    'can_edit_unit_price': can_edit_unit_price, 'selected_work_item': work_item,
                })
            if sub_sub_work and sub_sub_work.id in existing_sub_sub_work_ids:
                messages.error(request, 'This item is already added for this building.')
                form.fields.pop('sub_work', None)
                form.fields.pop('sub_sub_work', None)
                return render(request, 'collateral/valuation_form.html', {
                    'building': building, 'form': form, 'work_choices': work_choices,
                    'building_has_city': bool(building.city_id), 'is_edit': False,
                    'can_edit_unit_price': can_edit_unit_price, 'selected_work_item': work_item,
                })
            unit_price = form.cleaned_data.get('unit_price') or _get_unit_price_for_building(
                building, sub_work=sub_work, sub_sub_work=sub_sub_work
            )
            if unit_price is None and not can_edit_unit_price:
                messages.error(
                    request,
                    'No unit price in catalog for this woreda and work item. '
                    'Set the building\'s city (woreda), or ask the engineering team to add the unit price.',
                )
                form.fields.pop('sub_work', None)
                form.fields.pop('sub_sub_work', None)
                return render(request, 'collateral/valuation_form.html', {
                    'building': building, 'form': form, 'work_choices': work_choices,
                    'building_has_city': bool(building.city_id), 'is_edit': False,
                    'can_edit_unit_price': can_edit_unit_price, 'selected_work_item': work_item,
                })
            if unit_price is None:
                unit_price = Decimal('0')
            obj = form.save(commit=False)
            obj.building = building
            obj.unit_price = unit_price
            if request.user.is_authenticated:
                obj.quantity_entered_by = request.user
            obj.save()
            messages.success(request, 'Valuation row added.')
            return redirect('collateral:valuation_list', building_id=building_id)
    else:
        form = BuildingValuationForm(can_edit_unit_price=can_edit_unit_price)
    form.fields.pop('sub_work', None)
    form.fields.pop('sub_sub_work', None)
    # When no work items left to add, or building has no city, show message and links
    building_has_city = bool(building.city_id)
    if not work_choices:
        return render(request, 'collateral/valuation_form.html', {
            'building': building,
            'form': form,
            'work_choices': [],
            'work_choices_empty': True,
            'building_has_city': building_has_city,
            'is_edit': False,
            'can_edit_unit_price': can_edit_unit_price,
            'selected_work_item': None,
        })
    return render(request, 'collateral/valuation_form.html', {
        'building': building,
        'form': form,
        'work_choices': work_choices,
        'work_choices_empty': False,
        'building_has_city': building_has_city,
        'is_edit': False,
        'can_edit_unit_price': can_edit_unit_price,
        'selected_work_item': request.POST.get('work_item') if request.method == 'POST' else None,
    })


@login_required
@user_passes_test(_can_access_collateral)
def valuation_edit(request, valuation_id):
    """Edit BOQ quantity (and unit price for engineers) until collateral is submitted."""
    row = get_object_or_404(
        BuildingValuation.objects.select_related('building', 'building__loan_request', 'sub_work', 'sub_sub_work'),
        pk=valuation_id,
    )
    building = row.building
    loan_request = building.loan_request
    blocked = block_if_collateral_locked(request, loan_request, 'collateral:valuation_list', building.pk)
    if blocked:
        return blocked
    can_edit_unit_price = _user_can_edit_unit_price(request.user)
    work_label = row.sub_sub_work.name if row.sub_sub_work_id else row.sub_work.name
    if request.method == 'POST':
        form = BuildingValuationForm(request.POST, instance=row, can_edit_unit_price=can_edit_unit_price)
        form.fields.pop('sub_work', None)
        form.fields.pop('sub_sub_work', None)
        if form.is_valid():
            obj = form.save(commit=False)
            if request.user.is_authenticated:
                obj.quantity_entered_by = request.user
                if can_edit_unit_price and 'unit_price' in form.cleaned_data:
                    obj.unit_price_entered_by = request.user
            obj.save()
            log_collateral_event(
                loan_request,
                'valuation_edited',
                user=request.user,
                subject_type='BuildingValuation',
                subject_id=row.pk,
                payload={'work': work_label, 'quantity': str(obj.quantity), 'unit_price': str(obj.unit_price)},
            )
            messages.success(request, 'Valuation row updated.')
            return redirect('collateral:valuation_list', building_id=building.pk)
    else:
        form = BuildingValuationForm(instance=row, can_edit_unit_price=can_edit_unit_price)
        form.fields.pop('sub_work', None)
        form.fields.pop('sub_sub_work', None)
    return render(request, 'collateral/valuation_form.html', {
        'building': building,
        'form': form,
        'work_choices': [],
        'work_choices_empty': False,
        'building_has_city': bool(building.city_id),
        'is_edit': True,
        'can_edit_unit_price': can_edit_unit_price,
        'selected_work_item': None,
        'edit_work_label': work_label,
        'row': row,
    })


@login_required
@user_passes_test(_can_access_collateral)
def valuation_delete(request, valuation_id):
    """Remove a BOQ line until collateral is submitted."""
    row = get_object_or_404(
        BuildingValuation.objects.select_related('building', 'building__loan_request', 'sub_work', 'sub_sub_work'),
        pk=valuation_id,
    )
    building = row.building
    loan_request = building.loan_request
    if request.method != 'POST':
        return redirect('collateral:valuation_list', building_id=building.pk)
    blocked = block_if_collateral_locked(request, loan_request, 'collateral:valuation_list', building.pk)
    if blocked:
        return blocked
    work_label = row.sub_sub_work.name if row.sub_sub_work_id else row.sub_work.name
    row_id = row.pk
    row.delete()
    log_collateral_event(
        loan_request,
        'valuation_deleted',
        user=request.user,
        subject_type='BuildingValuation',
        subject_id=row_id,
        payload={'work': work_label},
    )
    messages.success(request, 'Valuation row removed.')
    return redirect('collateral:valuation_list', building_id=building.pk)


@login_required
@user_passes_test(_can_access_collateral)
def valuation_add_multiple(request, building_id):
    """Add multiple valuation rows at once: one quantity per available work item."""
    building = get_object_or_404(Building, pk=building_id)
    loan_request = building.loan_request
    can_edit_unit_price = _user_can_edit_unit_price(request.user)
    existing_sub_work_ids = set(
        BuildingValuation.objects.filter(building=building).exclude(sub_work__isnull=True).values_list('sub_work_id', flat=True)
    )
    existing_sub_sub_work_ids = set(
        BuildingValuation.objects.filter(building=building).exclude(sub_sub_work__isnull=True).values_list('sub_sub_work_id', flat=True)
    )
    # Only show work items that have a unit price for this building's city (woreda)
    allowed_sub_work_ids, allowed_sub_sub_work_ids = _get_work_item_ids_with_unit_price(building.city) if building.city_id else (set(), set())
    work_items = _build_work_items_flat(
        existing_sub_work_ids, existing_sub_sub_work_ids,
        allowed_sub_work_ids=allowed_sub_work_ids, allowed_sub_sub_work_ids=allowed_sub_sub_work_ids,
    )
    if request.method == 'POST':
        blocked = block_if_collateral_locked(request, loan_request, 'collateral:valuation_list', building_id)
        if blocked:
            return blocked
        added = 0
        errors = []
        for i, (key, _label) in enumerate(work_items):
            qty_val = request.POST.get('quantity_%d' % i)
            if qty_val is None or qty_val.strip() == '':
                continue
            try:
                qty = Decimal(qty_val.replace(',', '.').strip())
            except Exception:
                errors.append('Row %s: invalid quantity.' % (i + 1))
                continue
            if qty <= 0:
                continue
            sub_work_id, sub_sub_work_id = _parse_work_item(key)
            sub_work = SubWork.objects.filter(pk=sub_work_id).first() if sub_work_id else None
            sub_sub_work = SubSubWork.objects.filter(pk=sub_sub_work_id).first() if sub_sub_work_id else None
            if sub_work and sub_work.id in existing_sub_work_ids:
                continue
            if sub_sub_work and sub_sub_work.id in existing_sub_sub_work_ids:
                continue
            unit_price = request.POST.get('unit_price_%d' % i) if can_edit_unit_price else None
            if unit_price is not None:
                try:
                    unit_price = Decimal(unit_price.replace(',', '.').strip())
                except Exception:
                    unit_price = None
            if unit_price is None:
                unit_price = _get_unit_price_for_building(building, sub_work=sub_work, sub_sub_work=sub_sub_work)
            if unit_price is None:
                unit_price = Decimal('0')
            if not can_edit_unit_price and _get_unit_price_for_building(building, sub_work=sub_work, sub_sub_work=sub_sub_work) is None:
                errors.append('Row %s: no unit price in catalog for this woreda.' % (i + 1))
                continue
            obj = BuildingValuation(
                building=building,
                sub_work=sub_work,
                sub_sub_work=sub_sub_work,
                quantity=qty,
                unit_price=unit_price,
            )
            if request.user.is_authenticated:
                obj.quantity_entered_by = request.user
            obj.save()
            added += 1
            if sub_work:
                existing_sub_work_ids.add(sub_work.id)
            if sub_sub_work:
                existing_sub_sub_work_ids.add(sub_sub_work.id)
        if errors:
            for e in errors:
                messages.error(request, e)
        if added:
            messages.success(request, 'Added %d valuation row(s).' % added)
        return redirect('collateral:valuation_list', building_id=building_id)
    return render(request, 'collateral/valuation_add_multiple.html', {
        'building': building,
        'work_items': work_items,
        'can_edit_unit_price': can_edit_unit_price,
        'building_has_city': bool(building.city_id),
    })


def _annotate_image_distances(site_lat, site_lon, images):
    max_d = get_collateral_policy().photo_max_distance_from_site_m
    rows = []
    for img in images:
        dist = haversine_m(site_lat, site_lon, img.gps_lat, img.gps_lon)
        far = dist is not None and dist > max_d
        rows.append({
            'image': img,
            'distance_m': round(dist) if dist is not None else None,
            'far_from_site': far,
        })
    return rows


@login_required
@user_passes_test(_can_access_collateral)
def field_visit(request, building_id, step=1):
    """Mobile-first on-site workflow: building → BOQ → photos → review."""
    building = get_object_or_404(
        Building.objects.select_related('loan_request', 'loan_request__collateral', 'city', 'city__zone', 'city__zone__region'),
        pk=building_id,
    )
    loan_request = building.loan_request
    get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_request.pk)

    step = int(step)
    if step < 1 or step > 4:
        return redirect('collateral:field_visit', building_id=building_id)

    locked = collateral_is_locked(loan_request)
    if locked and request.method == 'POST':
        messages.warning(request, 'Collateral already submitted — field visit is read-only.')
        return redirect('collateral:field_visit', building_id=building_id, step=step)

    can_edit_unit_price = _user_can_edit_unit_price(request.user)
    building_form = None

    if request.method == 'POST':
        action = (request.POST.get('action') or 'save').strip()

        if step == 1 and action in ('save', 'save_next'):
            building_form = BuildingForm(request.POST, instance=building)
            if building_form.is_valid():
                building_form.save()
                building.refresh_from_db()
                if request.POST.get('site_gps_lat'):
                    gps_ok, gps_err = apply_site_gps_from_post(building, request.POST, user=request.user)
                    if gps_err:
                        messages.error(request, gps_err)
                    elif gps_ok:
                        messages.success(request, 'Building site location saved.')
                messages.success(request, 'Building details saved.')
                if action == 'save_next':
                    return redirect('collateral:field_visit_step', building_id=building_id, step=2)
            else:
                messages.error(request, 'Please fix the errors below.')
        elif step == 2 and action in ('save', 'save_next'):
            allowed_sub, allowed_subsub = _get_work_item_ids_with_unit_price(building.city) if building.city_id else (set(), set())
            work_items = _build_work_items_flat(set(), set(), allowed_sub_work_ids=allowed_sub, allowed_sub_sub_work_ids=allowed_subsub)
            saved, errors = save_field_visit_boq(
                building,
                request.POST,
                request.user,
                work_items=work_items,
                get_unit_price=_get_unit_price_for_building,
                can_edit_unit_price=can_edit_unit_price,
            )
            for err in errors:
                messages.error(request, err)
            if saved:
                messages.success(request, f'Saved {saved} BOQ line(s).')
            elif not errors:
                messages.info(request, 'No quantities entered.')
            if action == 'save_next' and not errors:
                return redirect('collateral:field_visit_step', building_id=building_id, step=3)
        elif step == 3 and action == 'upload_photo':
            ok, msg = save_field_visit_photo(building, request.POST, request.FILES, request.user)
            if ok:
                messages.success(request, msg)
            else:
                messages.error(request, msg)
        elif step == 3 and action == 'save_next':
            return redirect('collateral:field_visit_step', building_id=building_id, step=4)

    readiness = get_building_readiness(building)
    if building_form is None:
        building_form = BuildingForm(instance=building)
    building_form.fields['city'].queryset = building_form.fields['city'].queryset.order_by('zone__region', 'zone', 'name')

    allowed_sub, allowed_subsub = _get_work_item_ids_with_unit_price(building.city) if building.city_id else (set(), set())
    work_items_flat = _build_work_items_flat(set(), set(), allowed_sub_work_ids=allowed_sub, allowed_sub_sub_work_ids=allowed_subsub)
    valuations = list(BuildingValuation.objects.filter(building=building).select_related(
        'sub_work', 'sub_sub_work',
    ))
    boq_rows = build_field_boq_rows(building, work_items_flat, valuations)

    images = BuildingImage.objects.filter(building=building).order_by('-created_at')
    photo_types = BuildingImage.PHOTO_TYPE_CHOICES
    map_data = building_map_data(building)
    image_rows = _annotate_image_distances(building.site_gps_lat, building.site_gps_lon, images)
    pctx = _policy_template_context()

    return render(request, 'collateral/field_visit.html', {
        'building': building,
        'loan_request': loan_request,
        'step': step,
        'steps': FIELD_VISIT_STEPS,
        'locked': locked,
        'readiness': readiness,
        'building_form': building_form,
        'regions': Region.objects.all().order_by('name'),
        'zones_url': request.build_absolute_uri(reverse('ajax_load_zones_by_region')),
        'cities_url': request.build_absolute_uri(reverse('ajax_load_cities_by_zone')),
        'boq_rows': boq_rows,
        'building_has_city': bool(building.city_id),
        'can_edit_unit_price': can_edit_unit_price,
        'images': images,
        'photo_types': photo_types,
        'min_images': pctx['min_images_per_building'],
        'gps_weak_threshold_m': pctx['gps_weak_threshold_m'],
        'map_data': map_data,
        'image_rows': image_rows,
        'max_photo_distance_m': pctx['max_photo_distance_m'],
    })


@login_required
@user_passes_test(_can_access_collateral)
def land_field_visit(request, loan_request_id, step=1):
    """Field visit for land collateral: details + GPS → photos → review."""
    loan_request = get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_request_id)
    land, _ = LandValuation.objects.get_or_create(loan_request=loan_request)
    step = int(step)
    if step < 1 or step > 3:
        return redirect('collateral:land_field_visit', loan_request_id=loan_request_id)
    locked = collateral_is_locked(loan_request)
    land_form = None

    if request.method == 'POST' and not locked:
        action = (request.POST.get('action') or 'save').strip()
        if step == 1 and action in ('save', 'save_next'):
            land_form = LandValuationForm(request.POST, instance=land)
            if land_form.is_valid():
                land_form.save()
                land.refresh_from_db()
                if request.POST.get('site_gps_lat'):
                    gps_ok, gps_err = apply_site_gps_to_instance(land, request.POST, user=request.user)
                    if gps_err:
                        messages.error(request, gps_err)
                    elif gps_ok:
                        messages.success(request, 'Plot location saved.')
                messages.success(request, 'Land details saved.')
                if action == 'save_next':
                    return redirect('collateral:land_field_visit_step', loan_request_id=loan_request_id, step=2)
            else:
                messages.error(request, 'Please fix the errors below.')
        elif step == 2 and action == 'upload_photo':
            ok, msg = save_land_field_photo(land, request.POST, request.FILES, request.user)
            messages.success(request, msg) if ok else messages.error(request, msg)
        elif step == 2 and action == 'save_next':
            return redirect('collateral:land_field_visit_step', loan_request_id=loan_request_id, step=3)

    if land_form is None:
        land_form = LandValuationForm(instance=land)
    readiness = get_land_readiness(land)
    images = LandValuationImage.objects.filter(land_valuation=land).order_by('-created_at')
    map_data = land_map_data(land)
    image_rows = _annotate_image_distances(land.site_gps_lat, land.site_gps_lon, images)
    pctx = _policy_template_context()

    return render(request, 'collateral/field_visit_asset.html', {
        'visit_kind': 'land',
        'visit_title': 'Land field visit',
        'visit_subject': loan_request.loan_request_id,
        'loan_request': loan_request,
        'land': land,
        'step': step,
        'steps': LAND_FIELD_STEPS,
        'locked': locked,
        'readiness': readiness,
        'land_form': land_form,
        'images': images,
        'photo_types': LandValuationImage.PHOTO_TYPE_CHOICES,
        'min_images': pctx['min_images_per_land'],
        'back_url': reverse('collateral:land_valuation', args=[loan_request_id]),
        'summary_url': reverse('collateral:summary', args=[loan_request_id]),
        'gps_weak_threshold_m': pctx['gps_weak_threshold_m'],
        'map_data': map_data,
        'image_rows': image_rows,
        'max_photo_distance_m': pctx['max_photo_distance_m'],
    })


@login_required
@user_passes_test(_can_access_collateral)
def other_field_visit(request, item_id, step=1):
    """Field visit for vehicle / machinery / equipment: details + GPS → photos → review."""
    item = get_object_or_404(OtherCollateralItem.objects.select_related('loan_request'), pk=item_id)
    loan_request = item.loan_request
    get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_request.pk)
    step = int(step)
    if step < 1 or step > 3:
        return redirect('collateral:other_field_visit', item_id=item_id)
    locked = collateral_is_locked(loan_request)
    item_form = None

    if request.method == 'POST' and not locked:
        action = (request.POST.get('action') or 'save').strip()
        if step == 1 and action in ('save', 'save_next'):
            item_form = OtherCollateralItemForm(request.POST, instance=item)
            if item_form.is_valid():
                item_form.save()
                item.refresh_from_db()
                if request.POST.get('site_gps_lat'):
                    gps_ok, gps_err = apply_site_gps_to_instance(item, request.POST, user=request.user)
                    if gps_err:
                        messages.error(request, gps_err)
                    elif gps_ok:
                        messages.success(request, 'Asset location saved.')
                messages.success(request, 'Asset details saved.')
                if action == 'save_next':
                    return redirect('collateral:other_field_visit_step', item_id=item_id, step=2)
            else:
                for field, errs in item_form.errors.items():
                    for e in errs:
                        messages.error(request, f'{field}: {e}')
                messages.error(request, 'Could not save — check fields below.')
        elif step == 2 and action == 'upload_photo':
            ok, msg = save_other_field_photo(item, request.POST, request.FILES, request.user)
            messages.success(request, msg) if ok else messages.error(request, msg)
        elif step == 2 and action == 'save_next':
            return redirect('collateral:other_field_visit_step', item_id=item_id, step=3)

    if item_form is None:
        item_form = OtherCollateralItemForm(instance=item)
    readiness = get_other_item_readiness(item)
    images = OtherCollateralItemImage.objects.filter(item=item).order_by('-created_at')
    map_data = other_item_map_data(item)
    image_rows = _annotate_image_distances(item.site_gps_lat, item.site_gps_lon, images)
    pctx = _policy_template_context()
    from collateral import constants
    types_present = set(images.values_list('photo_type', flat=True))
    required_photo_type_status = [
        {'key': key, 'label': label, 'ok': key in types_present}
        for key, label in constants.REQUIRED_MOVABLE_PHOTO_TYPES
    ]

    return render(request, 'collateral/field_visit_asset.html', {
        'visit_kind': 'other',
        'visit_title': f'Field visit — {item.name}',
        'visit_subject': loan_request.loan_request_id,
        'loan_request': loan_request,
        'item': item,
        'step': step,
        'steps': OTHER_FIELD_STEPS,
        'locked': locked,
        'readiness': readiness,
        'item_form': item_form,
        'images': images,
        'photo_types': OtherCollateralItemImage.PHOTO_TYPE_CHOICES,
        'min_images': pctx['min_images_per_other_item'],
        'back_url': reverse('collateral:other_collateral_list', args=[loan_request.id]),
        'summary_url': reverse('collateral:summary', args=[loan_request.id]),
        'gps_weak_threshold_m': pctx['gps_weak_threshold_m'],
        'map_data': map_data,
        'image_rows': image_rows,
        'max_photo_distance_m': pctx['max_photo_distance_m'],
        'required_photo_type_status': required_photo_type_status,
    })


@login_required
@user_passes_test(_can_access_collateral)
def building_image_delete(request, image_id):
    """Delete a building photo before collateral submit (audit logged)."""
    img = get_object_or_404(BuildingImage.objects.select_related('building', 'building__loan_request'), pk=image_id)
    building = img.building
    loan_request = building.loan_request
    if request.method != 'POST':
        return redirect('collateral:field_visit_step', building_id=building.pk, step=3)
    blocked = block_if_collateral_locked(request, loan_request, 'collateral:field_visit_step', building.pk, step=3)
    if blocked:
        return blocked
    payload = {'photo_type': img.photo_type, 'building_id': building.pk}
    img_id = img.pk
    if img.image:
        img.image.delete(save=False)
    img.delete()
    log_collateral_event(
        loan_request, 'photo_deleted', user=request.user,
        subject_type='BuildingImage', subject_id=img_id, payload=payload,
    )
    messages.success(request, 'Photo removed.')
    next_url = request.POST.get('next') or reverse('collateral:field_visit_step', args=[building.pk, 3])
    return redirect(next_url)


@login_required
@user_passes_test(_can_access_collateral)
def land_image_delete(request, image_id):
    img = get_object_or_404(LandValuationImage.objects.select_related('land_valuation', 'land_valuation__loan_request'), pk=image_id)
    land = img.land_valuation
    loan_request = land.loan_request
    if request.method != 'POST':
        return redirect('collateral:land_field_visit_step', loan_request_id=loan_request.pk, step=2)
    blocked = block_if_collateral_locked(request, loan_request, 'collateral:land_field_visit_step', loan_request.pk, step=2)
    if blocked:
        return blocked
    img_id = img.pk
    if img.image:
        img.image.delete(save=False)
    img.delete()
    log_collateral_event(
        loan_request, 'photo_deleted', user=request.user,
        subject_type='LandValuationImage', subject_id=img_id, payload={'land_valuation_id': land.pk},
    )
    messages.success(request, 'Photo removed.')
    next_url = request.POST.get('next') or reverse('collateral:land_field_visit_step', args=[loan_request.pk, 2])
    return redirect(next_url)


@login_required
@user_passes_test(_can_access_collateral)
def other_image_delete(request, image_id):
    img = get_object_or_404(OtherCollateralItemImage.objects.select_related('item', 'item__loan_request'), pk=image_id)
    item = img.item
    loan_request = item.loan_request
    if request.method != 'POST':
        return redirect('collateral:other_field_visit_step', item_id=item.pk, step=2)
    blocked = block_if_collateral_locked(request, loan_request, 'collateral:other_field_visit_step', item.pk, step=2)
    if blocked:
        return blocked
    img_id = img.pk
    if img.image:
        img.image.delete(save=False)
    img.delete()
    log_collateral_event(
        loan_request, 'photo_deleted', user=request.user,
        subject_type='OtherCollateralItemImage', subject_id=img_id, payload={'item_id': item.pk},
    )
    messages.success(request, 'Photo removed.')
    next_url = request.POST.get('next') or reverse('collateral:other_field_visit_step', args=[item.pk, 2])
    return redirect(next_url)


@login_required
@user_passes_test(_can_access_collateral)
def building_images(request, building_id):
    """List and upload images for a building (desktop path; field visit preferred on tablet)."""
    building = get_object_or_404(Building, pk=building_id)
    images = BuildingImage.objects.filter(building=building).order_by('-created_at')
    locked = collateral_is_locked(building.loan_request)
    if request.method == 'POST' and not locked:
        if request.FILES.get('image'):
            ok, msg = save_field_visit_photo(building, request.POST, request.FILES, request.user)
            if ok:
                messages.success(request, msg)
            else:
                messages.error(request, msg)
        else:
            form = BuildingImageForm(request.POST, request.FILES)
            if form.is_valid():
                img = form.save(commit=False)
                img.building = building
                img.uploaded_by = request.user
                if not img.captured_at:
                    img.captured_at = timezone.now()
                img.save()
                messages.success(request, 'Image uploaded.')
        return redirect('collateral:building_images', building_id=building_id)
    form = BuildingImageForm()
    map_data = building_map_data(building)
    image_rows = _annotate_image_distances(building.site_gps_lat, building.site_gps_lon, images)
    return render(request, 'collateral/building_images.html', {
        'building': building,
        'images': images,
        'form': form,
        'image_count': images.count(),
        'min_images_required': _policy_template_context()['min_images_per_building'],
        'photo_types': BuildingImage.PHOTO_TYPE_CHOICES,
        'locked': locked,
        'field_visit_url': reverse('collateral:field_visit', args=[building_id]),
        'map_data': map_data,
        'image_rows': image_rows,
        'max_photo_distance_m': _policy_template_context()['max_photo_distance_m'],
    })


@login_required
@user_passes_test(_can_access_collateral)
def land_valuation(request, loan_request_id):
    """View/edit land valuation for a loan request."""
    loan_request = get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_request_id)
    land, _ = LandValuation.objects.get_or_create(loan_request=loan_request)
    if request.method == 'POST':
        blocked = block_if_collateral_locked(request, loan_request, 'collateral:land_valuation', loan_request_id)
        if blocked:
            return blocked
        form = LandValuationForm(request.POST, instance=land)
        if form.is_valid():
            form.save()
            messages.success(request, 'Land valuation saved.')
            return redirect('collateral:land_valuation', loan_request_id=loan_request_id)
    else:
        form = LandValuationForm(instance=land)
    return render(request, 'collateral/land_valuation.html', {
        'loan_request': loan_request,
        'form': form,
        'land': land,
        'readiness': get_land_readiness(land),
        'locked': collateral_is_locked(loan_request),
        'map_data': land_map_data(land),
        'land_images': list(land.images.select_related('uploaded_by').order_by('-created_at')),
    })


# ---------- Other collateral types (vehicle, machinery, equipment, etc.) ----------

@login_required
@user_passes_test(_can_access_collateral)
def other_collateral_add(request, loan_request_id):
    """Start field visit for a new movable collateral item (vehicle, machinery, etc.)."""
    if request.method != 'POST':
        return redirect('collateral:other_collateral_list', loan_request_id=loan_request_id)
    loan_request = get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_request_id)
    blocked = block_if_collateral_locked(request, loan_request, 'collateral:other_collateral_list', loan_request_id)
    if blocked:
        return blocked
    item = OtherCollateralItem.objects.create(
        loan_request=loan_request,
        name='Collateral item',
        estimated_value=Decimal('0'),
    )
    messages.info(request, 'Enter asset details on step 1, then add photos.')
    return redirect('collateral:other_field_visit', item_id=item.pk)


@login_required
@user_passes_test(_can_access_collateral)
def other_collateral_list(request, loan_request_id):
    """List movable collateral items for a loan."""
    loan_request = get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_request_id)
    items = OtherCollateralItem.objects.filter(loan_request=loan_request).order_by('name')
    total_other = sum(item.estimated_value for item in items)
    item_rows = [{'item': i, 'readiness': get_other_item_readiness(i)} for i in items]
    collateral_label = loan_request.collateral.name if loan_request.collateral_id else 'Collateral'
    return render(request, 'collateral/other_collateral_list.html', {
        'loan_request': loan_request,
        'items': items,
        'item_rows': item_rows,
        'total_other': total_other,
        'locked': collateral_is_locked(loan_request),
        'collateral_label': collateral_label,
    })


@login_required
@user_passes_test(_can_access_collateral)
def other_collateral_edit(request, item_id):
    item = get_object_or_404(OtherCollateralItem, pk=item_id)
    loan_request = item.loan_request
    if request.method == 'POST':
        blocked = block_if_collateral_locked(request, loan_request, 'collateral:other_collateral_list', loan_request.id)
        if blocked:
            return blocked
        form = OtherCollateralItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, 'Collateral item updated.')
            return redirect('collateral:other_collateral_list', loan_request_id=loan_request.id)
    else:
        form = OtherCollateralItemForm(instance=item)
    return render(request, 'collateral/other_collateral_form.html', {
        'form': form,
        'item': item,
        'loan_request': loan_request,
        'is_edit': True,
    })


@login_required
@user_passes_test(_can_access_collateral)
def other_collateral_delete(request, item_id):
    item = get_object_or_404(OtherCollateralItem, pk=item_id)
    loan_request_id = item.loan_request_id
    loan_request = item.loan_request
    if request.method != 'POST':
        return redirect('collateral:other_collateral_list', loan_request_id=loan_request_id)
    blocked = block_if_collateral_locked(request, loan_request, 'collateral:other_collateral_list', loan_request_id)
    if blocked:
        return blocked
    item.delete()
    messages.success(request, 'Collateral item removed.')
    return redirect('collateral:other_collateral_list', loan_request_id=loan_request_id)


@login_required
@user_passes_test(_can_access_collateral)
def summary(request, loan_request_id):
    """Collateral summary: one page per loan. Shows only the section matching the loan's collateral type (buildings, land, or other)."""
    loan_request = get_object_or_404(
        _collateral_eligible_loans(request.user).select_related('collateral', 'collateral_submitted_by'),
        pk=loan_request_id,
    )
    ct = (loan_request.collateral.name or '').lower()
    buildings = Building.objects.filter(loan_request=loan_request).prefetch_related(
        'buildingvaluation_set__sub_work', 'buildingvaluation_set__sub_sub_work'
    )
    building_totals = []
    for b in buildings:
        rows = BuildingValuation.objects.filter(building=b)
        total_val = sum(r.total for r in rows)
        building_totals.append({'building': b, 'total': total_val})
    try:
        land = LandValuation.objects.get(loan_request=loan_request)
        land_value = land.total_value or Decimal('0')
    except LandValuation.DoesNotExist:
        land_value = Decimal('0')
    other_items = OtherCollateralItem.objects.filter(loan_request=loan_request)
    total_other = sum(item.estimated_value or Decimal('0') for item in other_items)
    total_buildings = sum(bt['total'] for bt in building_totals)
    # Grand total only for the collateral type this loan has
    if 'building' in ct or 'house' in ct or 'construction' in ct:
        grand_total = total_buildings
    elif 'land' in ct:
        grand_total = land_value
    elif any(x in ct for x in ('vehicle', 'machinery', 'equipment', 'other')):
        grand_total = total_other
    else:
        grand_total = total_buildings + land_value + total_other
    # For building collateral: require at least 5 images per building before submit
    policy_ctx = _policy_template_context()
    min_bldg = policy_ctx['min_images_per_building']
    buildings_below_image_min = []
    loan_readiness = get_loan_collateral_readiness(loan_request)
    if loan_readiness['applies']:
        buildings_below_image_min = [
            item['building'] for item in loan_readiness['buildings']
            if item['readiness']['image_count'] < min_bldg
        ]
    coverage = compute_coverage_adequacy(loan_request)
    submit_blockers = collateral_submit_blockers(loan_request)
    can_submit_collateral = (
        loan_readiness.get('all_ready', True)
        and loan_readiness.get('applies', False)
        and coverage.get('adequate_for_submit', True)
        and not submit_blockers
    )
    if not loan_readiness.get('applies'):
        can_submit_collateral = True
    if loan_readiness.get('locked'):
        can_submit_collateral = False
    pending_unlock = CollateralUnlockRequest.objects.filter(
        loan_request=loan_request, status=CollateralUnlockRequest.STATUS_PENDING,
    ).first()
    building_map_sections = [
        {
            'building': b,
            'map_data': building_map_data(b),
            'map_id': f'summary-bmap-{b.pk}',
            'map_config_id': f'summary-bmap-data-{b.pk}',
        }
        for b in buildings.select_related('city', 'city__zone', 'city__zone__region')
    ]
    land_map_section = None
    try:
        land_obj = LandValuation.objects.get(loan_request=loan_request)
        land_map_section = land_map_data(land_obj)
    except LandValuation.DoesNotExist:
        pass
    other_map_sections = [
        {
            'item': item,
            'map_data': other_item_map_data(item),
            'map_id': f'summary-other-{item.pk}',
            'map_config_id': f'summary-other-data-{item.pk}',
        }
        for item in other_items
    ]
    return render(request, 'collateral/summary.html', {
        'loan_request': loan_request,
        'collateral_type_lower': ct,
        'building_totals': building_totals,
        'land_value': land_value,
        'other_items': other_items,
        'total_other': total_other,
        'total_buildings': total_buildings,
        'grand_total': grand_total,
        'buildings_below_image_min': buildings_below_image_min,
        'min_images_per_building': min_bldg,
        'can_submit_collateral': can_submit_collateral,
        'loan_readiness': loan_readiness,
        'submit_blockers': submit_blockers,
        'coverage': coverage,
        'collateral_policy': policy_ctx['collateral_policy'],
        'can_request_unlock': _can_request_collateral_unlock(request.user, loan_request),
        'pending_unlock': pending_unlock,
        'building_map_sections': building_map_sections,
        'land_map_section': land_map_section,
        'other_map_sections': other_map_sections,
    })


@login_required
@user_passes_test(_can_access_collateral)
def collateral_submit(request, loan_request_id):
    """Submit collateral estimation for this loan. Requires at least one image per building (for building collateral)."""
    if request.method != 'POST':
        return redirect('collateral:summary', loan_request_id=loan_request_id)
    loan_request = get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_request_id)
    blockers = collateral_submit_blockers(loan_request)
    if blockers:
        for msg in blockers:
            messages.error(request, msg)
        return redirect('collateral:summary', loan_request_id=loan_request_id)
    loan_request.collateral_submitted_at = timezone.now()
    loan_request.collateral_submitted_by = request.user
    from .engineering_qa import initial_engineering_status
    from loans.models import LoanRequest

    eng_status = initial_engineering_status(request.user)
    loan_request.collateral_engineering_status = eng_status
    if eng_status == LoanRequest.ENG_COLLATERAL_APPROVED:
        loan_request.collateral_engineering_reviewed_at = timezone.now()
        loan_request.collateral_engineering_reviewed_by = request.user
    update_fields = [
        'collateral_submitted_at', 'collateral_submitted_by', 'collateral_engineering_status',
    ]
    if eng_status == LoanRequest.ENG_COLLATERAL_APPROVED:
        update_fields.extend(['collateral_engineering_reviewed_at', 'collateral_engineering_reviewed_by'])
    loan_request.save(update_fields=update_fields)
    log_collateral_event(
        loan_request,
        'collateral_submitted',
        user=request.user,
        payload={
            'submitted_at': loan_request.collateral_submitted_at.isoformat(),
            'engineering_status': eng_status,
        },
    )
    if eng_status == LoanRequest.ENG_COLLATERAL_PENDING:
        from .services.notifications import engineering_review_recipients, notify_collateral_submitted
        notify_collateral_submitted(loan_request, recipients=engineering_review_recipients(loan_request))
    from loans.models import LoanAppraisal
    from loans.services.appraisal_prefill import sync_collateral_to_appraisal

    appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    if appraisal:
        synced = sync_collateral_to_appraisal(loan_request, appraisal, only_empty=False)
        if synced:
            messages.info(request, 'Appraisal updated: ' + '; '.join(synced))
    messages.success(
        request,
        'Collateral estimation submitted. All collateral data (buildings, valuations, land, other) is saved.',
    )
    return redirect('collateral:summary', loan_request_id=loan_request_id)


@login_required
@user_passes_test(_can_access_collateral)
def building_estimation_summary(request, building_id):
    """Building collateral estimation summary: መጠቃለሊ with LOCATION, work items by MainWork, subtotals ሀ/ለ, grand total."""
    building = get_object_or_404(Building, pk=building_id)
    rows = (
        BuildingValuation.objects.filter(building=building)
        .select_related('sub_work', 'sub_work__main_work', 'sub_sub_work', 'sub_sub_work__sub_work', 'sub_sub_work__sub_work__main_work')
        .order_by('sub_work__main_work__order', 'sub_work__order', 'sub_sub_work__order')
    )
    # Group by MainWork: list of (row_num, description, value), subtotal
    groups = OrderedDict()
    for r in rows:
        mw = r.sub_work.main_work if r.sub_work_id else r.sub_sub_work.sub_work.main_work
        if mw not in groups:
            groups[mw] = {'main_work': mw, 'rows': [], 'subtotal': Decimal('0')}
        desc = r.sub_work.name if r.sub_work_id else r.sub_sub_work.name
        groups[mw]['rows'].append((len(groups[mw]['rows']) + 1, desc, r.total))
        groups[mw]['subtotal'] += r.total
    section_list = list(groups.values())
    total_a = section_list[0]['subtotal'] if section_list else Decimal('0')
    total_b = sum(s['subtotal'] for s in section_list[1:]) if len(section_list) > 1 else Decimal('0')
    grand_total = sum(s['subtotal'] for s in section_list)
    location_label = building.city.name if building.city_id else building.name
    return render(request, 'collateral/building_estimation_summary.html', {
        'building': building,
        'section_list': section_list,
        'total_a': total_a,
        'total_b': total_b,
        'grand_total': grand_total,
        'location_label': location_label,
    })


# ---------- Unit price catalog (per woreda) – for engineering team, not tied to loans ----------

def _can_manage_unit_prices(user):
    """Only engineering team (and admin) can manage catalog and unit prices."""
    return user.role in ('engineering_head', 'engineer', 'admin', 'superadmin')


# ---------- Catalog: Main Work, Sub Work, Sub-Sub Work (engineering only) ----------

@login_required
@user_passes_test(_can_manage_unit_prices)
def catalog_index(request):
    """Catalog home: links to Main Work, Sub Work, Sub-Sub Work, Unit prices."""
    return render(request, 'collateral/catalog_index.html', {})


@login_required
@user_passes_test(_can_manage_unit_prices)
def main_work_list(request):
    """List Main Work items (ጠቅላላ ስራሕ)."""
    items = MainWork.objects.all().order_by('order', 'name')
    return render(request, 'collateral/main_work_list.html', {'items': items})


@login_required
@user_passes_test(_can_manage_unit_prices)
def main_work_add(request):
    if request.method == 'POST':
        form = MainWorkForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Main work added.')
            return redirect('collateral:main_work_list')
    else:
        form = MainWorkForm()
    return render(request, 'collateral/main_work_form.html', {'form': form, 'is_edit': False})


@login_required
@user_passes_test(_can_manage_unit_prices)
def main_work_edit(request, main_work_id):
    item = get_object_or_404(MainWork, pk=main_work_id)
    if request.method == 'POST':
        form = MainWorkForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, 'Main work updated.')
            return redirect('collateral:main_work_list')
    else:
        form = MainWorkForm(instance=item)
    return render(request, 'collateral/main_work_form.html', {'form': form, 'item': item, 'is_edit': True})


@login_required
@user_passes_test(_can_manage_unit_prices)
def sub_work_list(request):
    """List Sub Work items; optional filter by main_work_id."""
    qs = SubWork.objects.all().select_related('main_work').order_by('main_work__order', 'main_work__name', 'order', 'name')
    main_work_id = request.GET.get('main_work_id')
    try:
        main_work_id = int(main_work_id) if main_work_id else None
    except ValueError:
        main_work_id = None
    if main_work_id:
        qs = qs.filter(main_work_id=main_work_id)
    return render(request, 'collateral/sub_work_list.html', {
        'items': qs,
        'main_works': MainWork.objects.all().order_by('order', 'name'),
        'selected_main_work_id': main_work_id,
    })


@login_required
@user_passes_test(_can_manage_unit_prices)
def sub_work_add(request):
    if request.method == 'POST':
        form = SubWorkForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Sub work added.')
            return redirect('collateral:sub_work_list')
    else:
        form = SubWorkForm()
    return render(request, 'collateral/sub_work_form.html', {'form': form, 'is_edit': False})


@login_required
@user_passes_test(_can_manage_unit_prices)
def sub_work_edit(request, sub_work_id):
    item = get_object_or_404(SubWork, pk=sub_work_id)
    if request.method == 'POST':
        form = SubWorkForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, 'Sub work updated.')
            return redirect('collateral:sub_work_list')
    else:
        form = SubWorkForm(instance=item)
    return render(request, 'collateral/sub_work_form.html', {'form': form, 'item': item, 'is_edit': True})


@login_required
@user_passes_test(_can_manage_unit_prices)
def sub_sub_work_list(request):
    """List Sub-Sub Work items; optional filter by sub_work_id."""
    qs = SubSubWork.objects.all().select_related('sub_work', 'sub_work__main_work').order_by(
        'sub_work__main_work__order', 'sub_work__main_work__name', 'sub_work__order', 'sub_work__name', 'order', 'name'
    )
    sub_work_id = request.GET.get('sub_work_id')
    try:
        sub_work_id = int(sub_work_id) if sub_work_id else None
    except ValueError:
        sub_work_id = None
    if sub_work_id:
        qs = qs.filter(sub_work_id=sub_work_id)
    return render(request, 'collateral/sub_sub_work_list.html', {
        'items': qs,
        'sub_works': SubWork.objects.all().select_related('main_work').order_by('main_work__order', 'main_work__name', 'order', 'name'),
        'selected_sub_work_id': sub_work_id,
    })


@login_required
@user_passes_test(_can_manage_unit_prices)
def sub_sub_work_add(request):
    if request.method == 'POST':
        form = SubSubWorkForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Sub-sub work added.')
            return redirect('collateral:sub_sub_work_list')
    else:
        form = SubSubWorkForm()
    return render(request, 'collateral/sub_sub_work_form.html', {'form': form, 'is_edit': False})


@login_required
@user_passes_test(_can_manage_unit_prices)
def sub_sub_work_edit(request, sub_sub_work_id):
    item = get_object_or_404(SubSubWork, pk=sub_sub_work_id)
    if request.method == 'POST':
        form = SubSubWorkForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, 'Sub-sub work updated.')
            return redirect('collateral:sub_sub_work_list')
    else:
        form = SubSubWorkForm(instance=item)
    return render(request, 'collateral/sub_sub_work_form.html', {'form': form, 'item': item, 'is_edit': True})


# ---------- AJAX: cascade for unit price form (Main work → Sub work → Sub-sub work) ----------

@login_required
@user_passes_test(_can_manage_unit_prices)
def ajax_load_sub_works(request):
    """Return sub works for a main work (JSON)."""
    main_work_id = request.GET.get('main_work_id')
    if not main_work_id:
        return JsonResponse([], safe=False)
    items = SubWork.objects.filter(main_work_id=main_work_id).order_by('order', 'name')
    return JsonResponse(list(items.values('id', 'name', 'order')), safe=False)


@login_required
@user_passes_test(_can_manage_unit_prices)
def ajax_load_sub_sub_works(request):
    """Return sub-sub works for a sub work (JSON)."""
    sub_work_id = request.GET.get('sub_work_id')
    if not sub_work_id:
        return JsonResponse([], safe=False)
    items = SubSubWork.objects.filter(sub_work_id=sub_work_id).order_by('order', 'name')
    return JsonResponse(list(items.values('id', 'name', 'order')), safe=False)


# ---------- Unit price catalog (per woreda) ----------

@login_required
@user_passes_test(_can_manage_unit_prices)
def unit_price_list(request):
    """List unit prices per woreda (SubWork or SubSubWork × City). No loan involved."""
    prices = SubWorkUnitPrice.objects.select_related(
        'sub_work', 'sub_work__main_work',
        'sub_sub_work', 'sub_sub_work__sub_work', 'sub_sub_work__sub_work__main_work',
        'city', 'city__zone', 'city__zone__region'
    ).order_by('city__zone__region', 'city__zone', 'city', 'sub_work', 'sub_sub_work')
    city_id = request.GET.get('city_id')
    if city_id:
        prices = prices.filter(city_id=city_id)
    paginator = Paginator(prices, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'collateral/unit_price_list.html', {
        'page_obj': page_obj,
        'prices': page_obj,
        'selected_city_id': city_id,
    })


@login_required
@user_passes_test(_can_manage_unit_prices)
def unit_price_add(request):
    """Add unit price: Region→Zone→City and Main work→Sub work→Sub-sub work cascades."""
    if request.method == 'POST':
        form = SubWorkUnitPriceForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Unit price saved.')
            return redirect('collateral:unit_price_list')
    else:
        form = SubWorkUnitPriceForm()
        form.fields['city'].queryset = form.fields['city'].queryset.none()
        form.fields['sub_work'].queryset = SubWork.objects.none()
        form.fields['sub_sub_work'].queryset = SubSubWork.objects.none()
    regions = Region.objects.all().order_by('name')
    main_works = MainWork.objects.all().order_by('order', 'name')
    return render(request, 'collateral/unit_price_form.html', {
        'form': form,
        'regions': regions,
        'main_works': main_works,
        'is_edit': False,
        'price': None,
        'zones_url': request.build_absolute_uri(reverse('ajax_load_zones_by_region')),
        'cities_url': request.build_absolute_uri(reverse('ajax_load_cities_by_zone')),
        'sub_works_url': request.build_absolute_uri(reverse('collateral:ajax_load_sub_works')),
        'sub_sub_works_url': request.build_absolute_uri(reverse('collateral:ajax_load_sub_sub_works')),
    })


@login_required
@user_passes_test(_can_manage_unit_prices)
def unit_price_edit(request, price_id):
    """Edit unit price."""
    price = get_object_or_404(SubWorkUnitPrice, pk=price_id)
    if request.method == 'POST':
        form = SubWorkUnitPriceForm(request.POST, instance=price)
        if form.is_valid():
            form.save()
            messages.success(request, 'Unit price updated.')
            return redirect('collateral:unit_price_list')
    else:
        form = SubWorkUnitPriceForm(instance=price)
        form.fields['city'].queryset = form.fields['city'].queryset.filter(
            zone=price.city.zone
        ).order_by('name')
        if price.sub_sub_work_id:
            form.fields['sub_work'].queryset = SubWork.objects.filter(pk=price.sub_sub_work.sub_work_id).order_by('order', 'name')
            form.fields['sub_sub_work'].queryset = SubSubWork.objects.filter(
                sub_work=price.sub_sub_work.sub_work
            ).select_related('sub_work', 'sub_work__main_work').order_by('order', 'name')
        else:
            form.fields['sub_work'].queryset = SubWork.objects.filter(pk=price.sub_work_id).order_by('order', 'name')
            form.fields['sub_sub_work'].queryset = SubSubWork.objects.none()
    regions = Region.objects.all().order_by('name')
    main_works = MainWork.objects.all().order_by('order', 'name')
    return render(request, 'collateral/unit_price_form.html', {
        'form': form,
        'price': price,
        'regions': regions,
        'main_works': main_works,
        'is_edit': True,
        'zones_url': request.build_absolute_uri(reverse('ajax_load_zones_by_region')),
        'cities_url': request.build_absolute_uri(reverse('ajax_load_cities_by_zone')),
        'sub_works_url': request.build_absolute_uri(reverse('collateral:ajax_load_sub_works')),
        'sub_sub_works_url': request.build_absolute_uri(reverse('collateral:ajax_load_sub_sub_works')),
    })
