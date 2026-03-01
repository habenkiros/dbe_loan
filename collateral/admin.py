from django.contrib import admin
from .models import (
    MainWork, SubWork, SubSubWork, SubWorkUnitPrice,
    Building, BuildingValuation, BuildingImage, LandValuation,
    OtherCollateralItem,
)


@admin.register(MainWork)
class MainWorkAdmin(admin.ModelAdmin):
    list_display = ('name', 'order')


@admin.register(SubWork)
class SubWorkAdmin(admin.ModelAdmin):
    list_display = ('name', 'main_work', 'order')
    list_filter = ('main_work',)


@admin.register(SubSubWork)
class SubSubWorkAdmin(admin.ModelAdmin):
    list_display = ('name', 'sub_work', 'unit_measure', 'order')
    list_filter = ('sub_work__main_work', 'sub_work')


@admin.register(SubWorkUnitPrice)
class SubWorkUnitPriceAdmin(admin.ModelAdmin):
    list_display = ('sub_sub_work', 'city', 'unit_price', 'effective_from', 'effective_to')
    list_filter = ('city', 'sub_sub_work__sub_work__main_work')


class BuildingValuationInline(admin.TabularInline):
    model = BuildingValuation
    extra = 0


class BuildingImageInline(admin.TabularInline):
    model = BuildingImage
    extra = 0


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ('name', 'loan_request', 'city', 'construction_type', 'floors')
    list_filter = ('loan_request__branch',)
    inlines = [BuildingValuationInline, BuildingImageInline]


@admin.register(BuildingValuation)
class BuildingValuationAdmin(admin.ModelAdmin):
    list_display = ('building', 'sub_sub_work', 'quantity', 'unit_price', 'total')
    list_filter = ('building__loan_request',)


@admin.register(BuildingImage)
class BuildingImageAdmin(admin.ModelAdmin):
    list_display = ('building', 'caption', 'captured_at', 'gps_lat', 'gps_lon')


@admin.register(LandValuation)
class LandValuationAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'land_size_sqm', 'unit_price_per_sqm', 'total_value')


@admin.register(OtherCollateralItem)
class OtherCollateralItemAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'name', 'estimated_value', 'notes')
    list_filter = ('loan_request__collateral',)
