"""Market actors (dealers/brokers) and price observations for collateral intelligence."""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class MarketActor(models.Model):
    """Dealer, broker, sales person, or supplier who can feed market prices."""

    KIND_DEALER = 'dealer'
    KIND_BROKER = 'broker'
    KIND_SALES = 'sales_person'
    KIND_SUPPLIER = 'supplier'
    KIND_COOPERATIVE = 'cooperative'
    KIND_OTHER = 'other'
    KIND_CHOICES = [
        (KIND_DEALER, 'Dealer / shop'),
        (KIND_BROKER, 'Broker'),
        (KIND_SALES, 'Sales person'),
        (KIND_SUPPLIER, 'Supplier'),
        (KIND_COOPERATIVE, 'Cooperative / SACCO'),
        (KIND_OTHER, 'Other'),
    ]

    TRUST_PENDING = 'pending'
    TRUST_TRUSTED = 'trusted'
    TRUST_SUSPENDED = 'suspended'
    TRUST_CHOICES = [
        (TRUST_PENDING, 'Pending'),
        (TRUST_TRUSTED, 'Trusted'),
        (TRUST_SUSPENDED, 'Suspended'),
    ]

    FOCUS_BUILDING = 'building_materials'
    FOCUS_LAND = 'land'
    FOCUS_VEHICLE = 'vehicle'
    FOCUS_MACHINERY = 'machinery'
    FOCUS_OTHER = 'other'
    FOCUS_MIXED = 'mixed'
    FOCUS_CHOICES = [
        (FOCUS_BUILDING, 'Building materials / construction'),
        (FOCUS_LAND, 'Land / plots'),
        (FOCUS_VEHICLE, 'Vehicles'),
        (FOCUS_MACHINERY, 'Machinery / equipment'),
        (FOCUS_OTHER, 'Other movable'),
        (FOCUS_MIXED, 'Mixed'),
    ]

    name = models.CharField(max_length=255)
    actor_kind = models.CharField(
        max_length=30, choices=KIND_CHOICES, default=KIND_DEALER, db_index=True,
    )
    phone_number = models.CharField(max_length=30, blank=True)
    contact_person = models.CharField(max_length=120, blank=True)
    address = models.CharField(max_length=500, blank=True)
    product_focus = models.CharField(
        max_length=30, choices=FOCUS_CHOICES, default=FOCUS_BUILDING, db_index=True,
    )
    product_lines = models.CharField(
        max_length=255, blank=True,
        help_text='e.g. cement, HCB, steel, solar.',
    )
    trust_status = models.CharField(
        max_length=20, choices=TRUST_CHOICES, default=TRUST_PENDING, db_index=True,
    )
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True)
    branch = models.ForeignKey(
        'loans.Branch',
        on_delete=models.PROTECT,
        related_name='market_actors',
        null=True,
        blank=True,
        help_text='Optional branch tag; portal self-register may leave blank.',
    )
    primary_city = models.ForeignKey(
        'loans.City',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='market_actors',
        help_text='Main woreda/city this actor operates in.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='market_actors_created',
    )
    # Standalone dealer portal (not LO/BM loan hub) — password auth for this actor only.
    portal_enabled = models.BooleanField(
        default=False,
        help_text='If on, this actor can log into /market-portal/ separately from loan staff.',
    )
    portal_username = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        unique=True,
        help_text='Login for dealer portal (often phone). Blank = portal off.',
    )
    portal_password = models.CharField(
        max_length=128,
        blank=True,
        help_text='Hashed portal password (Django make_password).',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['branch', 'name'],
                name='partners_unique_actor_name_per_branch',
            ),
        ]
        indexes = [
            models.Index(fields=['branch', 'is_active', 'name']),
            models.Index(fields=['branch', 'actor_kind']),
            models.Index(fields=['trust_status', 'product_focus']),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_actor_kind_display()})'

    def set_portal_password(self, raw_password: str) -> None:
        from django.contrib.auth.hashers import make_password
        self.portal_password = make_password(raw_password) if raw_password else ''

    def check_portal_password(self, raw_password: str) -> bool:
        from django.contrib.auth.hashers import check_password
        if not self.portal_enabled or not self.portal_password or not raw_password:
            return False
        return check_password(raw_password, self.portal_password)

    def can_use_portal(self) -> bool:
        return bool(
            self.portal_enabled
            and self.is_active
            and self.trust_status != self.TRUST_SUSPENDED
            and self.portal_username
            and self.portal_password
        )



class MarketObservation(models.Model):
    """One price fact from a market actor — fuel for aggregation / auto-suggest later."""

    ASSET_BUILDING = 'building'
    ASSET_LAND = 'land'
    ASSET_VEHICLE = 'vehicle'
    ASSET_MACHINERY = 'machinery'
    ASSET_OTHER = 'other'
    ASSET_CHOICES = [
        (ASSET_BUILDING, 'Building / construction item'),
        (ASSET_LAND, 'Land (ETB/m²)'),
        (ASSET_VEHICLE, 'Vehicle'),
        (ASSET_MACHINERY, 'Machinery'),
        (ASSET_OTHER, 'Other'),
    ]

    CHANNEL_STAFF = 'staff'
    CHANNEL_PORTAL = 'portal'
    CHANNEL_INVITE = 'invite'
    CHANNEL_IMPORT = 'import'
    CHANNEL_SMS = 'sms'
    CHANNEL_CHOICES = [
        (CHANNEL_STAFF, 'Staff quote proxy'),
        (CHANNEL_PORTAL, 'Dealer portal'),
        (CHANNEL_INVITE, 'Invite link'),
        (CHANNEL_IMPORT, 'Excel / bulk import'),
        (CHANNEL_SMS, 'SMS / USSD'),
    ]

    STATUS_ACTIVE = 'active'
    STATUS_PENDING = 'pending'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_PENDING, 'Pending review'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    CONDITION_NEW = 'new'
    CONDITION_USED = 'used'
    CONDITION_NA = 'na'
    CONDITION_CHOICES = [
        (CONDITION_NEW, 'New'),
        (CONDITION_USED, 'Used'),
        (CONDITION_NA, 'N/A'),
    ]

    market_actor = models.ForeignKey(
        MarketActor,
        on_delete=models.CASCADE,
        related_name='observations',
    )
    branch = models.ForeignKey(
        'loans.Branch',
        on_delete=models.PROTECT,
        related_name='market_observations',
        null=True,
        blank=True,
        help_text='Optional; mirrors actor.branch when set.',
    )
    city = models.ForeignKey(
        'loans.City',
        on_delete=models.PROTECT,
        related_name='market_observations',
    )
    asset_class = models.CharField(
        max_length=20, choices=ASSET_CHOICES, default=ASSET_BUILDING, db_index=True,
    )
    # Optional link into construction catalog (building materials)
    sub_work = models.ForeignKey(
        'collateral.SubWork',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='market_observations',
    )
    sub_sub_work = models.ForeignKey(
        'collateral.SubSubWork',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='market_observations',
    )
    item_label = models.CharField(
        max_length=255,
        help_text='Free-text item name if not linked to catalog (e.g. cement 50kg bag).',
    )
    unit = models.CharField(max_length=40, blank=True, help_text='e.g. bag, m², m³, piece')
    unit_price_etb = models.DecimalField(max_digits=20, decimal_places=2)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    condition = models.CharField(
        max_length=10, choices=CONDITION_CHOICES, default=CONDITION_NA,
    )
    observed_at = models.DateField(db_index=True, default=timezone.localdate)
    channel = models.CharField(
        max_length=20, choices=CHANNEL_CHOICES, default=CHANNEL_STAFF, db_index=True,
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True,
    )
    notes = models.TextField(blank=True)
    site_lat = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    site_lon = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='market_observations_recorded',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-observed_at', '-created_at']
        verbose_name = 'market observation'
        verbose_name_plural = 'market observations'
        indexes = [
            models.Index(fields=['branch', 'observed_at']),
            models.Index(fields=['city', 'asset_class', 'observed_at']),
            models.Index(fields=['status', 'observed_at']),
            models.Index(fields=['market_actor', 'observed_at']),
        ]

    def __str__(self):
        return f'{self.item_label} @ {self.unit_price_etb} ({self.observed_at})'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.unit_price_etb is not None and self.unit_price_etb <= Decimal('0'):
            raise ValidationError({'unit_price_etb': 'Price must be positive.'})
        if not (self.item_label or '').strip() and not self.sub_work_id and not self.sub_sub_work_id:
            raise ValidationError('Provide item label or link a catalog work item.')

    def save(self, *args, **kwargs):
        if self.market_actor_id and not self.branch_id:
            self.branch_id = self.market_actor.branch_id
        if self.sub_sub_work_id and not self.item_label:
            self.item_label = str(self.sub_sub_work)[:255]
        elif self.sub_work_id and not self.item_label:
            self.item_label = str(self.sub_work)[:255]
        super().save(*args, **kwargs)

    @property
    def catalog_label(self):
        if self.sub_sub_work_id:
            return str(self.sub_sub_work)
        if self.sub_work_id:
            return str(self.sub_work)
        return self.item_label


class MarketPriceBand(models.Model):
    """Aggregated market memory for auto-suggest on engineering unit prices."""

    WINDOW_DAYS_DEFAULT = 90
    MIN_SAMPLES_SUGGEST = 3

    city = models.ForeignKey(
        'loans.City',
        on_delete=models.CASCADE,
        related_name='market_price_bands',
    )
    asset_class = models.CharField(
        max_length=20,
        choices=MarketObservation.ASSET_CHOICES,
        default=MarketObservation.ASSET_BUILDING,
        db_index=True,
    )
    sub_work = models.ForeignKey(
        'collateral.SubWork',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='market_price_bands',
    )
    sub_sub_work = models.ForeignKey(
        'collateral.SubSubWork',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='market_price_bands',
    )
    # Free-text key when not linked to BOQ catalog (land/vehicles, informal labels)
    item_key = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text='Normalized item label key when no sub_work / sub_sub_work.',
    )
    unit = models.CharField(max_length=40, blank=True)
    sample_count = models.PositiveIntegerField(default=0)
    median_price = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    p25_price = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    p75_price = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    min_price = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    max_price = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    last_observed_at = models.DateField(null=True, blank=True)
    window_days = models.PositiveIntegerField(default=WINDOW_DAYS_DEFAULT)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['city_id', 'asset_class', 'item_key']
        indexes = [
            models.Index(fields=['city', 'sub_work', 'sub_sub_work']),
            models.Index(fields=['city', 'item_key']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['city', 'asset_class', 'sub_work', 'sub_sub_work', 'item_key', 'unit'],
                name='partners_unique_market_price_band',
            ),
        ]

    def __str__(self):
        label = self.item_key or (
            str(self.sub_sub_work) if self.sub_sub_work_id else str(self.sub_work or '—')
        )
        return f'{label} @ {self.city_id}: median {self.median_price} (n={self.sample_count})'

    @property
    def is_suggestible(self) -> bool:
        return (
            self.sample_count >= self.MIN_SAMPLES_SUGGEST
            and self.median_price is not None
            and self.median_price > 0
        )

    @property
    def freshness_days(self):
        if not self.last_observed_at:
            return None
        from django.utils import timezone
        return (timezone.localdate() - self.last_observed_at).days
