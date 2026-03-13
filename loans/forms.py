# loans/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import (
    CustomUser, LoanRequest, District, Branch, Region, Zone, City,
    LoanCategory, CollateralType, LoanApplicationDocumentType, LoanAppraisal, CollateralEstimationConfig,
)

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


class LoanApplicationDocumentTypeForm(forms.ModelForm):
    """Superadmin: add/edit document types required for loan application."""
    class Meta:
        model = LoanApplicationDocumentType
        fields = ['name', 'order', 'is_required']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'is_required': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class CollateralEstimationConfigForm(forms.ModelForm):
    """Superadmin: who does collateral estimation – loan officer or engineering team."""
    class Meta:
        model = CollateralEstimationConfig
        fields = ['mode']
        widgets = {
            'mode': forms.Select(attrs={'class': 'form-control'}),
        }

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


class LoanAppraisalForm(forms.ModelForm):
    class Meta:
        model = LoanAppraisal
        fields = [
            'monthly_business_income',
            'monthly_business_expenses',
            'other_monthly_income',
            'other_monthly_expenses',
            'proposed_monthly_installment',
            'net_monthly_cashflow',
            'dscr',
            'business_assessment',
            'character_assessment',
            'collateral_total_value',
            'recommendation',
            'recommendation_comment',
        ]
        widgets = {
            'monthly_business_income': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'monthly_business_expenses': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'other_monthly_income': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'other_monthly_expenses': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'proposed_monthly_installment': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'net_monthly_cashflow': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'dscr': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'business_assessment': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'character_assessment': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'collateral_total_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'recommendation': forms.Select(attrs={'class': 'form-control'}),
            'recommendation_comment': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def clean(self):
        from decimal import Decimal, InvalidOperation
        data = super().clean()
        inc1 = data.get('monthly_business_income') or Decimal('0')
        inc2 = data.get('other_monthly_income') or Decimal('0')
        exp1 = data.get('monthly_business_expenses') or Decimal('0')
        exp2 = data.get('other_monthly_expenses') or Decimal('0')
        net = inc1 + inc2 - exp1 - exp2
        data['net_monthly_cashflow'] = net
        installment = data.get('proposed_monthly_installment')
        if installment and installment > 0:
            try:
                data['dscr'] = (net / installment).quantize(Decimal('0.01'))
            except (InvalidOperation, ZeroDivisionError):
                data['dscr'] = None
        return data


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


class AssignEngineerForm(forms.Form):
    """Engineering head assigns an engineer to a loan sent for collateral estimation."""
    assigned_engineer = forms.ModelChoiceField(
        queryset=CustomUser.objects.none(),
        required=False,
        empty_label='— Unassigned —',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assigned_engineer'].queryset = CustomUser.objects.filter(
            role='engineer', is_active=True
        ).order_by('username')