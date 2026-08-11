from django.contrib import admin

from applicant_portal.models import (
    ApplicantAccount,
    ApplicantAuthEvent,
    ApplicantIpThrottle,
    ApplicantMessageOutbox,
    ApplicantNotification,
    ApplicantPasswordReset,
    ApplicantPortalSettings,
    OnlineApplication,
    OnlineApplicationDocument,
)


class OnlineApplicationDocumentInline(admin.TabularInline):
    model = OnlineApplicationDocument
    extra = 0
    readonly_fields = ('uploaded_at', 'file_size', 'original_filename')


@admin.register(ApplicantPortalSettings)
class ApplicantPortalSettingsAdmin(admin.ModelAdmin):
    list_display = (
        'enabled', 'processing_fee_etb', 'min_password_length',
        'max_failed_logins', 'lockout_minutes', 'session_idle_minutes', 'updated_at',
    )
    fieldsets = (
        ('Portal', {
            'fields': ('enabled', 'processing_fee_etb'),
        }),
        ('Password policy', {
            'fields': (
                'min_password_length',
                'require_uppercase',
                'require_lowercase',
                'require_digit',
                'require_special',
            ),
        }),
        ('Login security', {
            'fields': (
                'max_failed_logins',
                'lockout_minutes',
                'register_rate_limit_per_hour',
                'session_idle_minutes',
            ),
        }),
    )

    def has_add_permission(self, request):
        return not ApplicantPortalSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ApplicantAccount)
class ApplicantAccountAdmin(admin.ModelAdmin):
    list_display = (
        'full_name', 'phone_number', 'customer_number', 'is_active', 'failed_login_attempts',
        'locked_until', 'last_login_at', 'last_login_ip', 'created_at',
    )
    list_filter = ('is_active',)
    search_fields = ('full_name', 'phone_number', 'customer_number')
    readonly_fields = (
        'public_id', 'created_at', 'updated_at', 'last_login_at',
        'password_hash', 'password_changed_at', 'last_login_ip',
    )
    actions = ['unlock_accounts']

    @admin.action(description='Clear lockout and failed attempts')
    def unlock_accounts(self, request, queryset):
        queryset.update(failed_login_attempts=0, locked_until=None)


@admin.register(OnlineApplication)
class OnlineApplicationAdmin(admin.ModelAdmin):
    list_display = (
        'public_id', 'applicant_name', 'category', 'branch', 'status',
        'payment_status', 'queue_id', 'updated_at',
    )
    list_filter = ('status', 'payment_status', 'category')
    search_fields = ('applicant_name', 'phone_number', 'queue_id', 'public_id')
    readonly_fields = (
        'public_id', 'created_at', 'updated_at', 'submitted_at',
        'payment_paid_at', 'loan_request', 'queue_id',
    )
    inlines = [OnlineApplicationDocumentInline]


@admin.register(ApplicantAuthEvent)
class ApplicantAuthEventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'phone_number', 'ip_address', 'created_at')
    list_filter = ('event_type',)
    search_fields = ('phone_number', 'ip_address')
    readonly_fields = (
        'event_type', 'account', 'phone_number', 'ip_address',
        'user_agent', 'detail', 'created_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ApplicantIpThrottle)
class ApplicantIpThrottleAdmin(admin.ModelAdmin):
    list_display = (
        'ip_address', 'failed_login_attempts', 'lockout_until',
        'register_count', 'updated_at',
    )
    search_fields = ('ip_address',)
    actions = ['clear_throttle']

    @admin.action(description='Clear throttle / lockout')
    def clear_throttle(self, request, queryset):
        queryset.update(
            failed_login_attempts=0,
            lockout_until=None,
            register_count=0,
            register_window_start=None,
        )


@admin.register(ApplicantNotification)
class ApplicantNotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'account', 'kind', 'is_read', 'created_at')
    list_filter = ('kind', 'is_read')


@admin.register(ApplicantMessageOutbox)
class ApplicantMessageOutboxAdmin(admin.ModelAdmin):
    list_display = ('channel', 'recipient', 'subject', 'sent', 'created_at')
    list_filter = ('channel', 'sent')
    readonly_fields = ('created_at',)


@admin.register(ApplicantPasswordReset)
class ApplicantPasswordResetAdmin(admin.ModelAdmin):
    list_display = ('account', 'expires_at', 'used_at', 'created_at')
    readonly_fields = ('code_hash', 'created_at')
