# collateral/forms.py
from decimal import Decimal

from django import forms
from .models import (
    Building, BuildingValuation, BuildingImage, LandValuation,
    MainWork, SubWork, SubSubWork, SubWorkUnitPrice,
    OtherCollateralItem,
)
from loans.models import City


class MainWorkForm(forms.ModelForm):
    class Meta:
        model = MainWork
        fields = ['name', 'order']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Foundation, Concrete'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'step': 1}),
        }


class SubWorkForm(forms.ModelForm):
    class Meta:
        model = SubWork
        fields = ['main_work', 'name', 'order']
        widgets = {
            'main_work': forms.Select(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Columns, Beams'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'step': '0.01', 'placeholder': 'e.g. 1.1, 1.2'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['main_work'].queryset = MainWork.objects.all().order_by('order', 'name')


class SubSubWorkForm(forms.ModelForm):
    class Meta:
        model = SubSubWork
        fields = ['sub_work', 'name', 'unit_measure', 'order']
        widgets = {
            'sub_work': forms.Select(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Reinforced Concrete Column C25'}),
            'unit_measure': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. m², m³'}),
            'order': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 1.1.1, 1.1.2'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sub_work'].queryset = SubWork.objects.all().select_related('main_work').order_by('main_work__order', 'main_work__name', 'order', 'name')


class BuildingForm(forms.ModelForm):
    class Meta:
        model = Building
        fields = ['name', 'construction_type', 'floors', 'city']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Building name or label'}),
            'construction_type': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Reinforced concrete'}),
            'floors': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'city': forms.Select(attrs={'class': 'form-control'}),
        }


def _user_can_edit_unit_price(user):
    """Only admin/superadmin can enter or override unit price; others (including engineering team) use catalog."""
    return user and getattr(user, 'role', None) in ('admin', 'superadmin')


class BuildingValuationForm(forms.ModelForm):
    """Valuation row: exactly one of sub_work or sub_sub_work; quantity and optional unit_price."""
    class Meta:
        model = BuildingValuation
        fields = ['sub_work', 'sub_sub_work', 'quantity', 'unit_price']
        widgets = {
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.0001', 'min': 0}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
        }

    def __init__(self, *args, can_edit_unit_price=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sub_work'].required = False
        self.fields['sub_work'].widget.attrs['class'] = 'form-control'
        self.fields['sub_sub_work'].required = False
        self.fields['sub_sub_work'].widget.attrs['class'] = 'form-control'
        self.fields['sub_sub_work'].queryset = self.fields['sub_sub_work'].queryset.select_related(
            'sub_work', 'sub_work__main_work'
        ).order_by('sub_work__main_work', 'sub_work', 'order', 'name')
        self.fields['quantity'].required = False
        self.fields['quantity'].widget.attrs['class'] = 'form-control'
        if not can_edit_unit_price:
            self.fields.pop('unit_price', None)

    def clean(self):
        from decimal import Decimal
        data = super().clean()
        sub_work = data.get('sub_work')
        sub_sub_work = data.get('sub_sub_work')
        if sub_work and sub_sub_work:
            data['sub_work'] = None
            return data
        if bool(sub_work) == bool(sub_sub_work):
            from django import forms as django_forms
            raise django_forms.ValidationError('Please select one work item from the list above.')
        if data.get('quantity') in (None, ''):
            data['quantity'] = Decimal('0')
        return data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.sub_sub_work_id:
            instance.sub_work_id = None
        else:
            instance.sub_sub_work_id = None
        if commit:
            instance.save()
        return instance


class BuildingImageForm(forms.ModelForm):
    class Meta:
        model = BuildingImage
        fields = ['image', 'caption', 'photo_type']
        widgets = {
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
                'capture': 'environment',
            }),
            'caption': forms.TextInput(attrs={'class': 'form-control'}),
            'photo_type': forms.Select(attrs={'class': 'form-control'}),
        }


class OtherCollateralItemForm(forms.ModelForm):
    """For vehicle, machinery, equipment, etc."""
    class Meta:
        model = OtherCollateralItem
        fields = [
            'name', 'make_model', 'year_made', 'plate_number', 'chassis_vin',
            'odometer_or_hours', 'condition_grade', 'estimated_value', 'notes',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Toyota Pickup, Tractor'}),
            'make_model': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Make / model'}),
            'year_made': forms.NumberInput(attrs={'class': 'form-control', 'min': 1950, 'max': 2100}),
            'plate_number': forms.TextInput(attrs={'class': 'form-control'}),
            'chassis_vin': forms.TextInput(attrs={'class': 'form-control'}),
            'odometer_or_hours': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'km or hours'}),
            'condition_grade': forms.Select(attrs={'class': 'form-control'}),
            'estimated_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['year_made'].required = False
        self.fields['make_model'].required = False
        self.fields['plate_number'].required = False
        self.fields['chassis_vin'].required = False
        self.fields['odometer_or_hours'].required = False
        self.fields['condition_grade'].required = False
        self.fields['notes'].required = False
        self.fields['year_made'] = forms.IntegerField(
            required=False,
            min_value=1950,
            max_value=2100,
            widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 1950, 'max': 2100}),
        )

    def clean_year_made(self):
        val = self.cleaned_data.get('year_made')
        if val in (None, ''):
            return None
        return val

    def clean_estimated_value(self):
        val = self.cleaned_data.get('estimated_value')
        if val is None:
            return Decimal('0')
        return val


class LandValuationForm(forms.ModelForm):
    class Meta:
        model = LandValuation
        fields = ['land_size_sqm', 'unit_price_per_sqm', 'notes']
        widgets = {
            'land_size_sqm': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.0001', 'min': 0}),
            'unit_price_per_sqm': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class SubWorkUnitPriceForm(forms.ModelForm):
    """Unit price per SubWork or SubSubWork per woreda (City). Used by engineering team. Set exactly one of sub_work or sub_sub_work."""
    class Meta:
        model = SubWorkUnitPrice
        fields = ['city', 'sub_work', 'sub_sub_work', 'unit_price']
        widgets = {
            'unit_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['city'].widget.attrs['class'] = 'form-control'
        self.fields['sub_work'].required = False
        self.fields['sub_work'].widget.attrs['class'] = 'form-control'
        self.fields['sub_work'].queryset = SubWork.objects.all().select_related('main_work').order_by('main_work__order', 'main_work__name', 'order', 'name')
        self.fields['sub_sub_work'].required = False
        self.fields['sub_sub_work'].widget.attrs['class'] = 'form-control'
        self.fields['sub_sub_work'].queryset = SubSubWork.objects.all().select_related(
            'sub_work', 'sub_work__main_work'
        ).order_by('sub_work__main_work__order', 'sub_work__main_work__name', 'sub_work__order', 'sub_work__name', 'order', 'name')

    def clean(self):
        data = super().clean()
        sub_work = data.get('sub_work')
        sub_sub_work = data.get('sub_sub_work')
        # When both are set (user picked sub work then sub-sub work), prefer sub_sub_work
        if sub_work and sub_sub_work:
            data['sub_work'] = None
            return data
        if bool(sub_work) == bool(sub_sub_work):
            from django import forms as django_forms
            raise django_forms.ValidationError('Set exactly one of Sub work or Sub-sub work.')
        return data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.sub_sub_work_id:
            instance.sub_work_id = None
        else:
            instance.sub_sub_work_id = None
        if commit:
            instance.save()
        return instance


class CollateralPolicyConfigForm(forms.ModelForm):
    class Meta:
        from collateral.models import CollateralPolicyConfig
        model = CollateralPolicyConfig
        fields = [
            'min_images_per_building', 'min_images_per_land', 'min_images_per_other_item',
            'gps_accuracy_weak_threshold_m', 'photo_max_distance_from_site_m',
            'block_submit_on_far_photos', 'block_submit_on_missing_photo_gps',
            'min_coverage_ratio', 'flag_coverage_below_ratio',
            'declared_address_max_distance_from_site_m', 'block_submit_on_declared_address_mismatch',
            'require_movable_photo_types', 'exif_gps_mismatch_warn_m',
            'block_submit_on_exif_gps_mismatch',
        ]
        widgets = {
            'min_coverage_ratio': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'flag_coverage_below_ratio': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
        }


class CollateralUnlockRequestForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        min_length=20,
        help_text='Explain what must be corrected (min 20 characters).',
    )


class CollateralUnlockReviewForm(forms.Form):
    review_note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        label='Supervisor note',
    )


class CollateralEngineeringReviewForm(forms.Form):
    review_note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        label='Engineering note',
        help_text='Required when returning collateral for correction.',
    )

    def clean(self):
        data = super().clean()
        return data
