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
    Building, BuildingValuation, BuildingImage, LandValuation,
    OtherCollateralItem,
)
from .forms import (
    BuildingForm, BuildingValuationForm, BuildingImageForm, LandValuationForm,
    SubWorkUnitPriceForm, _user_can_edit_unit_price,
    MainWorkForm, SubWorkForm, SubSubWorkForm,
    OtherCollateralItemForm,
)


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
    return render(request, 'collateral/dashboard.html', {
        'loan_requests': loan_requests,
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
    return render(request, 'collateral/building_list.html', {
        'loan_request': loan_request,
        'buildings': buildings,
        'collateral_type_lower': ct,
    })


@login_required
@user_passes_test(_can_access_collateral)
def building_add(request, loan_request_id):
    """Add a building to a loan request. City/woreda chosen via Region → Zone → City cascade."""
    loan_request = get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_request_id)
    if request.method == 'POST':
        form = BuildingForm(request.POST)
        if form.is_valid():
            building = form.save(commit=False)
            building.loan_request = loan_request
            building.save()
            messages.success(request, f'Building "{building.name}" added.')
            return redirect('collateral:building_list', loan_request_id=loan_request_id)
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
    })


def _get_unit_price_for_building(building, sub_work=None, sub_sub_work=None):
    """Get unit price from SubWorkUnitPrice for building's city (woreda) and sub_work or sub_sub_work."""
    if not building.city_id:
        return None
    if sub_sub_work:
        try:
            up = SubWorkUnitPrice.objects.get(sub_sub_work=sub_sub_work, city=building.city)
            return up.unit_price
        except SubWorkUnitPrice.DoesNotExist:
            return None
    if sub_work:
        try:
            up = SubWorkUnitPrice.objects.get(sub_work=sub_work, city=building.city)
            return up.unit_price
        except SubWorkUnitPrice.DoesNotExist:
            return None
    return None


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
    """Editing estimation results is disabled."""
    row = get_object_or_404(BuildingValuation, pk=valuation_id)
    messages.info(request, 'Editing estimation results is disabled.')
    return redirect('collateral:valuation_list', building_id=row.building_id)


@login_required
@user_passes_test(_can_access_collateral)
def valuation_add_multiple(request, building_id):
    """Add multiple valuation rows at once: one quantity per available work item."""
    building = get_object_or_404(Building, pk=building_id)
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


@login_required
@user_passes_test(_can_access_collateral)
def valuation_delete(request, valuation_id):
    """Deleting estimation results is disabled."""
    row = get_object_or_404(BuildingValuation, pk=valuation_id)
    messages.info(request, 'Editing and deleting estimation results is disabled.')
    return redirect('collateral:valuation_list', building_id=row.building_id)


@login_required
@user_passes_test(_can_access_collateral)
def building_images(request, building_id):
    """List and upload images for a building."""
    building = get_object_or_404(Building, pk=building_id)
    images = BuildingImage.objects.filter(building=building).order_by('-created_at')
    if request.method == 'POST':
        form = BuildingImageForm(request.POST, request.FILES)
        if form.is_valid():
            img = form.save(commit=False)
            img.building = building
            img.uploaded_by = request.user
            img.save()
            messages.success(request, 'Image uploaded.')
            return redirect('collateral:building_images', building_id=building_id)
    else:
        form = BuildingImageForm()
    image_count = images.count()
    min_images_required = 5
    return render(request, 'collateral/building_images.html', {
        'building': building,
        'images': images,
        'form': form,
        'image_count': image_count,
        'min_images_required': min_images_required,
    })


@login_required
@user_passes_test(_can_access_collateral)
def land_valuation(request, loan_request_id):
    """View/edit land valuation for a loan request."""
    loan_request = get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_request_id)
    land, _ = LandValuation.objects.get_or_create(loan_request=loan_request)
    if request.method == 'POST':
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
    })


# ---------- Other collateral types (vehicle, machinery, equipment, etc.) ----------

@login_required
@user_passes_test(_can_access_collateral)
def other_collateral_list(request, loan_request_id):
    """List and add other collateral items (vehicle, machinery, etc.) for a loan."""
    loan_request = get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_request_id)
    items = OtherCollateralItem.objects.filter(loan_request=loan_request).order_by('name')
    total_other = sum(item.estimated_value for item in items)
    if request.method == 'POST':
        form = OtherCollateralItemForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.loan_request = loan_request
            obj.save()
            messages.success(request, 'Collateral item added.')
            return redirect('collateral:other_collateral_list', loan_request_id=loan_request_id)
    else:
        form = OtherCollateralItemForm()
    return render(request, 'collateral/other_collateral_list.html', {
        'loan_request': loan_request,
        'items': items,
        'total_other': total_other,
        'form': form,
    })


@login_required
@user_passes_test(_can_access_collateral)
def other_collateral_edit(request, item_id):
    item = get_object_or_404(OtherCollateralItem, pk=item_id)
    loan_request = item.loan_request
    if request.method == 'POST':
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
    MIN_IMAGES_PER_BUILDING = 5
    buildings_below_image_min = []
    if 'building' in ct or 'house' in ct or 'construction' in ct:
        buildings_below_image_min = list(
            Building.objects.filter(loan_request=loan_request)
            .annotate(image_count=Count('buildingimage'))
            .filter(image_count__lt=MIN_IMAGES_PER_BUILDING)
        )
    can_submit_collateral = len(buildings_below_image_min) == 0
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
        'min_images_per_building': MIN_IMAGES_PER_BUILDING,
        'can_submit_collateral': can_submit_collateral,
    })


@login_required
@user_passes_test(_can_access_collateral)
def collateral_submit(request, loan_request_id):
    """Submit collateral estimation for this loan. Requires at least one image per building (for building collateral)."""
    if request.method != 'POST':
        return redirect('collateral:summary', loan_request_id=loan_request_id)
    loan_request = get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_request_id)
    ct = (loan_request.collateral.name or '').lower()
    MIN_IMAGES_PER_BUILDING = 5
    # For building-type collateral: require at least 5 images per building
    if 'building' in ct or 'house' in ct or 'construction' in ct:
        buildings_below_min = list(
            Building.objects.filter(loan_request=loan_request)
            .annotate(image_count=Count('buildingimage'))
            .filter(image_count__lt=MIN_IMAGES_PER_BUILDING)
        )
        if buildings_below_min:
            names = ', '.join(b.name for b in buildings_below_min)
            messages.error(
                request,
                'At least %d images are required for each building before submitting. '
                'Add more images for: %s.' % (MIN_IMAGES_PER_BUILDING, names),
            )
            return redirect('collateral:summary', loan_request_id=loan_request_id)
    loan_request.collateral_submitted_at = timezone.now()
    loan_request.collateral_submitted_by = request.user
    loan_request.save(update_fields=['collateral_submitted_at', 'collateral_submitted_by'])
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
    return render(request, 'collateral/unit_price_list.html', {
        'prices': prices,
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
