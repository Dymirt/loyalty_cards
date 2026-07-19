from django.contrib import admin

from .models import (
    BillingPeriod,
    CardPack,
    CardPackAllocation,
    CardPriceTier,
    EntitlementPolicy,
    Plan,
    PlanVersion,
    PriceBook,
    PriceBookVersion,
    PrintQuoteConsumption,
    Quote,
    QuoteLine,
    TenantSubscription,
    UsageEvent,
)


class NoDeleteAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False


class AppendOnlyAdmin(NoDeleteAdmin):
    def has_change_permission(self, request, obj=None):
        return obj is None


@admin.register(PlanVersion)
class PlanVersionAdmin(NoDeleteAdmin):
    list_display = ("plan", "version", "billing_interval", "recurring_amount", "currency", "published_at")
    list_filter = ("plan", "published_at", "currency")

    def has_change_permission(self, request, obj=None):
        return obj is None or not obj.published_at


@admin.register(PriceBookVersion)
class PriceBookVersionAdmin(NoDeleteAdmin):
    list_display = ("price_book", "version", "currency", "shipping_amount", "published_at")
    list_filter = ("price_book", "published_at", "currency")

    def has_change_permission(self, request, obj=None):
        return obj is None or not obj.published_at


@admin.register(UsageEvent)
class UsageEventAdmin(AppendOnlyAdmin):
    list_display = ("tenant", "kind", "quantity", "idempotency_key", "occurred_at")
    list_filter = ("tenant", "kind")
    search_fields = ("idempotency_key", "reference_id")


@admin.register(Quote)
class QuoteAdmin(NoDeleteAdmin):
    list_display = ("id", "tenant", "status", "quantity", "total_amount", "currency", "created_at")
    list_filter = ("tenant", "status", "currency")

    def has_change_permission(self, request, obj=None):
        return obj is None or obj.status != Quote.Status.ACCEPTED


for model in (
    Plan,
    EntitlementPolicy,
    TenantSubscription,
    BillingPeriod,
    PriceBook,
    CardPriceTier,
    CardPack,
):
    admin.site.register(model, NoDeleteAdmin)

for model in (QuoteLine, CardPackAllocation, PrintQuoteConsumption):
    admin.site.register(model, AppendOnlyAdmin)
