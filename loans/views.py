# loans/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Zone, Branch, LoanCategory, CollateralType, LoanRequest, CustomUser, LatestLoanRequestID
from .forms import CustomUserCreationForm, CustomUserChangeForm, LoanRequestForm, ZoneForm, BranchForm, LoanCategoryForm, CollateralTypeForm
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
import csv
from django.core.files.storage import FileSystemStorage
from django.contrib import messages
import pandas as pd

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

    # --- Search and filter handling ---
    query = request.GET.get("q")
    role = request.GET.get("role")

    if query:
        users = users.filter(
            Q(username__icontains=query) |
            Q(email__icontains=query) |
            Q(phone_number__icontains=query)
        )

    if role:
        users = users.filter(role=role)

    # Pagination
    paginator = Paginator(users, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "roles": CustomUser.USER_ROLES,
        "query": query or "",
        "selected_role": role or "",
    }
    return render(request, "loans/manage_users.html", context)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def edit_user(request, user_id):
    user = get_object_or_404(CustomUser, pk=user_id)
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
            loan_request.zone = request.user.zone
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
    return f"D-{latest_id:015d}"

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
    return render(request, 'loans/loan_request_detail_finance.html', {'loan_request': loan_request})
#manager
@login_required
@user_passes_test(lambda u: u.role in ['manager'])
def loan_request_detail_manager(request, loan_request_id):
    loan_request = get_object_or_404(LoanRequest, pk=loan_request_id)
    return render(request, 'loans/loan_request_detail_manager.html', {'loan_request': loan_request})

@login_required
@user_passes_test(lambda u: u.role == 'loan_officer')
def view_loan_requests(request):
    loan_requests = LoanRequest.objects.filter(branch=request.user.branch)
    
    # Filtering
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    status = request.GET.get('status')

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

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if start_date and end_date:
        loan_requests = loan_requests.filter(date_requested__range=[start_date, end_date])

    return render(request, 'loans/view_loan_requests.html', {'loan_requests': loan_requests})

@login_required
# @user_passes_test(lambda u: u.role in ['loan_officer', 'operational_manager', 'finance', 'manager'])
def load_branches_op(request):
    zone_id = request.GET.get('zone')
    user = request.user

    # Ensure that only branches within the user's zone are fetched
    branches = Branch.objects.filter(zone_id=zone_id, zone=user.zone) if zone_id else Branch.objects.none()

    branch_list = [{"id": branch.id, "name": branch.name} for branch in branches]
    
    return JsonResponse(branch_list, safe=False)

@login_required
@user_passes_test(lambda u: u.role == 'operational_manager')
def view_loan_requests_operation_manager(request):
    user = request.user  # Fetch the logged-in user
    zone_id = request.GET.get('zone')
    branch_id = request.GET.get('branch')
    date_requested = request.GET.get('date_requested')
    loan_request_id = request.GET.get('loan_request_id')
    status = request.GET.get('status')

    # Start with all loan requests for the operational manager's zone
    loan_requests = LoanRequest.objects.all()

    # Filter by zone if selected (should match the manager's zone)
    if zone_id:
        loan_requests = loan_requests.filter(zone_id=zone_id)
    if branch_id:
        loan_requests = loan_requests.filter(branch_id=branch_id)
    if date_requested:
        loan_requests = loan_requests.filter(date_requested__date=date_requested)
    if loan_request_id:
        loan_requests = loan_requests.filter(loan_request_id__icontains=loan_request_id)
    if status:
        loan_requests = loan_requests.filter(status=status)
    # Pagination
    paginator = Paginator(loan_requests, 10)  # Show 10 loan requests per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Fetch zones and branches for the filters
    zones = Zone.objects.all()
    branches = Branch.objects.filter(zone_id=zone_id) if zone_id else Branch.objects.none()

    context = {
        'page_obj': page_obj,
        'loan_requests': loan_requests,
        'zones': zones,
        'branches': branches,
        'selected_zone': zone_id,
        'selected_branch': branch_id,
        'selected_date_requested': date_requested,
        'selected_loan_request_id': loan_request_id,
        'selected_status': status,
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

@login_required
@user_passes_test(lambda u: u.role == 'finance')
def view_loan_requests_finance_manager(request):
    user = request.user
    zone_id = request.GET.get('zone')
    branch_id = request.GET.get('branch')
    date_requested = request.GET.get('date_requested')
    loan_request_id = request.GET.get('loan_request_id')
    status = request.GET.get('status')

    # Start with all loan requests
    loan_requests = LoanRequest.objects.all()

    # Apply filters independently
    if zone_id:
        loan_requests = loan_requests.filter(zone_id=zone_id)
    if branch_id:
        loan_requests = loan_requests.filter(branch_id=branch_id)
    if date_requested:
        loan_requests = loan_requests.filter(date_requested__date=date_requested)
    if loan_request_id:
        loan_requests = loan_requests.filter(loan_request_id__icontains=loan_request_id)
    if status:
        loan_requests = loan_requests.filter(status=status)

    # Pagination
    paginator = Paginator(loan_requests, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    zones = Zone.objects.all()
    branches = Branch.objects.filter(zone_id=zone_id) if zone_id else Branch.objects.none()

    context = {
        'page_obj': page_obj,
        'loan_requests': loan_requests,
        'zones': zones,
        'branches': branches,
        'selected_zone': zone_id,
        'selected_branch': branch_id,
        'selected_date_requested': date_requested,
        'selected_loan_request_id': loan_request_id,
        'selected_status': status,
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
@user_passes_test(lambda u: u.role == 'manager')
def view_loan_requests_manager(request):
    user = request.user
    zone_id = request.GET.get('zone')
    branch_id = request.GET.get('branch')
    date_requested = request.GET.get('date_requested')
    loan_request_id = request.GET.get('loan_request_id')
    status = request.GET.get('status')

    # Start with all loan requests
    loan_requests = LoanRequest.objects.all()

    # Apply filters independently
    if zone_id:
        loan_requests = loan_requests.filter(zone_id=zone_id)
    if branch_id:
        loan_requests = loan_requests.filter(branch_id=branch_id)
    if date_requested:
        loan_requests = loan_requests.filter(date_requested__date=date_requested)
    if loan_request_id:
        loan_requests = loan_requests.filter(loan_request_id__icontains=loan_request_id)
    if status:
        loan_requests = loan_requests.filter(status=status)

    # Pagination
    paginator = Paginator(loan_requests, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    zones = Zone.objects.all()
    branches = Branch.objects.filter(zone_id=zone_id) if zone_id else Branch.objects.none()

    context = {
        'page_obj': page_obj,
        'loan_requests': loan_requests,
        'zones': zones,
        'branches': branches,
        'selected_zone': zone_id,
        'selected_branch': branch_id,
        'selected_date_requested': date_requested,
        'selected_loan_request_id': loan_request_id,
        'selected_status': status,
    }
    return render(request, 'loans/view_loan_requests_manager.html', context)

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
    
    paginator = Paginator(branches, 10)  # Show 10 branches per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    if request.method == 'POST':
        form = BranchForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('manage_branches')
    else:
        form = BranchForm()

    context = {
        'form': form,
        'page_obj': page_obj
    }
    return render(request, 'loans/manage_branches.html', context)


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
    
    paginator = Paginator(categories, 10)  # Show 10 branches per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    if request.method == 'POST':
        form = LoanCategoryForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('manage_loan_categories')
    else:
        form = LoanCategoryForm()
        
    context = {
        'form': form,
        'page_obj': page_obj
    }   
    return render(request, 'loans/manage_loan_categories.html', context)

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
    
    paginator = Paginator(collateral_types, 10)  # Show 10 branches per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    if request.method == 'POST':
        form = CollateralTypeForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('manage_collateral_types')
    else:
        form = CollateralTypeForm()
        
    context = {
        'form': form,
        'page_obj': page_obj
    }  
    return render(request, 'loans/manage_collateral_types.html', context)

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

@login_required
@user_passes_test(lambda u: u.role in ['loan_officer', 'operational_manager', 'finance', 'manager'])
def view_report(request):
    status = request.GET.get('status')
    role = request.user.role
    branch = request.user.branch if role == 'loan_officer' else None

    loan_requests = LoanRequest.objects.all()
    
    if branch:
        loan_requests = loan_requests.filter(branch=branch)
    
    if status:
        loan_requests = loan_requests.filter(status=status)

    paginator = Paginator(loan_requests, 10)  # Show 10 loan requests per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'status': status,
        'zones': Zone.objects.all(),
        'branches': Branch.objects.all(),
    }
    return render(request, 'loans/view_report.html', context)

@login_required
@user_passes_test(lambda u: u.role in ['loan_officer', 'operational_manager', 'finance', 'manager'])
def generate_report(request):
    status = request.GET.get('status')
    role = request.user.role
    branch = request.user.branch if role == 'loan_officer' else None

    loan_requests = LoanRequest.objects.all()
    
    if branch:
        loan_requests = loan_requests.filter(branch=branch)
    
    if status:
        loan_requests = loan_requests.filter(status=status)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{status}_loan_requests.csv"'

    writer = csv.writer(response)
    writer.writerow(['ID', 'Applicant Name', 'Amount Requested', 'Status', 'Date Requested', 'Date Reviewed'])

    for loan_request in loan_requests:
        writer.writerow([
            loan_request.loan_request_id,
            loan_request.applicant_name,
            loan_request.amount_requested,
            loan_request.status,
            loan_request.date_requested,
            loan_request.date_reviewed
        ])

    return response

@login_required
@user_passes_test(lambda u: u.role in ['loan_officer', 'operational_manager', 'finance', 'manager'])
def view_report_options(request):
    return render(request, 'loans/view_report_options.html')

# @login_required
# @user_passes_test(lambda u: u.is_superuser)
def upload_zones(request):
    if request.method == 'POST' and request.FILES['file']:
        file = request.FILES['file']
        fs = FileSystemStorage(location='backup/')
        filename = fs.save(file.name, file)
        file_path = fs.path(filename)

        data = pd.read_excel(file_path, engine='openpyxl')
        for index, row in data.iterrows():
            zone, created = Zone.objects.get_or_create(name=row['name'])
            if created:
                messages.success(request, f'Successfully created zone: {zone.name}')
            else:
                messages.warning(request, f'Zone already exists: {zone.name}')

        return redirect('upload_zones')

    return render(request, 'backup/upload_zones.html')


def upload_branches(request):
    if request.method == 'POST' and request.FILES['file']:
        file = request.FILES['file']
        fs = FileSystemStorage(location='backup/')
        filename = fs.save(file.name, file)
        file_path = fs.path(filename)

        data = pd.read_excel(file_path, engine='openpyxl')
        for index, row in data.iterrows():
            zone_name = row['zone']
            branch_name = row['name']

            try:
                zone = Zone.objects.get(name=zone_name)
                branch, created = Branch.objects.get_or_create(name=branch_name, zone=zone)
                if created:
                    messages.success(request, f'Successfully created branch: {branch.name} in zone: {zone.name}')
                else:
                    messages.warning(request, f'Branch already exists: {branch.name} in zone: {zone.name}')
            except Zone.DoesNotExist:
                messages.error(request, f'Zone does not exist: {zone_name}')

        return redirect('upload_branches')

    return render(request, 'backup/upload_branches.html')

def upload_loan_categories(request):
    if request.method == 'POST' and request.FILES['file']:
        file = request.FILES['file']
        fs = FileSystemStorage(location='backup/')
        filename = fs.save(file.name, file)
        file_path = fs.path(filename)

        data = pd.read_excel(file_path, engine='openpyxl')
        for index, row in data.iterrows():
            category_name = row['name']

            loan_category, created = LoanCategory.objects.get_or_create(name=category_name)
            if created:
                messages.success(request, f'Successfully created loan category: {loan_category.name}')
            else:
                messages.warning(request, f'Loan category already exists: {loan_category.name}')

        return redirect('upload_loan_categories')

    return render(request, 'backup/upload_loan_categories.html')

def upload_users(request):
    if request.method == 'POST' and request.FILES['file']:
        file = request.FILES['file']
        fs = FileSystemStorage(location='backup/')
        filename = fs.save(file.name, file)
        file_path = fs.path(filename)

        data = pd.read_excel(file_path, engine='openpyxl')
        for index, row in data.iterrows():
            username = row['username']
            email = row['email']
            phone_number = row['phone_number']
            role = row['role']
            zone = row['zone']
            branch = row['branch']

            try:
                zone = Zone.objects.get(name=zone)
                branch = Branch.objects.get(name=branch, zone=zone)
                user, created = CustomUser.objects.get_or_create(
                    username=username,
                    defaults={
                        'email': email,
                        'phone_number': phone_number,
                        'role': role,
                        'zone': zone,
                        'branch': branch
                    }
                )
                if created:
                    user.set_password('Zemeo@zemeo10')  # You may want to set a default password or handle password securely
                    user.save()
                    messages.success(request, f'Successfully created user: {username}')
                else:
                    messages.warning(request, f'User already exists: {username}')
            except Zone.DoesNotExist:
                messages.error(request, f'Zone does not exist: {zone}')
            except Branch.DoesNotExist:
                messages.error(request, f'Branch does not exist: {branch}')

        return redirect('upload_users')

    return render(request, 'backup/upload_users.html')

def upload_loan_requests(request):
    if request.method == 'POST' and request.FILES['file']:
        file = request.FILES['file']
        fs = FileSystemStorage(location='backup/')
        filename = fs.save(file.name, file)
        file_path = fs.path(filename)

        data = pd.read_excel(file_path, engine='openpyxl')
        for index, row in data.iterrows():
            try:
                applicant_name = row['applicant_name']
                email = row['email']
                phone_number = row['phone_number']
                category = LoanCategory.objects.get(name=row['category'])
                collateral = CollateralType.objects.get(name=row['collateral'])
                amount_requested = row['amount_requested']
                reason = row['reason']
                status = str(row['status']).strip().lower()  # normalize
                zone = Zone.objects.get(name=row['zone'])
                branch = Branch.objects.get(name=row['branch'], zone=zone)
                customer_history = row['customer_history']
                date_requested = row['date_requested']

                # Default approvals
                operation_manager_approval = False
                finance_approval = False

                # If Excel says "Approved", mark both approvals True
                if status == "approved":
                    operation_manager_approval = True
                    finance_approval = True

                LoanRequest.objects.create(
                    loan_request_id=generate_incremental_loan_request_id(),
                    applicant_name=applicant_name,
                    email=email,
                    phone_number=phone_number,
                    category=category,
                    collateral=collateral,
                    amount_requested=amount_requested,
                    reason=reason,
                    status=status.capitalize(),   # keep proper case
                    zone=zone,
                    branch=branch,
                    customer_history=customer_history,
                    date_requested=date_requested,
                    operation_manager_approval=operation_manager_approval,
                    finance_approval=finance_approval
                )

                messages.success(request, f'Successfully imported loan request for: {applicant_name}')

            except LoanCategory.DoesNotExist:
                messages.error(request, f'Loan category does not exist: {category}')
            except CollateralType.DoesNotExist:
                messages.error(request, f'Collateral does not exist: {collateral}')
            except Branch.DoesNotExist:
                messages.error(request, f'Branch does not exist: {branch}')

        return redirect('upload_loan_requests')

    return render(request, 'backup/upload_loan_requests.html')


def upload_collaterals(request):
    if request.method == 'POST' and request.FILES['file']:
        file = request.FILES['file']
        fs = FileSystemStorage(location='backup/')
        filename = fs.save(file.name, file)
        file_path = fs.path(filename)

        data = pd.read_excel(file_path, engine='openpyxl')
        for index, row in data.iterrows():
            collateral_name = row['collateral']

            collateral, created = CollateralType.objects.get_or_create(name=collateral_name)
            if created:
                messages.success(request, f'Successfully created collateral: {collateral}')
            else:
                messages.warning(request, f'Collateral already exists: {collateral}')

        return redirect('upload_collaterals')

    return render(request, 'backup/upload_collaterals.html')

@login_required
def load_branches(request):
    zone_id = request.GET.get('zone')
    branches = Branch.objects.filter(zone_id=zone_id).order_by('name')
    return JsonResponse(list(branches.values('id', 'name')), safe=False)