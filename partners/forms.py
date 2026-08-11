from decimal import Decimal

from django import forms

from partners.models import MarketActor, MarketObservation


class MarketActorForm(forms.ModelForm):
    portal_password_new = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
        label='Portal password (set/change)',
        help_text='Only for the separate dealer portal at /market-portal/. Leave blank to keep current.',
    )

    class Meta:
        model = MarketActor
        fields = (
            'name',
            'actor_kind',
            'phone_number',
            'contact_person',
            'address',
            'product_focus',
            'product_lines',
            'trust_status',
            'primary_city',
            'is_active',
            'portal_enabled',
            'portal_username',
            'notes',
        )
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            'contact_person': forms.TextInput(attrs={'class': 'form-control'}),
            'product_lines': forms.TextInput(attrs={'class': 'form-control'}),
            'portal_username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Dealer portal login (e.g. phone)',
            }),
        }

    def __init__(self, *args, require_branch=False, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if not field.widget.attrs.get('class') and not isinstance(
                field.widget, (forms.CheckboxInput, forms.RadioSelect)
            ):
                field.widget.attrs.setdefault('class', 'form-control')
        self.fields['primary_city'].queryset = self.fields['primary_city'].queryset.order_by(
            'zone__region__name', 'zone__name', 'name'
        )
        self.fields['primary_city'].required = False
        self.fields['portal_username'].required = False
        if require_branch:
            from loans.models import Branch
            self.fields['branch'] = forms.ModelChoiceField(
                queryset=Branch.objects.order_by('name'),
                required=True,
                widget=forms.Select(attrs={'class': 'form-control'}),
            )
            if self.instance and self.instance.branch_id:
                self.fields['branch'].initial = self.instance.branch_id

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('portal_enabled'):
            username = (cleaned.get('portal_username') or '').strip()
            if not username:
                self.add_error('portal_username', 'Portal username required when portal is enabled.')
            pwd = cleaned.get('portal_password_new') or ''
            if not self.instance.pk or not self.instance.portal_password:
                if not pwd:
                    self.add_error('portal_password_new', 'Set a portal password when enabling portal access.')
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        pwd = self.cleaned_data.get('portal_password_new')
        if pwd:
            obj.set_portal_password(pwd)
        if commit:
            obj.save()
        return obj


class MarketObservationForm(forms.ModelForm):
    class Meta:
        model = MarketObservation
        fields = (
            'market_actor',
            'city',
            'asset_class',
            'sub_work',
            'sub_sub_work',
            'item_label',
            'unit',
            'unit_price_etb',
            'quantity',
            'condition',
            'observed_at',
            'notes',
        )
        widgets = {
            'observed_at': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'item_label': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Cement 50kg bag, HCB 20cm',
            }),
            'unit': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'bag, m², piece'}),
            'unit_price_etb': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
        }

    def __init__(self, *args, actors_qs=None, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if not field.widget.attrs.get('class') and not isinstance(
                field.widget, (forms.CheckboxInput, forms.RadioSelect)
            ):
                field.widget.attrs.setdefault('class', 'form-control')
        if actors_qs is not None:
            self.fields['market_actor'].queryset = actors_qs.filter(is_active=True).order_by('name')
        self.fields['city'].queryset = self.fields['city'].queryset.order_by(
            'zone__region__name', 'zone__name', 'name'
        )
        self.fields['sub_work'].required = False
        self.fields['sub_sub_work'].required = False
        self.fields['sub_work'].queryset = self.fields['sub_work'].queryset.select_related(
            'main_work'
        ).order_by('main_work__order', 'order', 'name')
        self.fields['sub_sub_work'].queryset = self.fields['sub_sub_work'].queryset.select_related(
            'sub_work', 'sub_work__main_work'
        ).order_by('sub_work__main_work__order', 'sub_work__order', 'order', 'name')
        self.fields['item_label'].required = False
        self.fields['market_actor'].label = 'Market actor (dealer / broker)'
        self.fields['unit_price_etb'].label = 'Unit price (ETB)'

    def clean(self):
        cleaned = super().clean()
        item = (cleaned.get('item_label') or '').strip()
        sub = cleaned.get('sub_work')
        ssub = cleaned.get('sub_sub_work')
        if not item and not sub and not ssub:
            raise forms.ValidationError(
                'Enter an item label or select a catalog sub-work / sub-sub-work.'
            )
        if not item:
            if ssub:
                cleaned['item_label'] = str(ssub)[:255]
            elif sub:
                cleaned['item_label'] = str(sub)[:255]
        price = cleaned.get('unit_price_etb')
        if price is not None and price <= 0:
            self.add_error('unit_price_etb', 'Price must be positive.')
        return cleaned


class PortalLoginForm(forms.Form):
    username = forms.CharField(
        max_length=64,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'autocomplete': 'username',
            'placeholder': 'Username',
        }),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'current-password',
            'placeholder': 'Password',
        }),
    )

    def clean(self):
        cleaned = super().clean()
        username = (cleaned.get('username') or '').strip()
        password = cleaned.get('password') or ''
        actor = MarketActor.objects.filter(portal_username__iexact=username).first()
        if not actor or not actor.check_portal_password(password) or not actor.can_use_portal():
            raise forms.ValidationError('Invalid username or password, or account suspended.')
        cleaned['actor'] = actor
        return cleaned


def _init_area_cascade_fields(form, data=None, initial_city=None):
    """Wire region → zone → city selects for portal forms."""
    from loans.models import City, Region, Zone

    form.fields['region'].queryset = Region.objects.order_by('name')
    form.fields['zone'].queryset = Zone.objects.none()
    form.fields['city'].queryset = City.objects.none()
    if data is not None:
        rid = data.get('region')
        zid = data.get('zone')
        if rid:
            form.fields['zone'].queryset = Zone.objects.filter(region_id=rid).order_by('name')
        if zid:
            form.fields['city'].queryset = City.objects.filter(zone_id=zid).order_by('name')
    elif initial_city is not None:
        city = initial_city
        if city and getattr(city, 'pk', None):
            if not hasattr(city, 'zone') or city.zone_id is None:
                city = City.objects.select_related('zone', 'zone__region').get(pk=city.pk)
            zone = city.zone
            region = zone.region if zone else None
            if region:
                form.fields['region'].initial = region.pk
                form.fields['zone'].queryset = Zone.objects.filter(region=region).order_by('name')
            if zone:
                form.fields['zone'].initial = zone.pk
                form.fields['city'].queryset = City.objects.filter(zone=zone).order_by('name')
            form.fields['city'].initial = city.pk


class PortalProfileForm(forms.Form):
    """Edit registered market-actor profile (identity, location, optional password)."""

    name = forms.CharField(
        max_length=255,
        label='Business / your name',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    phone_number = forms.CharField(
        max_length=30,
        required=False,
        label='Phone',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    actor_kind = forms.ChoiceField(
        choices=MarketActor.KIND_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='I am a',
    )
    product_focus = forms.ChoiceField(
        choices=MarketActor.FOCUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Main products',
    )
    region = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label='Region',
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_region'}),
    )
    zone = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label='Zone',
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_zone'}),
    )
    city = forms.ModelChoiceField(
        queryset=None,
        label='City / Woreda where you trade',
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_city'}),
    )
    username = forms.CharField(
        max_length=64,
        label='Username',
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'username'}),
    )
    password = forms.CharField(
        required=False,
        min_length=6,
        label='New password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'new-password',
            'placeholder': 'Leave blank to keep current',
        }),
    )
    password2 = forms.CharField(
        required=False,
        label='Confirm new password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'new-password',
        }),
    )

    def __init__(self, *args, actor=None, **kwargs):
        self.actor = actor
        super().__init__(*args, **kwargs)
        data = args[0] if args else None
        initial_city = None
        if actor and actor.primary_city_id and data is None:
            initial_city = actor.primary_city
        _init_area_cascade_fields(self, data, initial_city=initial_city)
        if actor and data is None:
            self.fields['name'].initial = actor.name
            self.fields['phone_number'].initial = actor.phone_number
            self.fields['actor_kind'].initial = actor.actor_kind
            self.fields['product_focus'].initial = actor.product_focus
            self.fields['username'].initial = actor.portal_username or ''

    def clean_username(self):
        u = (self.cleaned_data.get('username') or '').strip()
        qs = MarketActor.objects.filter(portal_username__iexact=u)
        if self.actor:
            qs = qs.exclude(pk=self.actor.pk)
        if qs.exists():
            raise forms.ValidationError('That username is already taken.')
        return u

    def clean(self):
        cleaned = super().clean()
        pwd = cleaned.get('password') or ''
        pwd2 = cleaned.get('password2') or ''
        if pwd or pwd2:
            if len(pwd) < 6:
                self.add_error('password', 'Password must be at least 6 characters.')
            if pwd != pwd2:
                self.add_error('password2', 'Passwords do not match.')
        if not cleaned.get('city'):
            self.add_error('city', 'Select region, zone, then city/woreda where you operate.')
        return cleaned

    def save(self) -> MarketActor:
        actor = self.actor
        actor.name = self.cleaned_data['name'].strip()
        actor.phone_number = (self.cleaned_data.get('phone_number') or '').strip()[:30]
        actor.actor_kind = self.cleaned_data['actor_kind']
        actor.product_focus = self.cleaned_data['product_focus']
        actor.primary_city = self.cleaned_data['city']
        actor.portal_username = self.cleaned_data['username'].strip()
        pwd = self.cleaned_data.get('password') or ''
        if pwd:
            actor.set_portal_password(pwd)
        actor.save()
        return actor


class PortalRegisterForm(forms.Form):
    name = forms.CharField(
        max_length=255,
        label='Business / your name',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    phone_number = forms.CharField(
        max_length=30,
        required=False,
        label='Phone',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    actor_kind = forms.ChoiceField(
        choices=MarketActor.KIND_CHOICES,
        initial=MarketActor.KIND_DEALER,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='I am a',
    )
    product_focus = forms.ChoiceField(
        choices=MarketActor.FOCUS_CHOICES,
        initial=MarketActor.FOCUS_BUILDING,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Main products',
    )
    region = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label='Region',
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_region'}),
    )
    zone = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label='Zone',
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_zone'}),
    )
    city = forms.ModelChoiceField(
        queryset=None,
        label='City / Woreda where you trade',
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_city'}),
        help_text='Saved once — used for every price you submit later.',
    )
    username = forms.CharField(
        max_length=64,
        label='Choose username',
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'username'}),
    )
    password = forms.CharField(
        min_length=6,
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )
    password2 = forms.CharField(
        label='Confirm password',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        data = args[0] if args else None
        _init_area_cascade_fields(self, data)

    def clean_username(self):
        u = (self.cleaned_data.get('username') or '').strip()
        if MarketActor.objects.filter(portal_username__iexact=u).exists():
            raise forms.ValidationError('That username is already taken.')
        return u

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('password') != cleaned.get('password2'):
            self.add_error('password2', 'Passwords do not match.')
        if not cleaned.get('city'):
            self.add_error('city', 'Select region, zone, then city/woreda where you operate.')
        return cleaned

    def save(self) -> MarketActor:
        actor = MarketActor(
            name=self.cleaned_data['name'].strip(),
            phone_number=(self.cleaned_data.get('phone_number') or '').strip()[:30],
            actor_kind=self.cleaned_data['actor_kind'],
            product_focus=self.cleaned_data['product_focus'],
            primary_city=self.cleaned_data['city'],
            trust_status=MarketActor.TRUST_TRUSTED,
            portal_enabled=True,
            portal_username=self.cleaned_data['username'].strip(),
            is_active=True,
            notes='Self-registered via market portal',
            branch=None,
        )
        actor.set_portal_password(self.cleaned_data['password'])
        actor.save()
        return actor


class PortalStep1AreaForm(forms.Form):
    """Step 1 of 2: who you are (guests) + region → zone → city."""

    guest_name = forms.CharField(
        required=False,
        max_length=255,
        label='Your name / shop',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Adi Haki Building Materials'}),
    )
    guest_phone = forms.CharField(
        required=False,
        max_length=30,
        label='Phone (optional)',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '09…'}),
    )
    region = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label='Region',
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_region'}),
    )
    zone = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label='Zone',
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_zone'}),
    )
    city = forms.ModelChoiceField(
        queryset=None,
        label='City / Woreda',
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_city'}),
    )

    def __init__(self, *args, for_guest=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.for_guest = for_guest
        if not for_guest:
            self.fields.pop('guest_name', None)
            self.fields.pop('guest_phone', None)
            self.fields['city'].label = 'City / Woreda where you trade'
            self.fields['city'].help_text = 'Updates your saved location for future prices.'

        data = args[0] if args else None
        _init_area_cascade_fields(self, data)

    def clean(self):
        cleaned = super().clean()
        if self.for_guest and not (cleaned.get('guest_name') or '').strip():
            cleaned['guest_name'] = 'Guest reporter'
        if not cleaned.get('city'):
            self.add_error('city', 'Select region, zone, then city/woreda.')
        return cleaned

    def to_session_dict(self) -> dict:
        city = self.cleaned_data['city']
        d = {
            'city_id': city.pk,
            'city_label': str(city),
            'region_id': self.cleaned_data.get('region').pk if self.cleaned_data.get('region') else None,
            'zone_id': self.cleaned_data.get('zone').pk if self.cleaned_data.get('zone') else None,
        }
        if self.for_guest:
            d['guest_name'] = (self.cleaned_data.get('guest_name') or 'Guest reporter').strip()
            d['guest_phone'] = (self.cleaned_data.get('guest_phone') or '').strip()
        return d


class PortalStep2ProductForm(forms.Form):
    """Step 2 of 2: product mode (catalog XOR free text) + price."""

    MODE_CATALOG = 'catalog'
    MODE_FREE = 'free'
    MODE_CHOICES = [
        (MODE_CATALOG, 'Construction catalog'),
        (MODE_FREE, 'Other product (type it)'),
    ]

    product_mode = forms.ChoiceField(
        choices=MODE_CHOICES,
        widget=forms.RadioSelect,
        label='How do you want to describe the item?',
        initial=MODE_CATALOG,
    )
    main_work = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label='Main work',
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_main_work'}),
    )
    sub_work = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label='Sub work',
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_sub_work'}),
    )
    sub_sub_work = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label='Sub-sub work (optional)',
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_sub_sub_work'}),
    )
    item_label = forms.CharField(
        required=False,
        max_length=255,
        label='Product name',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. Cement 50kg bag, used Hilux…',
        }),
    )
    unit = forms.CharField(
        required=False,
        max_length=40,
        label='Unit',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'bag, m², piece'}),
    )
    unit_price_etb = forms.DecimalField(
        max_digits=20,
        decimal_places=2,
        min_value=Decimal('0.01'),
        label='Price (ETB)',
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'step': '0.01', 'min': '0', 'inputmode': 'decimal',
        }),
    )
    condition = forms.ChoiceField(
        choices=MarketObservation.CONDITION_CHOICES,
        initial=MarketObservation.CONDITION_NA,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    observed_at = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from collateral.models import MainWork, SubWork, SubSubWork
        from django.utils import timezone

        self.fields['main_work'].queryset = MainWork.objects.order_by('order', 'name')
        self.fields['sub_work'].queryset = SubWork.objects.none()
        self.fields['sub_sub_work'].queryset = SubSubWork.objects.none()
        if not self.fields['observed_at'].initial:
            self.fields['observed_at'].initial = timezone.localdate()

        data = args[0] if args else None
        if data is not None:
            mid = data.get('main_work')
            swid = data.get('sub_work')
            if mid:
                self.fields['sub_work'].queryset = SubWork.objects.filter(
                    main_work_id=mid
                ).order_by('order', 'name')
            if swid:
                self.fields['sub_sub_work'].queryset = SubSubWork.objects.filter(
                    sub_work_id=swid
                ).order_by('order', 'name')

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get('product_mode') or self.MODE_CATALOG
        if mode == self.MODE_CATALOG:
            sub = cleaned.get('sub_work')
            ssub = cleaned.get('sub_sub_work')
            if not sub and not ssub:
                raise forms.ValidationError(
                    'Pick main work → sub work (sub-sub optional) from the catalog.'
                )
            cleaned['item_label'] = str(ssub or sub)[:255]
            cleaned['sub_work'] = ssub.sub_work if ssub and not sub else sub
            if ssub and not cleaned.get('sub_work'):
                cleaned['sub_work'] = ssub.sub_work
        else:
            cleaned['sub_work'] = None
            cleaned['sub_sub_work'] = None
            label = (cleaned.get('item_label') or '').strip()
            if len(label) < 2:
                self.add_error('item_label', 'Type the product name.')
            cleaned['item_label'] = label
        if not cleaned.get('observed_at'):
            from django.utils import timezone
            cleaned['observed_at'] = timezone.localdate()
        return cleaned
