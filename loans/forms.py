# loans/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import CustomUser, LoanRequest, District, Branch, Region, Zone, City, LoanCategory, CollateralType

class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ['username', 'password1', 'password2', 'role', 'phone_number', 'district', 'branch']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['branch'].queryset = Branch.objects.none()

        if 'district' in self.data:
            try:
                district_id = int(self.data.get('district'))
                self.fields['branch'].queryset = Branch.objects.filter(district_id=district_id).order_by('name')
            except (ValueError, TypeError):
                pass
        elif self.instance.pk and self.instance.district:
            self.fields['branch'].queryset = self.instance.district.branch_set.order_by('name')

class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'role', 'phone_number', 'district', 'branch']


class DistrictForm(forms.ModelForm):
    class Meta:
        model = District
        fields = ['name']


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ['district', 'name']


class RegionForm(forms.ModelForm):
    class Meta:
        model = Region
        fields = ['name']


class ZoneForm(forms.ModelForm):
    class Meta:
        model = Zone
        fields = ['region', 'name']


class CityForm(forms.ModelForm):
    class Meta:
        model = City
        fields = ['zone', 'name']

class LoanCategoryForm(forms.ModelForm):
    class Meta:
        model = LoanCategory
        fields = ['name']

class CollateralTypeForm(forms.ModelForm):
    class Meta:
        model = CollateralType
        fields = ['name']

class LoanRequestForm(forms.ModelForm):
    class Meta:
        model = LoanRequest
        fields = [
            'applicant_name',
            'phone_number',
            'category',
            'collateral',
            'amount_requested',
            'reason',
            'customer_history',
        ]
        widgets = {
            'date_requested': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(LoanRequestForm, self).__init__(*args, **kwargs)


class AssignLoanOfficerForm(forms.Form):
    """Branch manager assigns a loan officer to a loan request (analysis and collateral)."""
    assigned_loan_officer = forms.ModelChoiceField(
        queryset=CustomUser.objects.none(),
        required=False,
        empty_label='— Unassigned —',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, branch=None, **kwargs):
        super().__init__(*args, **kwargs)
        if branch:
            self.fields['assigned_loan_officer'].queryset = CustomUser.objects.filter(
                role='loan_officer',
                branch=branch,
                is_active=True,
            ).order_by('username')