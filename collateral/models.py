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


# ---------- Unit price per woreda (City): per SubSubWork ----------

class SubWorkUnitPrice(models.Model):
    """Unit price per SubSubWork per City (woreda). Set by engineering team."""
    sub_sub_work = models.ForeignKey(SubSubWork, on_delete=models.CASCADE)
    city = models.ForeignKey('loans.City', on_delete=models.CASCADE)
    unit_price = models.DecimalField(max_digits=20, decimal_places=2)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = [('sub_sub_work', 'city')]
        verbose_name_plural = "SubSubWork unit prices"

    def __str__(self):
        return f"{self.sub_sub_work.name} @ {self.city.name}: {self.unit_price}"


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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['loan_request', 'name']

    def __str__(self):
        return f"{self.name} ({self.loan_request.loan_request_id})"


class BuildingValuation(models.Model):
    """One valuation row per SubSubWork per building. Quantity × Unit price = Total."""
    building = models.ForeignKey(Building, on_delete=models.CASCADE)
    sub_sub_work = models.ForeignKey(SubSubWork, on_delete=models.CASCADE)
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
        unique_together = [('building', 'sub_sub_work')]

    @property
    def total(self):
        return (self.quantity or Decimal('0')) * (self.unit_price or Decimal('0'))

    def save(self, *args, **kwargs):
        # Could store total in DB for reporting; for now use property
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.building.name}: {self.sub_sub_work} qty={self.quantity}"


class BuildingImage(models.Model):
    """Field photo for a building (mobile upload, optional GPS)."""
    building = models.ForeignKey(Building, on_delete=models.CASCADE)
    image = models.ImageField(upload_to='collateral/building/%Y/%m/')
    caption = models.CharField(max_length=255, blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    gps_lat = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    gps_lon = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total_value(self):
        if self.land_size_sqm is None or self.unit_price_per_sqm is None:
            return None
        return self.land_size_sqm * self.unit_price_per_sqm

    def __str__(self):
        return f"Land {self.loan_request.loan_request_id}"


# ---------- Other collateral types (Vehicle, Machinery, Equipment, etc.) ----------

class OtherCollateralItem(models.Model):
    """
    Simple collateral item for non-building types (vehicle, machinery, equipment, etc.).
    One or more items per loan; each has name/description and estimated value.
    """
    loan_request = models.ForeignKey(
        'loans.LoanRequest', on_delete=models.CASCADE, related_name='other_collateral_items',
    )
    name = models.CharField(max_length=255, help_text="e.g. Toyota Pickup, Tractor, Machinery")
    estimated_value = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0'))
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['loan_request', 'name']

    def __str__(self):
        return f"{self.name} – {self.loan_request.loan_request_id}"
