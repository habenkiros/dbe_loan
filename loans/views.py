# loans/views.py

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import login, authenticate
from .models import Zone, Branch, LoanCategory, CollateralType, LoanRequest, CustomUser
from .forms import CustomUserCreationForm, LoanRequestForm
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
def create_loan_request(request):
    if request.method == 'POST':
        form = LoanRequestForm(request.POST)
        if form.is_valid():
            loan_request = form.save(commit=False)
            loan_request.branch = request.user.branch
            loan_request.save()
            return redirect('home')
    else:
        form = LoanRequestForm()
    return render(request, 'loans/create_loan_request.html', {'form': form})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_zones(request):
    zones = Zone.objects.all()
    return render(request, 'loans/manage_zones.html', {'zones': zones})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_branches(request):
    branches = Branch.objects.select_related('zone').all()
    return render(request, 'loans/manage_branches.html', {'branches': branches})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_loan_categories(request):
    categories = LoanCategory.objects.all()
    return render(request, 'loans/manage_loan_categories.html', {'categories': categories})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_collateral_types(request):
    collateral_types = CollateralType.objects.all()
    return render(request, 'loans/manage_collateral_types.html', {'collateral_types': collateral_types})

@login_required
def load_branches(request):
    zone_id = request.GET.get('zone_id')
    branches = Branch.objects.filter(zone_id=zone_id).all()
    return JsonResponse(list(branches.values('id', 'name')), safe=False)
