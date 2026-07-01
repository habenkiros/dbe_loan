from django.contrib import admin
from .models import (
    MainWork, SubWork, SubSubWork, SubWorkUnitPrice,
    Building, BuildingValuation, BuildingImage, LandValuation, LandValuationImage,
    OtherCollateralItem, OtherCollateralItemImage, CollateralFieldAuditLog,
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
    list_display = ('work_display', 'city', 'unit_price', 'effective_from', 'effective_to')
    list_filter = ('city',)

    def work_display(self, obj):
        return obj.sub_sub_work if obj.sub_sub_work_id else obj.sub_work
    work_display.short_description = 'Sub work / Sub-sub work'


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
    list_display = ('building', 'work_display', 'quantity', 'unit_price', 'total')
    list_filter = ('building__loan_request',)

    def work_display(self, obj):
        return obj.sub_sub_work if obj.sub_sub_work_id else obj.sub_work
    work_display.short_description = 'Sub work / Sub-sub work'


@admin.register(BuildingImage)
class BuildingImageAdmin(admin.ModelAdmin):
    list_display = ('building', 'photo_type', 'caption', 'captured_at', 'gps_lat', 'gps_lon', 'gps_accuracy_m')


@admin.register(LandValuation)
class LandValuationAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'land_size_sqm', 'unit_price_per_sqm', 'site_gps_lat', 'site_gps_lon')


class LandValuationImageInline(admin.TabularInline):
    model = LandValuationImage
    extra = 0


LandValuationAdmin.inlines = [LandValuationImageInline]


@admin.register(OtherCollateralItem)
class OtherCollateralItemAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'name', 'estimated_value', 'site_gps_lat')
    list_filter = ('loan_request__collateral',)


class OtherCollateralItemImageInline(admin.TabularInline):
    model = OtherCollateralItemImage
    extra = 0


OtherCollateralItemAdmin.inlines = [OtherCollateralItemImageInline]


@admin.register(CollateralFieldAuditLog)
class CollateralFieldAuditLogAdmin(admin.ModelAdmin):
    list_display = ('performed_at', 'loan_request', 'event_type', 'subject_type', 'subject_id', 'performed_by')
    list_filter = ('event_type', 'subject_type')
    search_fields = ('loan_request__loan_request_id', 'performed_by__username')
    readonly_fields = ('loan_request', 'event_type', 'subject_type', 'subject_id', 'payload', 'performed_by', 'performed_at')
    date_hierarchy = 'performed_at'
