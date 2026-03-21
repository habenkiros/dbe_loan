# loans/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import (
    CustomUser, LoanRequest, District, Branch, Region, Zone, City,
    LoanCategory, CollateralType, LoanApplicationDocumentType, LoanAppraisal, CollateralEstimationConfig,
    LoanRequestBasicInfo, AppraisalCreditHistoryEntry, AppraisalQualitativeFactor,
    QUALITATIVE_FACTOR_KEYS, QUALITATIVE_RATING_CHOICES,
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


class LoanRequestBasicInfoForm(forms.ModelForm):
    """Sheet (1) Basic Info and loan request – client, business, loan details."""
    class Meta:
        model = LoanRequestBasicInfo
        fields = [
            'tin_number', 'gender', 'age', 'marital_status', 'education_level', 'home_address',
            'spouse_name', 'spouse_occupation', 'father_name', 'grandfather_name',
            'business_name', 'business_description', 'business_address', 'date_business_started',
            'form_of_ownership', 'economic_sector', 'subsector_activity',
            'employees_full_time', 'employees_part_time', 'employees_seasonal',
            'employees_ft_equivalent', 'family_members_employed',
            'peak_sales_months', 'lowest_sales_months', 'number_business_owners',
            'term_months', 'repayment_frequency', 'interest_rate', 'interest_basis',
            'grace_period_months', 'interest_only_months', 'instalments_per_year', 'cash_contribution',
        ]
        widgets = {
            'date_business_started': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'home_address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'business_description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'business_address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.fields:
            if self.fields[name].widget.attrs.get('class') != 'form-control':
                self.fields[name].widget.attrs.setdefault('class', 'form-control')


class AppraisalCreditHistoryEntryForm(forms.ModelForm):
    """One row of credit history (Sheet 2). Dropdowns per Excel: Status, Purpose, Repayment, Letter from lender."""
    class Meta:
        model = AppraisalCreditHistoryEntry
        fields = [
            'lender', 'loan_amount', 'current_balance', 'maturity_date', 'purpose',
            'status', 'repayment', 'letter_from_lender', 'score',
        ]
        widgets = {
            'maturity_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'purpose': forms.Select(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'repayment': forms.Select(attrs={'class': 'form-control'}),
            'letter_from_lender': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.fields:
            self.fields[name].widget.attrs.setdefault('class', 'form-control')
        for name in ('purpose', 'status', 'repayment', 'letter_from_lender'):
            self.fields[name].required = False
            self.fields[name].empty_label = '—'


class AppraisalQualitativeFactorForm(forms.ModelForm):
    """One qualitative factor (Sheet 2) – rating (dropdown: Poor/basic/Professional) and notes."""
    class Meta:
        model = AppraisalQualitativeFactor
        fields = ['factor_key', 'factor_name', 'rating', 'notes', 'display_order']
        widgets = {
            'rating': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['factor_key'].widget = forms.HiddenInput()
        self.fields['factor_name'].widget.attrs['readonly'] = True
        self.fields['factor_name'].widget.attrs['class'] = 'form-control'
        self.fields['display_order'].widget = forms.HiddenInput()
        self.fields['rating'].choices = QUALITATIVE_RATING_CHOICES
        self.fields['rating'].required = False


def get_credit_history_formset():
    from django.forms import inlineformset_factory
    return inlineformset_factory(
        LoanAppraisal,
        AppraisalCreditHistoryEntry,
        form=AppraisalCreditHistoryEntryForm,
        extra=1,
        can_delete=True,
    )


def get_qualitative_factors_formset():
    from django.forms import inlineformset_factory
    return inlineformset_factory(
        LoanAppraisal,
        AppraisalQualitativeFactor,
        form=AppraisalQualitativeFactorForm,
        extra=0,
        can_delete=False,
        max_num=10,
    )


# Step-based appraisal: one form per sheet so saving a step doesn't overwrite others.
class AppraisalSheet2Form(forms.ModelForm):
    """Sheet (2) Business & character – NBE, credit history summary, qualitative score, assessments."""
    class Meta:
        model = LoanAppraisal
        fields = [
            'nbe_credit_report_obtained', 'nbe_report_date_received', 'total_number_repaid_loans',
            'credit_history_max_score', 'qualitative_total_score', 'qualitative_passed',
            'business_assessment', 'character_assessment',
        ]
        widgets = {
            'nbe_report_date_received': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'business_assessment': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'character_assessment': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.fields:
            if name not in ('nbe_credit_report_obtained', 'qualitative_passed'):
                self.fields[name].widget.attrs.setdefault('class', 'form-control')
        self.fields['nbe_credit_report_obtained'].widget.attrs['class'] = 'form-check-input'
        self.fields['qualitative_passed'].widget.attrs['class'] = 'form-check-input'


class AppraisalSheet3Form(forms.ModelForm):
    """Sheet (3) Cashflow analysis."""
    class Meta:
        model = LoanAppraisal
        fields = [
            'monthly_business_income', 'monthly_business_expenses', 'other_monthly_income', 'other_monthly_expenses',
            'proposed_monthly_installment', 'net_monthly_cashflow', 'dscr',
        ]
        widgets = {
            'monthly_business_income': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'monthly_business_expenses': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'other_monthly_income': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'other_monthly_expenses': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'proposed_monthly_installment': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'net_monthly_cashflow': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'dscr': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.fields:
            self.fields[name].widget.attrs.setdefault('class', 'form-control')

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


class AppraisalESForm(forms.ModelForm):
    """Sheet (4) E&S Assessment."""
    class Meta:
        model = LoanAppraisal
        fields = [
            'es_risk_category', 'es_eligibility_decision',
            'es_screened_by', 'es_checked_by', 'es_approved_by',
            'es_assessment_date', 'es_notes',
        ]
        widgets = {
            'es_assessment_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'es_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import CustomUser
        qs = CustomUser.objects.filter(is_active=True).order_by('username')
        for f in ('es_screened_by', 'es_checked_by', 'es_approved_by'):
            self.fields[f].queryset = qs
        for name in self.fields:
            self.fields[name].widget.attrs.setdefault('class', 'form-control')


class AppraisalCollateralForm(forms.ModelForm):
    """Sheet (5) Collateral worksheet – breakdown and total, coverage ratio."""
    class Meta:
        model = LoanAppraisal
        fields = [
            'collateral_immovable_value', 'collateral_moveable_value',
            'collateral_intangible_value', 'collateral_guarantors_value',
            'collateral_total_value', 'collateral_coverage_ratio',
        ]
        widgets = {
            'collateral_immovable_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'collateral_moveable_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'collateral_intangible_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'collateral_guarantors_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'collateral_total_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'collateral_coverage_ratio': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.fields:
            self.fields[name].widget.attrs.setdefault('class', 'form-control')

    def clean(self):
        from decimal import Decimal
        data = super().clean()
        imm = data.get('collateral_immovable_value') or Decimal('0')
        mov = data.get('collateral_moveable_value') or Decimal('0')
        intan = data.get('collateral_intangible_value') or Decimal('0')
        guar = data.get('collateral_guarantors_value') or Decimal('0')
        total_comp = imm + mov + intan + guar
        if total_comp > 0 and not data.get('collateral_total_value'):
            data['collateral_total_value'] = total_comp
        return data


class AppraisalSummaryForm(forms.ModelForm):
    """Sheet (6) Summary & decision – recommendation, strengths/weaknesses, committee."""
    class Meta:
        model = LoanAppraisal
        fields = [
            'recommendation', 'recommendation_comment',
            'strengths', 'weaknesses', 'committee_comments',
            'amount_approved', 'term_approved_months', 'rate_approved',
        ]
        widgets = {
            'recommendation': forms.Select(attrs={'class': 'form-control'}),
            'recommendation_comment': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'strengths': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'weaknesses': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'committee_comments': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'amount_approved': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'term_approved_months': forms.NumberInput(attrs={'class': 'form-control'}),
            'rate_approved': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.fields:
            self.fields[name].widget.attrs.setdefault('class', 'form-control')


class LoanAppraisalForm(forms.ModelForm):
    """Full appraisal form (single-page fallback): Sheet 2 + cashflow + collateral + decision."""
    class Meta:
        model = LoanAppraisal
        fields = [
            'nbe_credit_report_obtained', 'nbe_report_date_received', 'total_number_repaid_loans',
            'credit_history_max_score', 'qualitative_total_score', 'qualitative_passed',
            'business_assessment', 'character_assessment',
            'monthly_business_income', 'monthly_business_expenses', 'other_monthly_income', 'other_monthly_expenses',
            'proposed_monthly_installment', 'net_monthly_cashflow', 'dscr',
            'collateral_total_value', 'recommendation', 'recommendation_comment',
        ]
        widgets = {
            'nbe_report_date_received': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.fields:
            if name != 'nbe_credit_report_obtained' and name != 'qualitative_passed':
                self.fields[name].widget.attrs.setdefault('class', 'form-control')
        self.fields['nbe_credit_report_obtained'].widget.attrs['class'] = 'form-check-input'
        self.fields['qualitative_passed'].widget.attrs['class'] = 'form-check-input'

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