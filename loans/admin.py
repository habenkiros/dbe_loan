# loans/admin.py

from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse
from .models import (
    Zone, Branch, LoanCategory, CollateralType,
    LoanApplicationDocumentType, LoanRequestDocument, LoanDocumentRequest, LoanAppraisal,
    LoanRequest, CustomUser, CollateralEstimationConfig,
    LoanRequestBasicInfo, AppraisalCreditHistoryEntry, AppraisalQualitativeFactor,
    AppraisalAmortizationEntry,
)


class LoanRequestDocumentInline(admin.TabularInline):
    model = LoanRequestDocument
    extra = 0
    readonly_fields = ('uploaded_at',)


@admin.register(LoanRequest)
class LoanRequestAdmin(admin.ModelAdmin):
    list_display = (
        'loan_request_id', 'applicant_name', 'phone_number', 'category', 'collateral',
        'amount_requested', 'branch', 'status', 'queue_approved', 'date_requested',
    )
    list_filter = ('status', 'branch', 'category', 'collateral', 'queue_approved')
    search_fields = ('loan_request_id', 'applicant_name', 'phone_number')
    readonly_fields = ('loan_request_id',)
    list_per_page = 20
    inlines = [LoanRequestDocumentInline]

    def has_add_permission(self, request):
        """Loan requests are created from the main app, not from admin."""
        return False


admin.site.register(Zone)
admin.site.register(Branch)
admin.site.register(LoanCategory)
admin.site.register(CollateralType)


@admin.register(LoanApplicationDocumentType)
class LoanApplicationDocumentTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'order', 'is_required')
    list_editable = ('order', 'is_required')
    ordering = ['order', 'name']


admin.site.register(LoanRequestDocument)


@admin.register(LoanDocumentRequest)
class LoanDocumentRequestAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'document_type', 'requested_by', 'requested_at')
    list_filter = ('document_type',)
    search_fields = ('loan_request__loan_request_id',)
    readonly_fields = ('requested_at',)


admin.site.register(CustomUser)
admin.site.register(LoanRequestBasicInfo)


class AppraisalCreditHistoryEntryInline(admin.TabularInline):
    model = AppraisalCreditHistoryEntry
    extra = 0


class AppraisalQualitativeFactorInline(admin.TabularInline):
    model = AppraisalQualitativeFactor
    extra = 0
    max_num = 10


class AppraisalAmortizationEntryInline(admin.TabularInline):
    model = AppraisalAmortizationEntry
    extra = 0


@admin.register(LoanAppraisal)
class LoanAppraisalAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'created_by', 'qualitative_total_score', 'qualitative_passed', 'es_eligibility_decision', 'recommendation', 'created_at')
    inlines = [AppraisalCreditHistoryEntryInline, AppraisalQualitativeFactorInline, AppraisalAmortizationEntryInline]


@admin.register(CollateralEstimationConfig)
class CollateralEstimationConfigAdmin(admin.ModelAdmin):
    """Singleton: one row. Who does collateral estimation – loan officer or engineering team."""
    list_display = ('mode',)
    fields = ('mode',)

    def has_add_permission(self, request):
        return not CollateralEstimationConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = CollateralEstimationConfig.objects.first()
        if obj:
            return redirect(reverse('admin:loans_collateralestimationconfig_change', args=[obj.pk]))
        return super().changelist_view(request, extra_context)
