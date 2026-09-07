# loans/admin.py

from django import forms
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse
from .models import (
    Zone, Branch, Department, LoanCategory, FinancingFund, ProjectProfile, ProjectSourceUseLine,
    ProjectCashflowYear, ProjectTechnicalReview, PfiInstitutionProfile, PfiUtilizationReport,
    FundFileTag, LeaseAssetProfile, IjarahRentLine, ShariaReview,
    MurabahaContract, IdeaProfile, CapTableEntry, ConsumerProfile, AppraisalCrmRound,
    RehabCase, RehabEvent, InsurancePolicy, RevaluationDiary, LoanAppeal,
    CreditDeskScreening, ProductFamilyPolicy,
    KycIdentityCase, KycParty,
    CollateralType,
    LoanApplicationDocumentType, LoanCategoryDocumentRequirement,
    LoanRequestDocument, LoanDocumentRequest, LoanAppraisal,
    LoanRequest, CustomUser, CollateralEstimationConfig,
    LoanRequestBasicInfo, AppraisalCreditHistoryEntry, AppraisalQualitativeFactor,
    AppraisalAmortizationEntry, LoanCommitteeVote,
    ApprovalCommitteeLevel, ApprovalCommitteeMemberRule, LoanApprovalLevelProgress,
    BranchCommitteeOverride, BranchCommitteeMemberRule, LoanNotification,
)


class LoanRequestDocumentInline(admin.TabularInline):
    model = LoanRequestDocument
    extra = 0
    readonly_fields = (
        'uploaded_at', 'auth_status', 'file_sha256', 'file_size', 'automated_checks',
        'quality_score', 'authenticity_score', 'perceptual_hash',
    )
    fields = (
        'document_type', 'file', 'auth_status', 'uploaded_at',
        'file_size', 'file_sha256',
    )


@admin.register(LoanRequest)
class LoanRequestAdmin(admin.ModelAdmin):
    list_display = (
        'loan_request_id', 'applicant_name', 'phone_number', 'category', 'financing_fund', 'collateral',
        'amount_requested', 'branch', 'status', 'committee_status', 'queue_approved', 'date_requested',
    )
    list_filter = ('status', 'committee_status', 'branch', 'category', 'financing_fund', 'collateral', 'queue_approved')
    search_fields = ('loan_request_id', 'applicant_name', 'phone_number')
    readonly_fields = ('loan_request_id',)
    list_per_page = 10
    inlines = [LoanRequestDocumentInline]

    def has_add_permission(self, request):
        """Loan requests are created from the main app, not from admin."""
        return False


admin.site.register(Zone)


class BranchCommitteeMemberRuleInline(admin.TabularInline):
    model = BranchCommitteeMemberRule
    extra = 1
    fields = ('participant_type', 'role', 'user', 'label', 'is_active')


class BranchCommitteeOverrideInline(admin.StackedInline):
    model = BranchCommitteeOverride
    extra = 0
    max_num = 1
    fields = ('level', 'is_active', 'min_approvals_required', 'min_declines_required', 'notes')
    show_change_link = True
    verbose_name = 'Branch committee override'
    verbose_name_plural = 'Branch committee override (optional — replaces global branch rules for this branch)'


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'district', 'has_committee_override')
    list_filter = ('district',)
    search_fields = ('name',)
    inlines = [BranchCommitteeOverrideInline]

    @admin.display(boolean=True, description='Custom committee')
    def has_committee_override(self, obj):
        return obj.committee_overrides.filter(is_active=True).exists()


@admin.register(BranchCommitteeOverride)
class BranchCommitteeOverrideAdmin(admin.ModelAdmin):
    list_display = ('branch', 'level', 'is_active', 'min_approvals_required', 'min_declines_required', 'active_rules_count')
    list_filter = ('is_active', 'branch__district')
    search_fields = ('branch__name', 'notes')
    inlines = [BranchCommitteeMemberRuleInline]
    fieldsets = (
        (None, {
            'fields': ('branch', 'level', 'is_active', 'notes'),
            'description': (
                'Use this when a branch needs a different committee than the global default '
                '(e.g. Branch A: manager + accountant only). Member rules below replace global '
                'branch-level rules for loans from this branch.'
            ),
        }),
        ('Vote thresholds (optional)', {
            'fields': ('min_approvals_required', 'min_declines_required'),
        }),
    )

    @admin.display(description='Active rules')
    def active_rules_count(self, obj):
        if not obj.pk:
            return '—'
        return obj.member_rules.filter(is_active=True).count()


class LoanCategoryDocumentRequirementInline(admin.TabularInline):
    model = LoanCategoryDocumentRequirement
    extra = 0
    fields = ('document_type', 'is_required', 'order')


@admin.register(LoanCategory)
class LoanCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'product_family', 'appraisal_mode', 'requires_collateral')
    list_filter = ('product_family', 'appraisal_mode', 'requires_collateral')
    inlines = [LoanCategoryDocumentRequirementInline]


@admin.register(ProductFamilyPolicy)
class ProductFamilyPolicyAdmin(admin.ModelAdmin):
    list_display = ('family', 'default_appraisal_mode', 'requires_collateral')
    list_filter = ('requires_collateral', 'default_appraisal_mode')
    filter_horizontal = ('default_collateral',)


@admin.register(FinancingFund)
class FinancingFundAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'kind', 'source_name', 'envelope_amount', 'is_active')
    list_filter = ('kind', 'is_active')
    search_fields = ('code', 'name', 'source_name')


class PfiUtilizationReportInline(admin.TabularInline):
    model = PfiUtilizationReport
    extra = 0


@admin.register(PfiInstitutionProfile)
class PfiInstitutionProfileAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'institution_name', 'kind', 'facility_amount', 'par90_pct')
    list_filter = ('kind', 'facility_purpose')
    search_fields = ('institution_name', 'loan_request__loan_request_id')
    inlines = [PfiUtilizationReportInline]


@admin.register(FundFileTag)
class FundFileTagAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'region', 'women_owned', 'youth_owned', 'climate_tagged')


class IjarahRentLineInline(admin.TabularInline):
    model = IjarahRentLine
    extra = 0


@admin.register(LeaseAssetProfile)
class LeaseAssetProfileAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'supplier_name', 'serial_number', 'asset_price', 'asset_status')
    list_filter = ('asset_status', 'is_new_goods')
    search_fields = ('supplier_name', 'serial_number', 'loan_request__loan_request_id')
    inlines = [IjarahRentLineInline]


@admin.register(ShariaReview)
class ShariaReviewAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'kind', 'status', 'reviewed_at')
    list_filter = ('kind', 'status')


@admin.register(MurabahaContract)
class MurabahaContractAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'goods_description', 'cost_price', 'markup_pct', 'scope')
    list_filter = ('scope',)


class CapTableEntryInline(admin.TabularInline):
    model = CapTableEntry
    extra = 0


@admin.register(IdeaProfile)
class IdeaProfileAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'venture_name', 'founded_year', 'proposed_dbe_share_pct')
    inlines = [CapTableEntryInline]


@admin.register(ConsumerProfile)
class ConsumerProfileAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'purpose', 'employer_name', 'monthly_salary')


@admin.register(AppraisalCrmRound)
class AppraisalCrmRoundAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'version', 'status', 'sent_at', 'crm_at')
    list_filter = ('status',)


class RehabEventInline(admin.TabularInline):
    model = RehabEvent
    extra = 0
    readonly_fields = ('from_stage', 'to_stage', 'note', 'recorded_by', 'created_at')


@admin.register(RehabCase)
class RehabCaseAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'stage', 'updated_at')
    list_filter = ('stage',)
    inlines = [RehabEventInline]


@admin.register(InsurancePolicy)
class InsurancePolicyAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'kind', 'insurer', 'expires_on', 'dbe_co_beneficiary')
    list_filter = ('kind', 'dbe_co_beneficiary')


@admin.register(RevaluationDiary)
class RevaluationDiaryAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'due_on', 'completed_on')


@admin.register(LoanAppeal)
class LoanAppealAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'level', 'status', 'filed_at')
    list_filter = ('level', 'status')


class ProjectSourceUseLineInline(admin.TabularInline):
    model = ProjectSourceUseLine
    extra = 0


class ProjectCashflowYearInline(admin.TabularInline):
    model = ProjectCashflowYear
    extra = 0


class ProjectTechnicalReviewInline(admin.TabularInline):
    model = ProjectTechnicalReview
    extra = 0


@admin.register(ProjectProfile)
class ProjectProfileAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'project_title', 'sector', 'total_project_cost')
    list_filter = ('sector',)
    search_fields = ('project_title', 'loan_request__loan_request_id')
    inlines = [ProjectSourceUseLineInline, ProjectCashflowYearInline, ProjectTechnicalReviewInline]


@admin.register(LoanCategoryDocumentRequirement)
class LoanCategoryDocumentRequirementAdmin(admin.ModelAdmin):
    list_display = ('category', 'document_type', 'is_required', 'order')
    list_filter = ('category', 'is_required')
    search_fields = ('category__name', 'document_type__name')
    list_editable = ('is_required', 'order')
    ordering = ('category__name', 'order', 'document_type__name')


admin.site.register(CollateralType)


@admin.register(LoanApplicationDocumentType)
class LoanApplicationDocumentTypeAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'order', 'is_required', 'max_file_size_mb',
        'require_officer_verification', 'enable_ocr_match',
    )
    list_editable = ('order', 'is_required')
    ordering = ['order', 'name']
    fieldsets = (
        (None, {'fields': ('name', 'order', 'is_required', 'auth_notes')}),
        ('Upload rules', {'fields': ('allowed_extensions', 'max_file_size_mb')}),
        ('Reference sample (Path B)', {
            'fields': (
                'reference_sample', 'use_reference_sample_validation',
                'reference_min_similarity', 'reference_sample_profile',
                'reference_sample_analyzed_at',
            ),
        }),
        ('Content validation', {
            'fields': (
                'content_validation_sample', 'content_validation_min_matches',
                'content_validation_strict', 'content_extraction_mappings',
            ),
        }),
        ('Authentication checks', {
            'fields': (
                'require_officer_verification', 'enable_ocr_match',
                'enable_llm_check', 'enable_external_id',
            ),
        }),
    )


@admin.register(LoanRequestDocument)
class LoanRequestDocumentAdmin(admin.ModelAdmin):
    list_display = (
        'loan_request', 'document_type', 'auth_status', 'original_filename',
        'file_size', 'uploaded_at', 'uploaded_by',
    )
    list_filter = ('auth_status', 'document_type')
    search_fields = ('loan_request__loan_request_id', 'original_filename', 'file_sha256')
    readonly_fields = ('uploaded_at', 'authenticated_at', 'automated_checks', 'file_sha256', 'quality_score', 'authenticity_score', 'perceptual_hash')


@admin.register(LoanDocumentRequest)
class LoanDocumentRequestAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'document_type', 'requested_by', 'requested_at')
    list_filter = ('document_type',)
    search_fields = ('loan_request__loan_request_id',)
    readonly_fields = ('requested_at',)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'key', 'is_active', 'sort_order')
    list_filter = ('is_active',)
    search_fields = ('name', 'key')
    ordering = ('sort_order', 'name')


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


class ApprovalCommitteeMemberRuleInline(admin.TabularInline):
    model = ApprovalCommitteeMemberRule
    extra = 1
    fields = ('participant_type', 'role', 'user', 'label', 'is_active')
    verbose_name = 'Committee member rule'
    verbose_name_plural = 'Who may vote at this level (configure once; applied per loan automatically)'

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)

        class RuleForm(formset.form):
            def clean(self):
                cleaned = super().clean()
                if self.cleaned_data.get('DELETE'):
                    return cleaned
                ptype = cleaned.get('participant_type')
                role = cleaned.get('role')
                user = cleaned.get('user')
                if ptype == ApprovalCommitteeMemberRule.PARTICIPANT_ROLE:
                    if not role:
                        raise forms.ValidationError('Select a role when participant type is “Anyone with role”.')
                    cleaned['user'] = None
                elif ptype == ApprovalCommitteeMemberRule.PARTICIPANT_USER:
                    if not user:
                        raise forms.ValidationError('Select a user when participant type is “Specific user”.')
                    cleaned['role'] = ''
                return cleaned

        formset.form = RuleForm
        return formset


@admin.register(ApprovalCommitteeLevel)
class ApprovalCommitteeLevelAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'key', 'voter_scope', 'sequence_order', 'is_active',
        'active_member_rules_count',
        'min_approvals_required', 'min_declines_required',
        'min_loan_amount', 'max_loan_amount',
    )
    list_editable = ('sequence_order', 'is_active')
    list_filter = ('is_active', 'voter_scope')
    search_fields = ('name', 'key')
    inlines = [ApprovalCommitteeMemberRuleInline]
    readonly_fields = ('member_scope_description',)
    fieldsets = (
        (None, {
            'fields': ('key', 'name', 'voter_scope', 'sequence_order', 'is_active', 'member_scope_description'),
            'description': (
                'Add any number of levels. <strong>Voter scope</strong> controls how role rules resolve: '
                'branch / district (scoped to the loan) or organization-wide (roles or named users).'
            ),
        }),
        ('Vote thresholds', {
            'fields': ('min_approvals_required', 'min_declines_required'),
            'description': 'Example: 2 approvals required = at least 2 eligible members must vote approve.',
        }),
        ('Amount routing (optional)', {
            'fields': ('min_loan_amount', 'max_loan_amount'),
            'description': (
                'Uses <strong>Sheet 6 recommended amount</strong> when set, otherwise requested amount. '
                'Leave both blank to always include this level.'
            ),
        }),
    )

    @admin.display(description='Member rules')
    def active_member_rules_count(self, obj):
        if not obj.pk:
            return '—'
        n = obj.member_rules.filter(is_active=True).count()
        return n


@admin.register(LoanApprovalLevelProgress)
class LoanApprovalLevelProgressAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'level', 'status', 'started_at', 'completed_at')
    list_filter = ('status', 'level')


@admin.register(LoanNotification)
class LoanNotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'kind', 'loan_request', 'is_read', 'created_at')
    list_filter = ('kind', 'is_read')
    search_fields = ('title', 'user__username', 'loan_request__loan_request_id')
    readonly_fields = ('created_at',)


@admin.register(LoanCommitteeVote)
class LoanCommitteeVoteAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'member', 'vote', 'amount_supported', 'voted_at')
    list_filter = ('vote',)
    search_fields = ('loan_request__loan_request_id', 'member__username')
    readonly_fields = ('voted_at',)


@admin.register(CreditDeskScreening)
class CreditDeskScreeningAdmin(admin.ModelAdmin):
    list_display = ('loan_request', 'desk', 'status', 'reviewed_at')
    list_filter = ('desk', 'status')
    search_fields = ('loan_request__loan_request_id',)


class KycPartyInline(admin.TabularInline):
    model = KycParty
    extra = 0
    fields = (
        'role', 'legal_name_en', 'identity_kind', 'fan', 'tin', 'id_number',
        'verify_status', 'biometric_status',
    )
    readonly_fields = ('verify_status', 'biometric_status')


@admin.register(KycIdentityCase)
class KycIdentityCaseAdmin(admin.ModelAdmin):
    list_display = ('id', 'loan_request', 'band', 'score', 'updated_at')
    list_filter = ('band',)
    search_fields = ('loan_request__loan_request_id',)
    readonly_fields = ('blockers', 'findings', 'updated_at')
    inlines = [KycPartyInline]
