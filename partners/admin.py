from django.contrib import admin

from partners.models import MarketActor, MarketObservation, MarketPriceBand


@admin.register(MarketActor)
class MarketActorAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'actor_kind', 'product_focus', 'trust_status',
        'branch', 'portal_enabled', 'portal_username', 'is_active',
    )
    list_filter = ('actor_kind', 'product_focus', 'trust_status', 'portal_enabled', 'is_active', 'branch')
    search_fields = ('name', 'phone_number', 'contact_person', 'product_lines', 'portal_username')
    raw_id_fields = ('branch', 'primary_city', 'created_by')


@admin.register(MarketObservation)
class MarketObservationAdmin(admin.ModelAdmin):
    list_display = (
        'observed_at', 'market_actor', 'item_label', 'unit_price_etb',
        'city', 'asset_class', 'status', 'channel',
    )
    list_filter = ('asset_class', 'status', 'channel', 'condition', 'branch')
    search_fields = ('item_label', 'market_actor__name', 'notes')
    date_hierarchy = 'observed_at'
    raw_id_fields = (
        'market_actor', 'branch', 'city', 'sub_work', 'sub_sub_work', 'recorded_by',
    )


@admin.register(MarketPriceBand)
class MarketPriceBandAdmin(admin.ModelAdmin):
    list_display = (
        'city', 'asset_class', 'sample_count', 'median_price',
        'last_observed_at', 'sub_work', 'sub_sub_work', 'item_key',
    )
    list_filter = ('asset_class', 'city')
    search_fields = ('item_key',)
    raw_id_fields = ('city', 'sub_work', 'sub_sub_work')
