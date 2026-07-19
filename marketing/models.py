"""Append-only public marketing lead evidence."""

from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import models


class MarketingLead(models.Model):
    public_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    full_name = models.CharField(max_length=120)
    company_name = models.CharField(max_length=160)
    email = models.EmailField(max_length=254)
    phone = models.CharField(max_length=40, blank=True)
    message = models.TextField(max_length=4000)
    privacy_policy_version = models.CharField(max_length=80)
    privacy_text_sha256 = models.CharField(max_length=64)
    content_sha256 = models.CharField(max_length=64)
    source_path = models.CharField(max_length=300, default="/kontakt/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Marketing leads are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Marketing leads cannot be deleted.")

    def __str__(self):
        return f"{self.company_name} · {self.created_at:%Y-%m-%d}"


__all__ = ["MarketingLead"]
