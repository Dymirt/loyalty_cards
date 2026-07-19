"""Django forms for tenant print requests and platform fulfillment."""

from uuid import uuid4

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from billing.models import Quote
from card_artwork.models import CardDesign
from cards.models import CardBatch
from tenants.forms import style_portal_form
from tenants.models import Tenant

from .models import FulfillmentEvent, PrintRequest
from .services import FULFILLMENT_TRANSITIONS


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_portal_form(self)


class PrintRequestForm(StyledFormMixin, forms.Form):
    design = forms.ModelChoiceField(
        queryset=CardDesign.objects.none(),
        label=_("Opublikowany projekt"),
    )
    quote = forms.ModelChoiceField(
        queryset=Quote.objects.none(),
        label=_("Zaakceptowana kalkulacja"),
    )
    proof_approved = forms.BooleanField(
        label=_("Akceptuję dokładnie ten zamrożony projekt i jego sumę kontrolną"),
    )
    delivery_name = forms.CharField(max_length=160, label=_("Odbiorca"))
    delivery_address_line1 = forms.CharField(max_length=240, label=_("Adres"))
    delivery_address_line2 = forms.CharField(
        max_length=240,
        required=False,
        label=_("Druga linia adresu"),
    )
    delivery_postal_code = forms.CharField(max_length=24, label=_("Kod pocztowy"))
    delivery_city = forms.CharField(max_length=120, label=_("Miasto"))
    delivery_country = forms.RegexField(
        regex=r"^[A-Za-z]{2}$",
        initial="PL",
        label=_("Kod kraju"),
    )
    notes = forms.CharField(
        required=False,
        label=_("Uwagi dla operatora"),
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    idempotency_key = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, tenant, **kwargs):
        self.tenant = tenant
        kwargs.setdefault("initial", {})
        kwargs["initial"].setdefault("idempotency_key", f"print-request:{uuid4()}")
        kwargs["initial"].setdefault("delivery_name", tenant.name)
        super().__init__(*args, **kwargs)
        self.fields["design"].queryset = CardDesign.objects.filter(
            tenant=tenant,
            artifacts__kind__in=("proof_front", "proof_back"),
        ).distinct()
        self.fields["quote"].queryset = Quote.objects.filter(
            tenant=tenant,
            status=Quote.Status.ACCEPTED,
            print_request__isnull=True,
        ).order_by("-accepted_at", "-pk")

    def clean_delivery_country(self):
        return self.cleaned_data["delivery_country"].upper()

    def clean(self):
        cleaned = super().clean()
        quote = cleaned.get("quote")
        if quote and quote.tenant_id != self.tenant.pk:
            self.add_error("quote", _("Kalkulacja należy do innej firmy."))
        design = cleaned.get("design")
        if design and design.tenant_id != self.tenant.pk:
            self.add_error("design", _("Projekt należy do innej firmy."))
        return cleaned


class PlatformQueueFilterForm(StyledFormMixin, forms.Form):
    tenant = forms.ModelChoiceField(
        queryset=Tenant.objects.filter(is_active=True),
        required=False,
        label=_("Firma"),
    )
    status = forms.ChoiceField(
        choices=(("", _("Wszystkie statusy")), *PrintRequest.Status.choices),
        required=False,
        label=_("Status"),
    )


class OperatorReasonForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(
        required=False,
        label=_("Notatka operatora"),
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class RequiredReasonForm(OperatorReasonForm):
    reason = forms.CharField(
        label=_("Powód"),
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class FulfillmentForm(StyledFormMixin, forms.Form):
    event_type = forms.ChoiceField(label=_("Następny etap"))
    occurred_at = forms.DateTimeField(
        label=_("Data i czas"),
        initial=timezone.now,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )
    reference = forms.CharField(
        max_length=160,
        required=False,
        label=_("Numer przesyłki / referencja"),
    )
    notes = forms.CharField(
        required=False,
        label=_("Uwagi"),
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    idempotency_key = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, current_status, **kwargs):
        kwargs.setdefault("initial", {})
        kwargs["initial"].setdefault("idempotency_key", f"fulfillment:{uuid4()}")
        super().__init__(*args, **kwargs)
        choices = [
            (event_type, FulfillmentEvent.Kind(event_type).label)
            for event_type, (source, _target) in FULFILLMENT_TRANSITIONS.items()
            if source == current_status
        ]
        self.fields["event_type"].choices = choices
        if choices:
            self.fields["event_type"].initial = choices[0][0]


class CorrectionForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(
        label=_("Powód korekty"),
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    reference = forms.CharField(
        max_length=160, required=False, label=_("Referencja")
    )
    notes = forms.CharField(
        required=False,
        label=_("Wyjaśnienie"),
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    idempotency_key = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("initial", {})
        kwargs["initial"].setdefault("idempotency_key", f"correction:{uuid4()}")
        super().__init__(*args, **kwargs)


class LegacyPreviewForm(StyledFormMixin, forms.Form):
    tenant = forms.ModelChoiceField(
        queryset=Tenant.objects.filter(is_active=True),
        label=_("Firma"),
    )
    batch = forms.ModelChoiceField(
        queryset=CardBatch.objects.filter(cards__is_legacy=True).distinct(),
        label=_("Historyczna partia"),
    )
    start_number = forms.IntegerField(min_value=1, label=_("Pierwszy numer"))
    end_number = forms.IntegerField(min_value=1, label=_("Ostatni numer"))

    def clean(self):
        cleaned = super().clean()
        tenant, batch = cleaned.get("tenant"), cleaned.get("batch")
        if tenant and batch and batch.tenant_id != tenant.pk:
            self.add_error("batch", _("Partia należy do innej firmy."))
        if (
            cleaned.get("start_number")
            and cleaned.get("end_number")
            and cleaned["start_number"] > cleaned["end_number"]
        ):
            self.add_error("end_number", _("Ostatni numer nie może być mniejszy."))
        return cleaned


class LegacyConfirmForm(StyledFormMixin, forms.Form):
    tenant_id = forms.IntegerField(widget=forms.HiddenInput)
    batch_id = forms.IntegerField(widget=forms.HiddenInput)
    start_number = forms.IntegerField(widget=forms.HiddenInput)
    end_number = forms.IntegerField(widget=forms.HiddenInput)
    expected_count = forms.IntegerField(widget=forms.HiddenInput)
    confirmation_count = forms.IntegerField(
        min_value=1,
        label=_("Wpisz dokładną liczbę kart z podglądu"),
    )
    event_types = forms.MultipleChoiceField(
        choices=(
            (FulfillmentEvent.Kind.PRINTED, _("Wydrukowane")),
            (FulfillmentEvent.Kind.DELIVERED, _("Dostarczone")),
        ),
        widget=forms.CheckboxSelectMultiple,
        label=_("Dopisz zdarzenia"),
    )
    occurred_at = forms.DateTimeField(
        initial=timezone.now,
        label=_("Data zdarzenia/dostawy"),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )
    reference = forms.CharField(
        max_length=160, required=False, label=_("Referencja")
    )
    notes = forms.CharField(
        required=False,
        label=_("Uwagi"),
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def clean(self):
        cleaned = super().clean()
        if (
            cleaned.get("expected_count") is not None
            and cleaned.get("confirmation_count") is not None
            and cleaned["expected_count"] != cleaned["confirmation_count"]
        ):
            self.add_error(
                "confirmation_count",
                _("Wpisana liczba musi być identyczna z podglądem."),
            )
        return cleaned


__all__ = [
    "CorrectionForm",
    "FulfillmentForm",
    "LegacyConfirmForm",
    "LegacyPreviewForm",
    "OperatorReasonForm",
    "PlatformQueueFilterForm",
    "PrintRequestForm",
    "RequiredReasonForm",
]
