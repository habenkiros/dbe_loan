"""
Collateral valuation models.
Valuation is per building; unit prices are per SubWork per woreda (City).
"""
from decimal import Decimal
from django.db import models
from django.conf import settings


# ---------- Construction catalog (DECSI ዝርዝር ስራሕ) ----------

class MainWork(models.Model):
    """Level 1: ጠቅላላ ስራሕ (e.g. Foundation, Concrete, Wall, Roofing)."""
    name = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0, help_text="Display order")

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class SubWork(models.Model):
    """Level 2: under MainWork (e.g. Columns, Beams, Slabs under Concrete)."""
    main_work = models.ForeignKey(MainWork, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    order = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal('0'),
        help_text="Order number e.g. 1.1, 1.2 (related to main work)",
    )

    class Meta:
        ordering = ['main_work', 'order', 'name']
        unique_together = [('main_work', 'name')]

    def __str__(self):
        return f"{self.main_work.name} → {self.name}"


class SubSubWork(models.Model):
    """Level 3: under SubWork (e.g. Reinforced Concrete Column C25)."""
    sub_work = models.ForeignKey(SubWork, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    unit_measure = models.CharField(max_length=50, blank=True, help_text="e.g. m², m³")
    order = models.CharField(
        max_length=20, default='0',
        help_text="Order number e.g. 1.1.1, 1.1.2 (related to sub work)",
    )

    class Meta:
        ordering = ['sub_work', 'order', 'name']
        unique_together = [('sub_work', 'name')]

    def __str__(self):
        return f"{self.sub_work} → {self.name}"


# ---------- Unit price per woreda (City): per SubWork or SubSubWork ----------

class SubWorkUnitPrice(models.Model):
    """Unit price per SubWork or SubSubWork per City (woreda). Set by engineering team. Exactly one of sub_work or sub_sub_work must be set."""
    sub_work = models.ForeignKey(
        SubWork, on_delete=models.CASCADE, null=True, blank=True,
        help_text="Set when there is no sub-sub work; leave blank if sub_sub_work is set.",
    )
    sub_sub_work = models.ForeignKey(
        SubSubWork, on_delete=models.CASCADE, null=True, blank=True,
        help_text="Set for sub-sub work level; leave blank to use sub_work only.",
    )
    city = models.ForeignKey('loans.City', on_delete=models.CASCADE)
    unit_price = models.DecimalField(max_digits=20, decimal_places=2)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = [('city', 'sub_work', 'sub_sub_work')]
        verbose_name_plural = "SubWork / SubSubWork unit prices"

    def clean(self):
        from django.core.exceptions import ValidationError
        if bool(self.sub_work_id) == bool(self.sub_sub_work_id):
            raise ValidationError("Set exactly one of Sub work or Sub-sub work.")

    def __str__(self):
        if self.sub_sub_work_id:
            return f"{self.sub_sub_work.name} @ {self.city.name}: {self.unit_price}"
        return f"{self.sub_work} @ {self.city.name}: {self.unit_price}"


# ---------- Building & valuation ----------

class Building(models.Model):
    """One physical building under a loan request."""
    loan_request = models.ForeignKey('loans.LoanRequest', on_delete=models.CASCADE)
    name = models.CharField(max_length=255, help_text="Building label/name")
    construction_type = models.CharField(max_length=100, blank=True)
    floors = models.PositiveIntegerField(null=True, blank=True)
    # Location (woreda) for unit price lookup
    city = models.ForeignKey(
        'loans.City', on_delete=models.SET_NULL, null=True, blank=True,
        help_text="City/Woreda for unit price",
    )
    site_gps_lat = models.DecimalField(
        max_digits=12, decimal_places=8, null=True, blank=True,
        help_text='GPS latitude captured at the building site.',
    )
    site_gps_lon = models.DecimalField(
        max_digits=12, decimal_places=8, null=True, blank=True,
        help_text='GPS longitude captured at the building site.',
    )
    site_gps_accuracy_m = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='GPS accuracy in metres when site was marked.',
    )
    site_captured_at = models.DateTimeField(null=True, blank=True)
    site_gps_weak_acknowledged = models.BooleanField(
        default=False,
        help_text='Officer attested location when GPS was weak or unavailable.',
    )
    site_gps_attestation_note = models.TextField(
        blank=True,
        help_text='Officer explanation when GPS accuracy exceeds policy threshold.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['loan_request', 'name']

    def __str__(self):
        return f"{self.name} ({self.loan_request.loan_request_id})"


class BuildingValuation(models.Model):
    """One valuation row per SubWork or SubSubWork per building. Quantity × Unit price = Total. Exactly one of sub_work or sub_sub_work must be set."""
    building = models.ForeignKey(Building, on_delete=models.CASCADE)
    sub_work = models.ForeignKey(
        SubWork, on_delete=models.CASCADE, null=True, blank=True,
        help_text="Set when there is no sub-sub work; leave blank if sub_sub_work is set.",
    )
    sub_sub_work = models.ForeignKey(
        SubSubWork, on_delete=models.CASCADE, null=True, blank=True,
        help_text="Set for sub-sub work level; leave blank to use sub_work only.",
    )
    quantity = models.DecimalField(max_digits=20, decimal_places=4, default=Decimal('0'))
    unit_price = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0'))
    # Audit: who entered quantity / unit price (optional until roles are defined)
    quantity_entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='collateral_quantity_entries',
    )
    unit_price_entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='collateral_unit_price_entries',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('building', 'sub_work', 'sub_sub_work')]

    def clean(self):
        from django.core.exceptions import ValidationError
        if bool(self.sub_work_id) == bool(self.sub_sub_work_id):
            raise ValidationError("Set exactly one of Sub work or Sub-sub work.")

    @property
    def total(self):
        return (self.quantity or Decimal('0')) * (self.unit_price or Decimal('0'))

    def save(self, *args, **kwargs):
        # Could store total in DB for reporting; for now use property
        super().save(*args, **kwargs)

    def __str__(self):
        item = self.sub_sub_work if self.sub_sub_work_id else self.sub_work
        return f"{self.building.name}: {item} qty={self.quantity}"


class BuildingImage(models.Model):
    """Field photo for a building (mobile upload, optional GPS)."""
    PHOTO_FRONT = 'front'
    PHOTO_SIDE = 'side'
    PHOTO_REAR = 'rear'
    PHOTO_ROOF = 'roof'
    PHOTO_INTERIOR = 'interior'
    PHOTO_OTHER = 'other'
    PHOTO_TYPE_CHOICES = [
        (PHOTO_FRONT, 'Front / facade'),
        (PHOTO_SIDE, 'Side'),
        (PHOTO_REAR, 'Rear'),
        (PHOTO_ROOF, 'Roof'),
        (PHOTO_INTERIOR, 'Interior'),
        (PHOTO_OTHER, 'Other'),
    ]

    building = models.ForeignKey(Building, on_delete=models.CASCADE)
    image = models.ImageField(upload_to='collateral/building/%Y/%m/')
    caption = models.CharField(max_length=255, blank=True)
    photo_type = models.CharField(
        max_length=20, choices=PHOTO_TYPE_CHOICES, default=PHOTO_OTHER, blank=True,
    )
    captured_at = models.DateTimeField(null=True, blank=True)
    gps_lat = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    gps_lon = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    gps_accuracy_m = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
    )
    gps_weak_acknowledged = models.BooleanField(default=False)
    gps_attestation_note = models.TextField(blank=True)
    exif_gps_lat = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    exif_gps_lon = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    browser_vs_exif_distance_m = models.DecimalField(
        max_digits=12, decimal_places=1, null=True, blank=True,
        help_text='Distance between browser capture GPS and photo EXIF GPS (metres).',
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.building.name} image"


class LandValuation(models.Model):
    """Land value for a loan request (optional; one per loan)."""
    loan_request = models.OneToOneField(
        'loans.LoanRequest', on_delete=models.CASCADE, related_name='land_valuation',
    )
    land_size_sqm = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    unit_price_per_sqm = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    site_gps_lat = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    site_gps_lon = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    site_gps_accuracy_m = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    site_captured_at = models.DateTimeField(null=True, blank=True)
    site_gps_weak_acknowledged = models.BooleanField(default=False)
    site_gps_attestation_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total_value(self):
        if self.land_size_sqm is None or self.unit_price_per_sqm is None:
            return None
        return self.land_size_sqm * self.unit_price_per_sqm

    def __str__(self):
        return f"Land {self.loan_request.loan_request_id}"


class LandValuationImage(models.Model):
    """Field photo for land collateral."""
    PHOTO_PLOT = 'plot'
    PHOTO_BOUNDARY = 'boundary'
    PHOTO_TITLE = 'title_deed'
    PHOTO_OTHER = 'other'
    PHOTO_TYPE_CHOICES = [
        (PHOTO_PLOT, 'Plot / overview'),
        (PHOTO_BOUNDARY, 'Boundary / corners'),
        (PHOTO_TITLE, 'Title / certificate'),
        (PHOTO_OTHER, 'Other'),
    ]

    land_valuation = models.ForeignKey(LandValuation, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='collateral/land/%Y/%m/')
    caption = models.CharField(max_length=255, blank=True)
    photo_type = models.CharField(max_length=20, choices=PHOTO_TYPE_CHOICES, default=PHOTO_OTHER, blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    gps_lat = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    gps_lon = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    gps_accuracy_m = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    gps_weak_acknowledged = models.BooleanField(default=False)
    gps_attestation_note = models.TextField(blank=True)
    exif_gps_lat = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    exif_gps_lon = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    browser_vs_exif_distance_m = models.DecimalField(
        max_digits=12, decimal_places=1, null=True, blank=True,
        help_text='Distance between browser capture GPS and photo EXIF GPS (metres).',
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Land photo {self.land_valuation_id}"


# ---------- Other collateral types (Vehicle, Machinery, Equipment, etc.) ----------

class OtherCollateralItem(models.Model):
    """
    Simple collateral item for non-building types (vehicle, machinery, equipment, etc.).
    One or more items per loan; each has name/description and estimated value.
    """
    CONDITION_EXCELLENT = 'excellent'
    CONDITION_GOOD = 'good'
    CONDITION_FAIR = 'fair'
    CONDITION_POOR = 'poor'
    CONDITION_CHOICES = [
        (CONDITION_EXCELLENT, 'Excellent'),
        (CONDITION_GOOD, 'Good'),
        (CONDITION_FAIR, 'Fair'),
        (CONDITION_POOR, 'Poor'),
    ]

    loan_request = models.ForeignKey(
        'loans.LoanRequest', on_delete=models.CASCADE, related_name='other_collateral_items',
    )
    name = models.CharField(max_length=255, help_text="e.g. Toyota Pickup, Tractor, Machinery")
    estimated_value = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0'))
    plate_number = models.CharField(max_length=50, blank=True, help_text='Plate / registration number.')
    chassis_vin = models.CharField(max_length=80, blank=True, help_text='Chassis or VIN.')
    year_made = models.PositiveSmallIntegerField(null=True, blank=True)
    make_model = models.CharField(max_length=255, blank=True)
    odometer_or_hours = models.CharField(
        max_length=50, blank=True, help_text='Odometer (km) or operating hours.',
    )
    condition_grade = models.CharField(max_length=20, choices=CONDITION_CHOICES, blank=True)
    notes = models.TextField(blank=True)
    site_gps_lat = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    site_gps_lon = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    site_gps_accuracy_m = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    site_captured_at = models.DateTimeField(null=True, blank=True)
    site_gps_weak_acknowledged = models.BooleanField(default=False)
    site_gps_attestation_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['loan_request', 'name']

    def __str__(self):
        return f"{self.name} – {self.loan_request.loan_request_id}"


class OtherCollateralItemImage(models.Model):
    """Field photo for vehicle / machinery / equipment collateral."""
    PHOTO_PLATE = 'plate'
    PHOTO_ASSET = 'asset'
    PHOTO_SERIAL = 'serial_label'
    PHOTO_OTHER = 'other'
    PHOTO_TYPE_CHOICES = [
        (PHOTO_PLATE, 'Plate / registration'),
        (PHOTO_ASSET, 'Full asset'),
        (PHOTO_SERIAL, 'Serial / chassis label'),
        (PHOTO_OTHER, 'Other'),
    ]

    item = models.ForeignKey(OtherCollateralItem, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='collateral/other/%Y/%m/')
    caption = models.CharField(max_length=255, blank=True)
    photo_type = models.CharField(max_length=20, choices=PHOTO_TYPE_CHOICES, default=PHOTO_OTHER, blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    gps_lat = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    gps_lon = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    gps_accuracy_m = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    gps_weak_acknowledged = models.BooleanField(default=False)
    gps_attestation_note = models.TextField(blank=True)
    exif_gps_lat = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    exif_gps_lon = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    browser_vs_exif_distance_m = models.DecimalField(
        max_digits=12, decimal_places=1, null=True, blank=True,
        help_text='Distance between browser capture GPS and photo EXIF GPS (metres).',
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.item.name} photo"


class CollateralFieldAuditLog(models.Model):
    """
    Immutable audit trail for on-site collateral actions.
    Supports supervisory review and future AI / provenance analysis.
    """
    EVT_SITE_GPS = 'site_gps_marked'
    EVT_PHOTO_UPLOADED = 'photo_uploaded'
    EVT_PHOTO_DELETED = 'photo_deleted'
    EVT_BOQ_SAVED = 'boq_saved'
    EVT_VALUATION_EDITED = 'valuation_edited'
    EVT_VALUATION_DELETED = 'valuation_deleted'
    EVT_COLLATERAL_SUBMITTED = 'collateral_submitted'
    EVT_WEAK_GPS_ATTESTED = 'weak_gps_attested'
    EVT_UNLOCK_REQUESTED = 'unlock_requested'
    EVT_UNLOCK_APPROVED = 'unlock_approved'
    EVT_UNLOCK_REJECTED = 'unlock_rejected'
    EVT_ENGINEERING_APPROVED = 'engineering_approved'
    EVT_ENGINEERING_RETURNED = 'engineering_returned'
    EVT_DOSSIER_EXPORTED = 'dossier_exported'
    EVENT_CHOICES = [
        (EVT_SITE_GPS, 'Site GPS marked'),
        (EVT_PHOTO_UPLOADED, 'Photo uploaded'),
        (EVT_PHOTO_DELETED, 'Photo deleted'),
        (EVT_BOQ_SAVED, 'BOQ quantities saved'),
        (EVT_VALUATION_EDITED, 'Valuation row edited'),
        (EVT_VALUATION_DELETED, 'Valuation row deleted'),
        (EVT_COLLATERAL_SUBMITTED, 'Collateral submitted'),
        (EVT_WEAK_GPS_ATTESTED, 'Weak GPS attested'),
        (EVT_UNLOCK_REQUESTED, 'Unlock requested'),
        (EVT_UNLOCK_APPROVED, 'Unlock approved'),
        (EVT_UNLOCK_REJECTED, 'Unlock rejected'),
        (EVT_ENGINEERING_APPROVED, 'Engineering approved'),
        (EVT_ENGINEERING_RETURNED, 'Engineering returned'),
        (EVT_DOSSIER_EXPORTED, 'Dossier exported'),
    ]

    loan_request = models.ForeignKey(
        'loans.LoanRequest', on_delete=models.CASCADE, related_name='collateral_audit_logs',
    )
    event_type = models.CharField(max_length=40, choices=EVENT_CHOICES)
    subject_type = models.CharField(max_length=40, blank=True)
    subject_id = models.PositiveIntegerField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='collateral_audit_events',
    )
    performed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-performed_at']
        verbose_name = 'Collateral field audit log'
        verbose_name_plural = 'Collateral field audit logs'

    def __str__(self):
        return f'{self.event_type} — {self.loan_request_id} @ {self.performed_at}'


class CollateralPolicyConfig(models.Model):
    """
    Bank-wide collateral field-work policy. Single row (superadmin settings).
    """
    min_images_per_building = models.PositiveSmallIntegerField(default=5)
    min_images_per_land = models.PositiveSmallIntegerField(default=3)
    min_images_per_other_item = models.PositiveSmallIntegerField(default=3)
    gps_accuracy_weak_threshold_m = models.PositiveIntegerField(
        default=100,
        help_text='Above this GPS accuracy (metres), officer attestation is required.',
    )
    photo_max_distance_from_site_m = models.PositiveIntegerField(
        default=200,
        help_text='Flag photos farther than this from registered site GPS.',
    )
    block_submit_on_far_photos = models.BooleanField(
        default=False,
        help_text='If enabled, photos beyond max distance block collateral submit.',
    )
    block_submit_on_missing_photo_gps = models.BooleanField(
        default=False,
        help_text='If enabled, photos without GPS block collateral submit.',
    )
    min_coverage_ratio = models.DecimalField(
        max_digits=6, decimal_places=4, default=1.0,
        help_text='Minimum collateral value ÷ loan amount (1.0 = 100%). Blocks submit if below.',
    )
    flag_coverage_below_ratio = models.DecimalField(
        max_digits=6, decimal_places=4, default=1.0,
        help_text='Advisory warning when coverage is below this ratio.',
    )
    declared_address_max_distance_from_site_m = models.PositiveIntegerField(
        default=3000,
        help_text='Flag when geocoded declared address is farther than this from field site GPS.',
    )
    block_submit_on_declared_address_mismatch = models.BooleanField(
        default=False,
        help_text='If enabled, large declared-address vs site GPS gap blocks collateral submit.',
    )
    require_movable_photo_types = models.BooleanField(
        default=True,
        help_text='Require plate, full asset, and chassis/serial photos for vehicle/machinery items.',
    )
    exif_gps_mismatch_warn_m = models.PositiveIntegerField(
        default=200,
        help_text='Warn when photo EXIF GPS differs from browser GPS by more than this (metres).',
    )
    block_submit_on_exif_gps_mismatch = models.BooleanField(
        default=False,
        help_text='If enabled, large EXIF vs browser GPS mismatch blocks collateral submit.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Collateral policy config'
        verbose_name_plural = 'Collateral policy config'

    def __str__(self):
        return 'Collateral field-work policy'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        from collateral.policy import clear_policy_cache
        clear_policy_cache()


class CollateralUnlockRequest(models.Model):
    """Supervisor-approved unlock after collateral submit (corrections workflow)."""
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending review'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    loan_request = models.ForeignKey(
        'loans.LoanRequest', on_delete=models.CASCADE, related_name='collateral_unlock_requests',
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='collateral_unlock_requests',
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField(help_text='Why collateral must be corrected.')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='collateral_unlock_reviews',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    previous_submitted_at = models.DateTimeField(null=True, blank=True)
    previous_submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',
    )

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return f'Unlock {self.loan_request_id} ({self.status})'
