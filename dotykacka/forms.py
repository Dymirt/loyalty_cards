"""Django forms for public loyalty-card registration."""

import re

from django import forms

from .card_codes import CardCodeError, parse_card_code
from .models import (
    CardDesign,
    IntegrationConnection,
    Klient,
    PhysicalCard,
    Tenant,
    TenantBrand,
)


PORTAL_INPUT_CLASSES = (
    "portal-input disabled:cursor-not-allowed disabled:bg-stone-100 "
    "disabled:text-stone-500"
)
PORTAL_CHECKBOX_CLASSES = (
    "mt-1 size-5 rounded border-stone-300 text-accent-700 "
    "focus:ring-2 focus:ring-accent-100"
)


def _style_portal_form(form):
    for name, field in form.fields.items():
        classes = (
            PORTAL_CHECKBOX_CLASSES
            if isinstance(field.widget, forms.CheckboxInput)
            else PORTAL_INPUT_CLASSES
        )
        field.widget.attrs["class"] = classes
        if field.help_text:
            field.widget.attrs["aria-describedby"] = f"{form[name].id_for_label}_help"


class LoyaltyCustomerRegistrationForm(forms.Form):
    first_name = forms.CharField(max_length=100, label="Imię")
    last_name = forms.CharField(max_length=100, label="Nazwisko")
    email = forms.EmailField(max_length=100, label="E-mail")
    phone = forms.CharField(max_length=20, label="Tel.")
    barcode = forms.CharField(max_length=60, label="Barcode")
    marketing_consent = forms.BooleanField(
        required=True,
        label="Zgoda marketingowa",
    )

    def __init__(self, *args, tenant: Tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        _style_portal_form(self)
        if hasattr(tenant, "brand") and tenant.brand.marketing_consent_text:
            self.fields["marketing_consent"].label = tenant.brand.marketing_consent_text

    def clean_phone(self) -> str:
        phone = self.cleaned_data["phone"].strip()
        if not re.fullmatch(r"[1-9][0-9]{8}", phone):
            raise forms.ValidationError("Podaj 9-cyfrowy numer telefonu.")
        return phone

    def clean_barcode(self) -> str:
        try:
            barcode = parse_card_code(
                self.cleaned_data["barcode"],
                expected_prefix=self.tenant.card_prefix,
            ).value
        except CardCodeError as exc:
            raise forms.ValidationError("Nieprawidłowy format kodu kreskowego.") from exc

        if Klient.objects.filter(tenant=self.tenant, klient_id=barcode).exists():
            raise forms.ValidationError("Ta karta już istnieje w bazie danych.")
        card = PhysicalCard.objects.filter(tenant=self.tenant, code=barcode).first()
        if card is None:
            raise forms.ValidationError("Ta karta nie należy do dostępnej puli kart.")
        if card.customer_id or card.status != PhysicalCard.Status.AVAILABLE:
            raise forms.ValidationError("Ta karta została już przypisana.")
        return barcode


def registration_form_data(post_data):
    """Accept old field names while new templates use Python-style names."""

    data = post_data.copy()
    aliases = {
        "first_name": "firstName",
        "last_name": "lastName",
        "phone": "tel",
    }
    for current_name, legacy_name in aliases.items():
        if current_name not in data and legacy_name in data:
            data[current_name] = data[legacy_name]
    return data


class TenantBrandForm(forms.ModelForm):
    class Meta:
        model = TenantBrand
        fields = (
            "public_name",
            "tagline",
            "address",
            "phone",
            "email",
            "website_url",
            "email_subject",
            "email_signature",
            "marketing_consent_text",
        )
        labels = {
            "public_name": "Nazwa publiczna",
            "tagline": "Hasło marki",
            "address": "Adres",
            "phone": "Telefon",
            "email": "E-mail",
            "website_url": "Strona WWW",
            "email_subject": "Temat wiadomości z kartą",
            "email_signature": "Podpis wiadomości",
            "marketing_consent_text": "Treść zgody marketingowej",
        }
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3}),
            "marketing_consent_text": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_portal_form(self)


class CardDesignForm(forms.Form):
    name = forms.CharField(max_length=160, label="Nazwa wersji projektu")
    background_image = forms.ImageField(
        required=False,
        label="Obraz tła",
        help_text="JPG, PNG lub WebP; maksymalnie 12 MB i 40 megapikseli.",
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
    )
    logo_image = forms.ImageField(
        required=False,
        label="Logo",
        help_text="JPG, PNG lub WebP; przezroczysty PNG jest obsługiwany.",
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
    )
    layout_preset = forms.ChoiceField(
        choices=CardDesign.LayoutPreset.choices,
        label="Układ",
    )
    crop_mode = forms.ChoiceField(
        choices=CardDesign.CropMode.choices,
        label="Kadrowanie tła",
    )
    focal_x = forms.IntegerField(min_value=0, max_value=100, label="Punkt X (%)")
    focal_y = forms.IntegerField(min_value=0, max_value=100, label="Punkt Y (%)")
    width_px = forms.IntegerField(min_value=600, max_value=4000, label="Szerokość (px)")
    height_px = forms.IntegerField(min_value=350, max_value=3000, label="Wysokość (px)")
    dpi = forms.IntegerField(min_value=150, max_value=600, label="DPI")
    bleed_mm = forms.DecimalField(
        min_value=0,
        max_value=10,
        max_digits=4,
        decimal_places=1,
        label="Spad (mm)",
    )
    logo_width_px = forms.IntegerField(
        min_value=80,
        max_value=2000,
        label="Szerokość logo (px)",
    )
    front_text = forms.CharField(
        required=False,
        max_length=240,
        label="Tekst z przodu",
    )
    back_text = forms.CharField(
        required=False,
        label="Tekst z tyłu",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    foreground_color = forms.RegexField(
        regex=r"^#[0-9A-Fa-f]{6}$",
        label="Kolor tekstu",
        widget=forms.TextInput(attrs={"type": "color"}),
    )
    panel_color = forms.RegexField(
        regex=r"^#[0-9A-Fa-f]{6}$",
        label="Kolor panelu",
        widget=forms.TextInput(attrs={"type": "color"}),
    )
    barcode_foreground_color = forms.RegexField(
        regex=r"^#[0-9A-Fa-f]{6}$",
        label="Kolor kodu",
        widget=forms.TextInput(attrs={"type": "color"}),
    )
    barcode_background_color = forms.RegexField(
        regex=r"^#[0-9A-Fa-f]{6}$",
        label="Tło kodu",
        widget=forms.TextInput(attrs={"type": "color"}),
    )
    font_family = forms.ChoiceField(
        choices=(("barlow", "Barlow"),),
        label="Krój pisma",
    )

    def __init__(self, *args, tenant: Tenant, current_design=None, **kwargs):
        self.tenant = tenant
        self.current_design = current_design
        if not args and "data" not in kwargs:
            if current_design:
                kwargs["initial"] = {
                    field: getattr(current_design, field)
                    for field in (
                        "name",
                        "layout_preset",
                        "crop_mode",
                        "focal_x",
                        "focal_y",
                        "width_px",
                        "height_px",
                        "dpi",
                        "bleed_mm",
                        "logo_width_px",
                        "front_text",
                        "back_text",
                        "foreground_color",
                        "panel_color",
                        "barcode_foreground_color",
                        "barcode_background_color",
                        "font_family",
                    )
                }
            else:
                kwargs["initial"] = {
                    "name": f"{tenant.name} design",
                    "layout_preset": CardDesign.LayoutPreset.CENTERED,
                    "crop_mode": CardDesign.CropMode.DETERMINISTIC,
                    "focal_x": 50,
                    "focal_y": 50,
                    "width_px": 1011,
                    "height_px": 638,
                    "dpi": 300,
                    "bleed_mm": 0,
                    "logo_width_px": 576,
                    "foreground_color": "#000000",
                    "panel_color": "#FFFFFF",
                    "barcode_foreground_color": "#000000",
                    "barcode_background_color": "#FFFFFF",
                    "font_family": "barlow",
                }
        super().__init__(*args, **kwargs)
        _style_portal_form(self)

    def _validate_uploaded_image(self, value, *, minimum_size=None):
        if not value:
            return value
        image = getattr(value, "image", None)
        if image and image.format not in {"JPEG", "PNG", "WEBP"}:
            raise forms.ValidationError("Dozwolone formaty to JPG, PNG i WebP.")
        if value.size > 12 * 1024 * 1024:
            raise forms.ValidationError("Plik może mieć maksymalnie 12 MB.")
        if image and image.width * image.height > 40_000_000:
            raise forms.ValidationError("Obraz może mieć maksymalnie 40 megapikseli.")
        if image and minimum_size and (
            image.width < minimum_size[0] or image.height < minimum_size[1]
        ):
            raise forms.ValidationError(
                f"Obraz musi mieć co najmniej {minimum_size[0]} × {minimum_size[1]} px."
            )
        return value

    def clean_background_image(self):
        return self._validate_uploaded_image(
            self.cleaned_data.get("background_image"),
            minimum_size=(800, 500),
        )

    def clean_logo_image(self):
        return self._validate_uploaded_image(self.cleaned_data.get("logo_image"))

    def clean(self):
        cleaned = super().clean()
        has_background = bool(cleaned.get("background_image")) or bool(
            self.current_design and self.current_design.background_source
        )
        if not has_background:
            self.add_error("background_image", "Dodaj obraz tła dla pierwszej wersji projektu.")
        if (
            cleaned.get("logo_width_px")
            and cleaned.get("width_px")
            and cleaned["logo_width_px"] > cleaned["width_px"] - 40
        ):
            self.add_error("logo_width_px", "Logo musi mieścić się w szerokości karty.")
        return cleaned


class DotykackaIntegrationForm(forms.Form):
    enabled = forms.BooleanField(required=False, label="Włącz integrację")
    cloud_id = forms.IntegerField(min_value=1, required=False, label="Cloud ID")
    discount_group_id = forms.IntegerField(
        min_value=1,
        required=False,
        label="ID grupy rabatowej",
    )
    authorization_token = forms.CharField(
        required=False,
        label="Token autoryzacyjny",
        widget=forms.PasswordInput(render_value=False),
        help_text="Pozostaw puste, aby zachować zapisany token.",
    )

    def __init__(self, *args, tenant: Tenant, connection=None, **kwargs):
        self.tenant = tenant
        self.connection = connection or IntegrationConnection(
            tenant=tenant,
            provider=IntegrationConnection.Provider.DOTYKACKA,
        )
        if not args and "data" not in kwargs:
            kwargs["initial"] = {
                "enabled": self.connection.enabled,
                "cloud_id": self.connection.configuration.get("cloud_id"),
                "discount_group_id": self.connection.configuration.get(
                    "discount_group_id"
                ),
            }
        super().__init__(*args, **kwargs)
        _style_portal_form(self)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("enabled"):
            for field in ("cloud_id", "discount_group_id"):
                if not cleaned.get(field):
                    self.add_error(field, "To pole jest wymagane dla aktywnej integracji.")
            if not cleaned.get("authorization_token") and not self.connection.has_secret(
                "authorization_token"
            ):
                self.add_error(
                    "authorization_token",
                    "Token jest wymagany dla aktywnej integracji.",
                )
        return cleaned

    def save(self):
        self.connection.configuration = {
            "cloud_id": self.cleaned_data.get("cloud_id") or 0,
            "discount_group_id": self.cleaned_data.get("discount_group_id") or 0,
        }
        credentials = self.connection.get_credentials()
        if self.cleaned_data.get("authorization_token"):
            credentials["authorization_token"] = self.cleaned_data["authorization_token"]
        self.connection.set_credentials(credentials)
        self.connection.enabled = self.cleaned_data["enabled"]
        self.connection.save()
        return self.connection


class BrevoIntegrationForm(forms.Form):
    enabled = forms.BooleanField(required=False, label="Włącz integrację")
    list_id = forms.IntegerField(min_value=1, required=False, label="ID listy")
    default_phone_country_code = forms.RegexField(
        regex=r"^\+[1-9][0-9]{0,3}$",
        required=False,
        label="Domyślny kod kraju",
    )
    api_key = forms.CharField(
        required=False,
        label="Klucz API",
        widget=forms.PasswordInput(render_value=False),
        help_text="Pozostaw puste, aby zachować zapisany klucz.",
    )

    def __init__(self, *args, tenant: Tenant, connection=None, **kwargs):
        self.tenant = tenant
        self.connection = connection or IntegrationConnection(
            tenant=tenant,
            provider=IntegrationConnection.Provider.BREVO,
        )
        if not args and "data" not in kwargs:
            kwargs["initial"] = {
                "enabled": self.connection.enabled,
                "list_id": self.connection.configuration.get("list_id"),
                "default_phone_country_code": self.connection.configuration.get(
                    "default_phone_country_code", "+48"
                ),
            }
        super().__init__(*args, **kwargs)
        _style_portal_form(self)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("enabled"):
            if not cleaned.get("list_id"):
                self.add_error("list_id", "To pole jest wymagane dla aktywnej integracji.")
            if not cleaned.get("api_key") and not self.connection.has_secret("api_key"):
                self.add_error("api_key", "Klucz jest wymagany dla aktywnej integracji.")
        return cleaned

    def save(self):
        self.connection.configuration = {
            "list_id": self.cleaned_data.get("list_id") or 0,
            "default_phone_country_code": self.cleaned_data.get(
                "default_phone_country_code"
            )
            or "+48",
        }
        credentials = self.connection.get_credentials()
        if self.cleaned_data.get("api_key"):
            credentials["api_key"] = self.cleaned_data["api_key"]
        self.connection.set_credentials(credentials)
        self.connection.enabled = self.cleaned_data["enabled"]
        self.connection.save()
        return self.connection


class GoogleWalletIntegrationForm(forms.Form):
    enabled = forms.BooleanField(required=False, label="Włącz integrację")
    issuer_id = forms.CharField(max_length=100, required=False, label="ID wydawcy")
    class_suffix = forms.RegexField(
        regex=r"^[A-Za-z0-9_-]{1,64}$",
        required=False,
        label="Sufiks klasy",
    )

    def __init__(self, *args, tenant: Tenant, connection=None, **kwargs):
        self.tenant = tenant
        self.connection = connection or IntegrationConnection(
            tenant=tenant,
            provider=IntegrationConnection.Provider.GOOGLE_WALLET,
        )
        if not args and "data" not in kwargs:
            kwargs["initial"] = {
                "enabled": self.connection.enabled,
                "issuer_id": self.connection.configuration.get("issuer_id"),
                "class_suffix": self.connection.configuration.get("class_suffix"),
            }
        super().__init__(*args, **kwargs)
        _style_portal_form(self)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("enabled"):
            for field in ("issuer_id", "class_suffix"):
                if not cleaned.get(field):
                    self.add_error(field, "To pole jest wymagane dla aktywnej integracji.")
        return cleaned

    def save(self):
        self.connection.configuration = {
            "issuer_id": self.cleaned_data.get("issuer_id") or "",
            "class_suffix": self.cleaned_data.get("class_suffix") or "",
        }
        self.connection.enabled = self.cleaned_data["enabled"]
        self.connection.save()
        return self.connection
