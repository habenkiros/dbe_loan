# collateral/views.py
from collections import OrderedDict
from decimal import Decimal
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Q
from loans.models import LoanRequest, Region
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


def _collateral_eligible_loans():
    """Loan requests eligible for collateral: queue_approved or status=Approved."""
    return LoanRequest.objects.filter(
        Q(queue_approved=True) | Q(status__iexact='Approved')
    )


@login_required
@user_passes_test(_can_access_collateral)
def dashboard(request):
    """List loan requests eligible for collateral (queue_approved or Approved); link to their collateral."""
    loan_requests = _collateral_eligible_loans().select_related(
        'branch', 'district'
    ).order_by('-date_requested')
    q = request.GET.get('q')
    if q:
        loan_requests = loan_requests.filter(
            Q(loan_request_id__icontains=q) |
            Q(applicant_name__icontains=q) |
            Q(phone_number__icontains=q)
        )
    return render(request, 'collateral/dashboard.html', {
        'loan_requests': loan_requests,
        'query': q or '',
    })


@login_required
@user_passes_test(_can_access_collateral)
def building_list(request, loan_request_id):
    """List buildings for a loan request; add building."""
    loan_request = get_object_or_404(_collateral_eligible_loans(), pk=loan_request_id)
    buildings = Building.objects.filter(loan_request=loan_request).select_related('city')
    return render(request, 'collateral/building_list.html', {
        'loan_request': loan_request,
        'buildings': buildings,
    })


@login_required
@user_passes_test(_can_access_collateral)
def building_add(request, loan_request_id):
    """Add a building to a loan request."""
    loan_request = get_object_or_404(_collateral_eligible_loans(), pk=loan_request_id)
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
    return render(request, 'collateral/building_form.html', {
        'loan_request': loan_request,
        'form': form,
        'is_edit': False,
    })


@login_required
@user_passes_test(_can_access_collateral)
def building_edit(request, building_id):
    """Edit a building."""
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
    return render(request, 'collateral/building_form.html', {
        'loan_request': loan_request,
        'building': building,
        'form': form,
        'is_edit': True,
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
    """Get unit price from SubWorkUnitPrice for building's city and sub_work or sub_sub_work."""
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


def _build_work_choices(existing_sub_work_ids, existing_sub_sub_work_ids):
    """Build optgroup choices for work item dropdown: (group_label, [(value, label), ...])."""
    from collections import OrderedDict
    groups = OrderedDict()
    for mw in MainWork.objects.all().order_by('order', 'name'):
        for sw in SubWork.objects.filter(main_work=mw).order_by('order', 'name'):
            key = f"{mw.name} → {sw.name}"
            options = []
            if sw.id not in existing_sub_work_ids:
                options.append((f"sub_work:{sw.id}", f"{sw.name} (sub work only)"))
            for ssw in SubSubWork.objects.filter(sub_work=sw).order_by('order', 'name'):
                if ssw.id not in existing_sub_sub_work_ids:
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
    work_choices = _build_work_choices(existing_sub_work_ids, existing_sub_sub_work_ids)
    if request.method == 'POST':
        work_item = request.POST.get('work_item')
        sub_work_id, sub_sub_work_id = _parse_work_item(work_item)
        data = request.POST.copy()
        data.setdefault('sub_work', sub_work_id or '')
        data.setdefault('sub_sub_work', sub_sub_work_id or '')
        form = BuildingValuationForm(data, can_edit_unit_price=can_edit_unit_price)
        if form.is_valid():
            sub_work = form.cleaned_data.get('sub_work')
            sub_sub_work = form.cleaned_data.get('sub_sub_work')
            if sub_work and sub_work.id in existing_sub_work_ids:
                messages.error(request, 'This item is already added for this building.')
                return render(request, 'collateral/valuation_form.html', {
                    'building': building, 'form': form, 'work_choices': work_choices,
                    'is_edit': False, 'can_edit_unit_price': can_edit_unit_price, 'selected_work_item': work_item,
                })
            if sub_sub_work and sub_sub_work.id in existing_sub_sub_work_ids:
                messages.error(request, 'This item is already added for this building.')
                return render(request, 'collateral/valuation_form.html', {
                    'building': building, 'form': form, 'work_choices': work_choices,
                    'is_edit': False, 'can_edit_unit_price': can_edit_unit_price, 'selected_work_item': work_item,
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
                return render(request, 'collateral/valuation_form.html', {
                    'building': building, 'form': form, 'work_choices': work_choices,
                    'is_edit': False, 'can_edit_unit_price': can_edit_unit_price, 'selected_work_item': work_item,
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
    return render(request, 'collateral/valuation_form.html', {
        'building': building,
        'form': form,
        'work_choices': work_choices,
        'is_edit': False,
        'can_edit_unit_price': can_edit_unit_price,
    })


@login_required
@user_passes_test(_can_access_collateral)
def valuation_edit(request, valuation_id):
    """Edit quantity (and unit price only for engineers). Loan officers: quantity only; unit price from catalog."""
    row = get_object_or_404(BuildingValuation, pk=valuation_id)
    building = row.building
    can_edit_unit_price = _user_can_edit_unit_price(request.user)
    if request.method == 'POST':
        data = request.POST.copy()
        data.setdefault('sub_work', row.sub_work_id or '')
        data.setdefault('sub_sub_work', row.sub_sub_work_id or '')
        form = BuildingValuationForm(data, instance=row, can_edit_unit_price=can_edit_unit_price)
        if form.is_valid():
            obj = form.save(commit=False)
            if not can_edit_unit_price:
                catalog_price = _get_unit_price_for_building(
                    building, sub_work=row.sub_work, sub_sub_work=row.sub_sub_work
                )
                if catalog_price is not None:
                    obj.unit_price = catalog_price
            obj.save()
            messages.success(request, 'Valuation row updated.')
            return redirect('collateral:valuation_list', building_id=building.id)
    else:
        form = BuildingValuationForm(instance=row, can_edit_unit_price=can_edit_unit_price)
    # Hide work item fields on edit (user only changes quantity / unit price)
    form.fields.pop('sub_work', None)
    form.fields.pop('sub_sub_work', None)
    return render(request, 'collateral/valuation_form.html', {
        'building': building,
        'form': form,
        'row': row,
        'is_edit': True,
        'can_edit_unit_price': can_edit_unit_price,
    })


@login_required
@user_passes_test(_can_access_collateral)
def valuation_delete(request, valuation_id):
    """Delete a valuation row."""
    row = get_object_or_404(BuildingValuation, pk=valuation_id)
    building_id = row.building_id
    row.delete()
    messages.success(request, 'Valuation row removed.')
    return redirect('collateral:valuation_list', building_id=building_id)


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
    return render(request, 'collateral/building_images.html', {
        'building': building,
        'images': images,
        'form': form,
    })


@login_required
@user_passes_test(_can_access_collateral)
def land_valuation(request, loan_request_id):
    """View/edit land valuation for a loan request."""
    loan_request = get_object_or_404(_collateral_eligible_loans(), pk=loan_request_id)
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
    loan_request = get_object_or_404(_collateral_eligible_loans(), pk=loan_request_id)
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
    """Collateral summary: building totals + land + other collateral = total collateral value."""
    loan_request = get_object_or_404(_collateral_eligible_loans(), pk=loan_request_id)
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
    total_other = sum(item.estimated_value for item in other_items)
    total_buildings = sum(bt['total'] for bt in building_totals)
    grand_total = total_buildings + land_value + total_other
    return render(request, 'collateral/summary.html', {
        'loan_request': loan_request,
        'building_totals': building_totals,
        'land_value': land_value,
        'other_items': other_items,
        'total_other': total_other,
        'total_buildings': total_buildings,
        'grand_total': grand_total,
    })


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
