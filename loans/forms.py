# loans/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import (
    CustomUser, LoanRequest, District, Branch, Region, Zone, City,
    LoanCategory, CollateralType, LoanApplicationDocumentType, LoanAppraisal, CollateralEstimationConfig,
    LoanRequestBasicInfo, AppraisalCreditHistoryEntry, AppraisalQualitativeFactor,
    AppraisalRiskMitigation, AppraisalCondition,
    AppraisalESChecklistItem,
    QUALITATIVE_FACTOR_KEYS, qualitative_rating_field_choices,
    es_checklist_item_count,
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
    """Superadmin: document type + per-type authentication rules."""
    class Meta:
        model = LoanApplicationDocumentType
        fields = [
            'name', 'order', 'is_required',
            'allowed_extensions', 'max_file_size_mb', 'auth_notes',
            'content_validation_sample', 'content_validation_min_matches',
            'content_validation_strict', 'content_extraction_mappings',
            'require_officer_verification', 'enable_ocr_match',
            'identity_match_fields', 'identity_match_strict',
            'enable_llm_check', 'enable_external_id',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'is_required': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allowed_extensions': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': 'pdf,jpg,jpeg,png (blank = bank default)'},
            ),
            'max_file_size_mb': forms.NumberInput(
                attrs={'class': 'form-control', 'min': 1, 'placeholder': 'Bank default'},
            ),
            'auth_notes': forms.TextInput(attrs={'class': 'form-control'}),
            'content_validation_sample': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 6,
                    'placeholder': 'One expected phrase per line, e.g.\nFEDERAL DEMOCRATIC REPUBLIC OF ETHIOPIA\nIDENTITY CARD\nTrade License',
                },
            ),
            'content_validation_min_matches': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'content_validation_strict': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'content_extraction_mappings': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 5,
                    'placeholder': 'tin_number=TIN\nbusiness_name=Business Name\nfather_name=Father Name\ntin_number=regex:\\b(\\d{10})\\b',
                },
            ),
            'require_officer_verification': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enable_ocr_match': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'identity_match_fields': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'applicant_name,phone_number,tin_number,business_name',
                },
            ),
            'identity_match_strict': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enable_llm_check': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enable_external_id': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'allowed_extensions': 'Only these extensions accepted for this document type.',
            'max_file_size_mb': 'Leave empty to use the bank-wide default below.',
            'content_validation_sample': (
                'Paste phrases that must appear in a valid upload (one per line). '
                'The system reads PDF/image/DOCX text and rejects wrong documents.'
            ),
            'content_validation_min_matches': 'How many of the phrases above must be found in the file.',
            'content_validation_strict': 'Reject upload immediately when content validation fails.',
            'content_extraction_mappings': (
                'Map document labels to appraisal fields for auto-fill (Sheet 1 / 2). '
                'One per line: field_name=Label in document.'
            ),
            'identity_match_fields': (
                'Comma-separated loan fields to find in the document via OCR: '
                'applicant_name, phone_number, tin_number, business_name.'
            ),
            'identity_match_strict': (
                'Reject upload when configured identity fields do not match loan data. '
                'Leave unchecked to accept upload but flag for officer review.'
            ),
        }

    def clean(self):
        cleaned = super().clean()
        phrases = []
        sample = cleaned.get('content_validation_sample') or ''
        for line in sample.splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                phrases.append(line)
        min_matches = cleaned.get('content_validation_min_matches') or 1
        if phrases and min_matches > len(phrases):
            raise forms.ValidationError(
                f'Minimum matches ({min_matches}) cannot exceed number of phrases ({len(phrases)}).'
            )
        return cleaned


class LoanApplicationDocumentTypeEditForm(LoanApplicationDocumentTypeForm):
    """Edit form includes official reference sample file upload."""

    class Meta(LoanApplicationDocumentTypeForm.Meta):
        fields = LoanApplicationDocumentTypeForm.Meta.fields + [
            'reference_sample',
            'use_reference_sample_validation',
            'reference_min_similarity',
        ]
        widgets = {
            **LoanApplicationDocumentTypeForm.Meta.widgets,
            'reference_sample': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.pdf,.jpg,.jpeg,.png'}),
            'use_reference_sample_validation': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'reference_min_similarity': forms.NumberInput(
                attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'max': '1'},
            ),
        }
        help_texts = {
            **LoanApplicationDocumentTypeForm.Meta.help_texts,
            'reference_sample': 'Upload the official blank/sample document (PDF or image). Save to analyze and seed validation rules.',
            'use_reference_sample_validation': 'Reject uploads that do not match the reference sample text/layout.',
            'reference_min_similarity': '0.08 is lenient for phone scans; increase to 0.15+ for stricter matching.',
        }


class DocumentAuthenticationDefaultsForm(forms.Form):
    """Bank-wide defaults when a document type leaves size/extensions blank."""

    def __init__(self, *args, **kwargs):
        from .models import DocumentAuthenticationPolicy
        self.policy = DocumentAuthenticationPolicy.objects.first()
        if not self.policy:
            self.policy = DocumentAuthenticationPolicy()
        super().__init__(*args, **kwargs)
        self.fields['allowed_extensions'] = forms.CharField(
            required=True,
            initial=self.policy.allowed_extensions,
            widget=forms.TextInput(attrs={'class': 'form-control'}),
            help_text='Used when a document type does not set its own allowed extensions.',
        )
        self.fields['max_file_size_mb'] = forms.IntegerField(
            min_value=1,
            initial=self.policy.max_file_size_mb,
            widget=forms.NumberInput(attrs={'class': 'form-control'}),
            help_text='Used when a document type does not set its own max size.',
        )
        self.fields['require_verified_documents_for_collateral'] = forms.BooleanField(
            required=False,
            initial=self.policy.require_verified_documents_for_collateral,
            widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            help_text='Required document types must pass authentication before collateral.',
        )

    def save(self):
        from .models import DocumentAuthenticationPolicy
        if not self.policy.pk:
            self.policy = DocumentAuthenticationPolicy.objects.create(
                allowed_extensions=self.cleaned_data['allowed_extensions'],
                max_file_size_mb=self.cleaned_data['max_file_size_mb'],
                require_verified_documents_for_collateral=self.cleaned_data['require_verified_documents_for_collateral'],
            )
        else:
            self.policy.allowed_extensions = self.cleaned_data['allowed_extensions']
            self.policy.max_file_size_mb = self.cleaned_data['max_file_size_mb']
            self.policy.require_verified_documents_for_collateral = self.cleaned_data['require_verified_documents_for_collateral']
            self.policy.save()
        return self.policy


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
    """One qualitative factor (Sheet 2) – rating dropdown per Excel (options vary by factor_key)."""
    class Meta:
        model = AppraisalQualitativeFactor
        fields = [
            'factor_key', 'factor_name',
            'rating', 'weight', 'earned_score',
            'notes', 'display_order',
        ]
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
        self.fields['rating'].required = False
        # Computed by Excel mapping; show as readonly in UI.
        self.fields['weight'].disabled = True
        self.fields['earned_score'].disabled = True

        factor_key = ''
        if getattr(self.instance, 'pk', None) and self.instance.factor_key:
            factor_key = self.instance.factor_key
        elif self.initial.get('factor_key'):
            factor_key = self.initial['factor_key']

        choices = qualitative_rating_field_choices(factor_key)
        current = getattr(self.instance, 'rating', None) or self.initial.get('rating') or ''
        if current and not any(current == c[0] for c in choices):
            choices = list(choices) + [(current, current)]
        self.fields['rating'].choices = choices


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


class AppraisalESChecklistItemForm(forms.ModelForm):
    """One E&S checklist row (Sheet 4) – Yes/No/N/A, description, mitigation."""

    class Meta:
        model = AppraisalESChecklistItem
        fields = [
            'section_key', 'section_label', 'item_key', 'question_text',
            'response_yes_no', 'description', 'mitigation', 'display_order',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'mitigation': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('section_key', 'section_label', 'item_key', 'question_text', 'display_order'):
            self.fields[name].widget = forms.HiddenInput()
        self.fields['response_yes_no'].required = False
        self.fields['response_yes_no'].widget.attrs.setdefault('class', 'form-control')


def get_es_checklist_formset():
    from django.forms import inlineformset_factory
    n = es_checklist_item_count()
    return inlineformset_factory(
        LoanAppraisal,
        AppraisalESChecklistItem,
        form=AppraisalESChecklistItemForm,
        extra=0,
        can_delete=False,
        max_num=n,
    )


class AppraisalRiskMitigationForm(forms.ModelForm):
    class Meta:
        model = AppraisalRiskMitigation
        fields = [
            'risk', 'severity', 'mitigation', 'owner', 'due_date', 'status', 'display_order',
        ]
        widgets = {
            'mitigation': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.fields:
            self.fields[name].widget.attrs.setdefault('class', 'form-control')


def get_risk_mitigation_formset():
    from django.forms import inlineformset_factory
    return inlineformset_factory(
        LoanAppraisal,
        AppraisalRiskMitigation,
        form=AppraisalRiskMitigationForm,
        extra=3,
        can_delete=True,
    )


class AppraisalConditionForm(forms.ModelForm):
    class Meta:
        model = AppraisalCondition
        fields = [
            'condition_type', 'description', 'responsible_party', 'due_date', 'fulfilled', 'display_order',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.fields:
            if name != 'fulfilled':
                self.fields[name].widget.attrs.setdefault('class', 'form-control')
        self.fields['fulfilled'].widget.attrs.setdefault('class', 'form-check-input')


def get_conditions_formset():
    from django.forms import inlineformset_factory
    return inlineformset_factory(
        LoanAppraisal,
        AppraisalCondition,
        form=AppraisalConditionForm,
        extra=3,
        can_delete=True,
    )


# Step-based appraisal: one form per sheet so saving a step doesn't overwrite others.
class AppraisalSheet2Form(forms.ModelForm):
    """Sheet (2) Business & character – NBE, credit history summary, qualitative score, assessments."""
    class Meta:
        model = LoanAppraisal
        fields = [
            'nbe_credit_report_obtained', 'nbe_report_date_received', 'total_number_repaid_loans',
            'credit_history_max_score', 'qualitative_total_score', 'qualitative_passed',
            'bureau_score', 'bureau_score_band', 'bureau_report_date',
            'bureau_active_loans_count', 'bureau_total_outstanding', 'bureau_total_monthly_debt_service',
            'bureau_inquiries_6m', 'bureau_defaults_ever', 'bureau_restructured_ever', 'bureau_thin_file',
            'business_assessment', 'character_assessment',
        ]
        widgets = {
            'nbe_report_date_received': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'bureau_report_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
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
        # Computed from qualitative factors earned scores.
        self.fields['qualitative_total_score'].disabled = True
        self.fields['qualitative_passed'].disabled = True


class AppraisalSheet3Form(forms.ModelForm):
    """
    Sheet (3) Cashflow analysis.
    Phase 0: aggregate income/expense + installment → net cashflow, DSCR (computed).
    Phase 1: optional P&L lines roll into business income (from sales) / expenses when filled.
    Phase 2: annual net cashflow, annual debt service, annual DSCR (computed from Sheet 1 frequency).
    """
    class Meta:
        model = LoanAppraisal
        fields = [
            # Phase 1 – structured monthly P&L
            'cf_monthly_sales', 'cf_monthly_cogs', 'cf_monthly_salaries', 'cf_monthly_rent',
            'cf_monthly_utilities', 'cf_monthly_transport', 'cf_monthly_other_operating', 'cf_monthly_taxes',
            # Phase 0 – aggregates (optional if Phase 1 breakdown used)
            'monthly_business_income', 'monthly_business_expenses', 'other_monthly_income', 'other_monthly_expenses',
            'proposed_monthly_installment',
            # Stress test (sensitivity)
            'stress_sales_drop_pct', 'stress_cost_increase_pct',
        ]
        widgets = {
            'cf_monthly_sales': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cf_monthly_cogs': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cf_monthly_salaries': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cf_monthly_rent': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cf_monthly_utilities': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cf_monthly_transport': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cf_monthly_other_operating': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cf_monthly_taxes': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'monthly_business_income': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'monthly_business_expenses': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'other_monthly_income': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'other_monthly_expenses': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'proposed_monthly_installment': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'stress_sales_drop_pct': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'stress_cost_increase_pct': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
        }

    def __init__(self, *args, basic_info=None, **kwargs):
        self.basic_info = basic_info
        super().__init__(*args, **kwargs)
        for name in self.fields:
            self.fields[name].widget.attrs.setdefault('class', 'form-control')
        self.fields['monthly_business_income'].help_text = (
            'Leave blank to use Monthly sales (Phase 1) as business income when sales is filled.'
        )
        self.fields['monthly_business_expenses'].help_text = (
            'When P&L expense lines sum to more than 0, that sum replaces monthly business expenses.'
        )

    def clean(self):
        from decimal import Decimal, InvalidOperation
        from .cashflow_utils import payments_per_year_from_repayment_frequency, annual_debt_service

        data = super().clean()

        def d(v):
            return v if v is not None else Decimal('0')

        pl_exp = (
            d(data.get('cf_monthly_cogs'))
            + d(data.get('cf_monthly_salaries'))
            + d(data.get('cf_monthly_rent'))
            + d(data.get('cf_monthly_utilities'))
            + d(data.get('cf_monthly_transport'))
            + d(data.get('cf_monthly_other_operating'))
            + d(data.get('cf_monthly_taxes'))
        )
        if pl_exp > 0:
            data['monthly_business_expenses'] = pl_exp

        sales = data.get('cf_monthly_sales')
        if data.get('monthly_business_income') is None and sales is not None:
            data['monthly_business_income'] = sales

        inc1 = d(data.get('monthly_business_income'))
        inc2 = d(data.get('other_monthly_income'))
        exp1 = d(data.get('monthly_business_expenses'))
        exp2 = d(data.get('other_monthly_expenses'))
        net = inc1 + inc2 - exp1 - exp2
        self._computed_net_monthly = net

        installment = data.get('proposed_monthly_installment')
        self._computed_dscr_monthly = None
        if installment and installment > 0:
            try:
                self._computed_dscr_monthly = (net / installment).quantize(Decimal('0.01'))
            except (InvalidOperation, ZeroDivisionError):
                pass

        freq = getattr(self.basic_info, 'repayment_frequency', None) if self.basic_info else None
        ppy = payments_per_year_from_repayment_frequency(freq)
        self._payments_per_year = ppy
        self._computed_annual_debt = annual_debt_service(installment, ppy)
        self._computed_annual_net = (net * Decimal('12')).quantize(Decimal('0.01')) if net is not None else None
        self._computed_dscr_annual = None
        if self._computed_annual_net is not None and self._computed_annual_debt and self._computed_annual_debt > 0:
            try:
                self._computed_dscr_annual = (
                    self._computed_annual_net / self._computed_annual_debt
                ).quantize(Decimal('0.01'))
            except (InvalidOperation, ZeroDivisionError):
                pass

        # Stress test: apply % shock to income and expenses, then recompute net + DSCR.
        drop_pct = data.get('stress_sales_drop_pct')
        cost_pct = data.get('stress_cost_increase_pct')
        self._computed_stressed_net = None
        self._computed_stressed_dscr = None
        if (drop_pct is not None) or (cost_pct is not None):
            try:
                drop = d(drop_pct) / Decimal('100')
                cost = d(cost_pct) / Decimal('100')
                stressed_inc = (inc1 + inc2) * (Decimal('1') - drop)
                stressed_exp = (exp1 + exp2) * (Decimal('1') + cost)
                self._computed_stressed_net = (stressed_inc - stressed_exp).quantize(Decimal('0.01'))
                if installment and installment > 0:
                    self._computed_stressed_dscr = (self._computed_stressed_net / installment).quantize(Decimal('0.01'))
            except (InvalidOperation, ZeroDivisionError):
                pass

        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.net_monthly_cashflow = self._computed_net_monthly
        obj.dscr = self._computed_dscr_monthly
        obj.cf_annual_net_cashflow = self._computed_annual_net
        obj.cf_annual_debt_service = self._computed_annual_debt
        obj.dscr_annual = self._computed_dscr_annual
        obj.stressed_net_monthly_cashflow = getattr(self, '_computed_stressed_net', None)
        obj.stressed_dscr = getattr(self, '_computed_stressed_dscr', None)
        if commit:
            obj.save()
        return obj


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
        self.fields['amount_approved'].label = 'Recommended amount (ETB)'
        self.fields['amount_approved'].help_text = (
            'Amount the loan officer recommends; sent to the approval committee after appraisal.'
        )
        self.fields['term_approved_months'].label = 'Recommended term (months)'
        self.fields['rate_approved'].label = 'Recommended rate (%)'
        self.fields['committee_comments'].label = 'Notes for committee (optional)'


class CommitteeVoteForm(forms.Form):
    vote = forms.ChoiceField(
        choices=[
            ('approve', 'Approve'),
            ('decline', 'Decline'),
        ],
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    amount_supported = forms.DecimalField(
        required=False,
        min_value=0,
        decimal_places=2,
        max_digits=20,
        label='Amount you approve (ETB)',
        help_text='Leave blank to use the loan officer’s recommended amount.',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )
    comments = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )


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