"""Enforce seat limits at the actual membership activation boundary."""

from django.db.models.signals import pre_save
from django.dispatch import receiver

from tenants.models import TenantMembership

from .services import ensure_active_seat_available


@receiver(
    pre_save,
    sender=TenantMembership,
    dispatch_uid="billing.enforce_membership_activation_seat_limit",
)
def enforce_membership_activation_seat_limit(sender, instance, **kwargs):
    if not instance.is_active or not instance.tenant_id:
        return
    if instance.pk:
        was_active = sender.objects.filter(pk=instance.pk, is_active=True).exists()
        if was_active:
            return
    ensure_active_seat_available(tenant=instance.tenant, membership=instance)
