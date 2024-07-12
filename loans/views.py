# loans/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Zone, Branch, LoanCategory, CollateralType, LoanRequest, CustomUser, LatestLoanRequestID
from .forms import CustomUserCreationForm, CustomUserChangeForm, LoanRequestForm, ZoneForm, BranchForm, LoanCategoryForm, CollateralTypeForm
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q

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
    return render(request, 'loans/manage_users.html', {'users': users})


@login_required
@user_passes_test(lambda u: u.is_superuser)
def edit_user(request, id):
    user = get_object_or_404(CustomUser, pk=id)
    if request.method == 'POST':
        form = CustomUserChangeForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            return redirect('manage_users')
    else:
        form = CustomUserChangeForm(instance=user)
    return render(request, 'loans/edit_user.html', {'form': form, 'user': user})

@login_required
@user_passes_test(lambda u: u.role == 'loan_officer')
def create_loan_request(request):
    if request.method == 'POST':
        form = LoanRequestForm(request.POST)
        if form.is_valid():
            loan_request = form.save(commit=False)
            loan_request.branch = request.user.branch
            loan_request.loan_request_id = generate_incremental_loan_request_id()
            loan_request.save()
            return redirect('view_loan_requests')
    else:
        form = LoanRequestForm()
    return render(request, 'loans/create_loan_request.html', {'form': form})

def generate_incremental_loan_request_id():
    latest_id_instance, created = LatestLoanRequestID.objects.get_or_create(pk=1)
    latest_id = latest_id_instance.latest_id + 1
    latest_id_instance.latest_id = latest_id
    latest_id_instance.save()
    return f"DECSI-{latest_id:015d}"

# loans/views.py

@login_required
@user_passes_test(lambda u: u.role in ['operation_manager', 'finance_manager'])
def update_loan_request_status(request, loan_request_id):
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if request.method == 'POST':
        if 'operation_manager' in request.POST and request.user.role == 'operation_manager':
            loan_request.operation_manager_approval = request.POST.get('operation_manager_approval') == 'True'
        elif 'finance_manager' in request.POST and request.user.role == 'finance_manager':
            loan_request.finance_approval = request.POST.get('finance_approval') == 'True'
        loan_request.save()
        return redirect('view_loan_requests')
    return render(request, 'loans/update_loan_request_status.html', {'loan_request': loan_request})

# loans/views.py

@login_required
@user_passes_test(lambda u: u.role in ['loan_officer', 'operational_manager', 'finance'])
def loan_request_detail(request, loan_request_id):
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    return render(request, 'loans/loan_request_detail.html', {'loan_request': loan_request})

@login_required
@user_passes_test(lambda u: u.role in ['operational_manager'])
def loan_request_detail_operation_manager(request, loan_request_id):
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    return render(request, 'loans/loan_request_detail_operation_manager.html', {'loan_request': loan_request})

@login_required
@user_passes_test(lambda u: u.role in ['finance'])
def loan_request_detail_finance(request, loan_request_id):
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    return render(request, 'loans/loan_request_detail-finance.html', {'loan_request': loan_request})


@login_required
@user_passes_test(lambda u: u.role == 'loan_officer')
def view_loan_requests(request):
    loan_requests = LoanRequest.objects.filter(branch=request.user.branch)
    
    # Filtering
    zone_id = request.GET.get('zone_id')
    branch_id = request.GET.get('branch_id')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    status = request.GET.get('status')

    if zone_id:
        loan_requests = loan_requests.filter(branch__zone_id=zone_id)
    if branch_id:
        loan_requests = loan_requests.filter(branch_id=branch_id)
    if start_date and end_date:
        loan_requests = loan_requests.filter(date_requested__range=[start_date, end_date])
    if status:
        loan_requests = loan_requests.filter(status=status)

    # Pagination
    paginator = Paginator(loan_requests, 10)  # Show 10 loan requests per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'zones': Zone.objects.all(),
        'branches': Branch.objects.filter(zone=request.user.branch.zone),
    }
    return render(request, 'loans/view_loan_requests.html', context)


@login_required
@user_passes_test(lambda u: u.role == 'loan_officer')
def filter_loan_requests(request):
    loan_requests = LoanRequest.objects.filter(branch=request.user.branch)

    zone_id = request.GET.get('zone_id')
    branch_id = request.GET.get('branch_id')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if zone_id:
        loan_requests = loan_requests.filter(branch__zone_id=zone_id)
    if branch_id:
        loan_requests = loan_requests.filter(branch_id=branch_id)
    if start_date and end_date:
        loan_requests = loan_requests.filter(date_requested__range=[start_date, end_date])

    return render(request, 'loans/view_loan_requests.html', {'loan_requests': loan_requests})


@login_required
@user_passes_test(lambda u: u.role == 'operational_manager')
def view_loan_requests_operation_manager(request):
    loan_requests = LoanRequest.objects.all()  # Operation managers can see all requests

    # Filtering
    zone_id = request.GET.get('zone_id')
    branch_id = request.GET.get('branch_id')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    status = request.GET.get('status')

    if zone_id:
        loan_requests = loan_requests.filter(branch__zone_id=zone_id)
    if branch_id:
        loan_requests = loan_requests.filter(branch_id=branch_id)
    if start_date and end_date:
        loan_requests = loan_requests.filter(date_requested__range=[start_date, end_date])
    if status:
        loan_requests = loan_requests.filter(status=status)

    # Pagination
    paginator = Paginator(loan_requests, 10)  # Show 10 loan requests per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'zones': Zone.objects.all(),
        'branches': Branch.objects.all(),
    }
    return render(request, 'loans/view_loan_requests_operation_manager.html', context)

@login_required
@user_passes_test(lambda u: u.role == 'operational_manager')
def update_operation_manager_approval(request, loan_request_id):
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if request.method == 'POST':
        loan_request.operation_manager_approval = request.POST.get('operation_manager_approval') == 'True'
        loan_request.save()
        return redirect('view_loan_requests_operation_manager')
    return render(request, 'loans/update_operation_manager_approval.html', {'loan_request': loan_request})

# loans/views.py

@login_required
@user_passes_test(lambda u: u.role == 'finance')
def view_loan_requests_finance_manager(request):
    loan_requests = LoanRequest.objects.all()  # Finance managers can see all requests

    # Filtering
    zone_id = request.GET.get('zone_id')
    branch_id = request.GET.get('branch_id')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    status = request.GET.get('status')

    if zone_id:
        loan_requests = loan_requests.filter(branch__zone_id=zone_id)
    if branch_id:
        loan_requests = loan_requests.filter(branch_id=branch_id)
    if start_date and end_date:
        loan_requests = loan_requests.filter(date_requested__range=[start_date, end_date])
    if status:
        loan_requests = loan_requests.filter(status=status)

    # Pagination
    paginator = Paginator(loan_requests, 10)  # Show 10 loan requests per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'zones': Zone.objects.all(),
        'branches': Branch.objects.all(),
    }
    return render(request, 'loans/view_loan_requests_finance_manager.html', context)

@login_required
@user_passes_test(lambda u: u.role == 'finance')
def update_finance_manager_approval(request, loan_request_id):
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    if request.method == 'POST':
        loan_request.finance_approval = request.POST.get('finance_approval') == 'True'
        loan_request.save()
        return redirect('view_loan_requests_finance_manager')
    return render(request, 'loans/update_finance_manager_approval.html', {'loan_request': loan_request})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_zones(request):
    zones = Zone.objects.all()
    if request.method == 'POST':
        form = ZoneForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('manage_zones')
    else:
        form = ZoneForm()
    return render(request, 'loans/manage_zones.html', {'zones': zones, 'form': form})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def edit_zone(request, zone_id):
    zone = get_object_or_404(Zone, pk=zone_id)
    if request.method == 'POST':
        form = ZoneForm(request.POST, instance=zone)
        if form.is_valid():
            form.save()
            return redirect('manage_zones')
    else:
        form = ZoneForm(instance=zone)
    return render(request, 'loans/edit_zone.html', {'form': form, 'zone': zone})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_branches(request):
    branches = Branch.objects.select_related('zone').all()
    if request.method == 'POST':
        form = BranchForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('manage_branches')
    else:
        form = BranchForm()
    return render(request, 'loans/manage_branches.html', {'branches': branches, 'form': form})

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
    if request.method == 'POST':
        form = LoanCategoryForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('manage_loan_categories')
    else:
        form = LoanCategoryForm()
    return render(request, 'loans/manage_loan_categories.html', {'categories': categories, 'form': form})

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
    if request.method == 'POST':
        form = CollateralTypeForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('manage_collateral_types')
    else:
        form = CollateralTypeForm()
    return render(request, 'loans/manage_collateral_types.html', {'collateral_types': collateral_types, 'form': form})

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
def load_branches(request):
    zone_id = request.GET.get('zone_id')
    branches = Branch.objects.filter(zone_id=zone_id).all()
    return JsonResponse(list(branches.values('id', 'name')), safe=False)
