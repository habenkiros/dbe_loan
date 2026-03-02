# collateral/forms.py
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
    """Only engineering team (and admin) can enter or override unit price; others use catalog."""
    return user and getattr(user, 'role', None) in (
        'engineering_head', 'engineer', 'admin', 'superadmin',
    )


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
        if not can_edit_unit_price:
            self.fields.pop('unit_price', None)

    def clean(self):
        data = super().clean()
        sub_work = data.get('sub_work')
        sub_sub_work = data.get('sub_sub_work')
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


class BuildingImageForm(forms.ModelForm):
    class Meta:
        model = BuildingImage
        fields = ['image', 'caption', 'gps_lat', 'gps_lon']
        widgets = {
            'image': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'caption': forms.TextInput(attrs={'class': 'form-control'}),
            'gps_lat': forms.NumberInput(attrs={'class': 'form-control', 'step': 'any', 'placeholder': 'Latitude'}),
            'gps_lon': forms.NumberInput(attrs={'class': 'form-control', 'step': 'any', 'placeholder': 'Longitude'}),
        }


class OtherCollateralItemForm(forms.ModelForm):
    """For vehicle, machinery, equipment, etc. – name and estimated value."""
    class Meta:
        model = OtherCollateralItem
        fields = ['name', 'estimated_value', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Toyota Pickup, Tractor'}),
            'estimated_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


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
