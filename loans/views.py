# loans/views.py

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, authenticate
from .models import Zone, Branch, LoanCategory, CollateralType, LoanRequest, CustomUser
from .forms import CustomUserCreationForm, LoanRequestForm

@login_required
def home(request):
    return render(request, 'loans/home.html')

@login_required
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
