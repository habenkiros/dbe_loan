# loans/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Zone, Branch, LoanCategory, CollateralType, LoanRequest, CustomUser
from .forms import CustomUserCreationForm, LoanRequestForm, ZoneForm, BranchForm, LoanCategoryForm, CollateralTypeForm
from django.http import JsonResponse

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
            return redirect('home')
    else:
        form = CustomUserCreationForm()
    return render(request, 'loans/create_user.html', {'form': form})

@login_required
@user_passes_test(lambda u: u.role == 'loan_officer')
def create_loan_request(request):
    if request.method == 'POST':
        form = LoanRequestForm(request.POST)
        if form.is_valid():
            loan_request = form.save(commit=False)
            loan_request.branch = request.user.branch
            loan_request.save()
            return redirect('view_loan_requests')
    else:
        form = LoanRequestForm()
    return render(request, 'loans/create_loan_request.html', {'form': form})

@login_required
@user_passes_test(lambda u: u.role == 'loan_officer')
def view_loan_requests(request):
    loan_requests = LoanRequest.objects.filter(branch=request.user.branch)
    return render(request, 'loans/view_loan_requests.html', {'loan_requests': loan_requests})

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
def manage_users(request):
    users = CustomUser.objects.all()
    return render(request, 'loans/manage_users.html', {'users': users})

@login_required
def load_branches(request):
    zone_id = request.GET.get('zone_id')
    branches = Branch.objects.filter(zone_id=zone_id).all()
    return JsonResponse(list(branches.values('id', 'name')), safe=False)
