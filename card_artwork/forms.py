"""Versioned tenant card-artwork forms."""

from django import forms
from django.utils.translation import gettext_lazy as _

from tenants.forms import style_portal_form

from .models import CardArtworkSource, CardDesign


class CardDesignForm(forms.Form):
    name = forms.CharField(max_length=160, label=_("Nazwa wersji projektu"))
    source_image = forms.ModelChoiceField(
        queryset=CardArtworkSource.objects.none(),
        required=False,
        label=_("Wybierz zapisany obraz źródłowy"),
        help_text=_(
            "Wybór nie zmienia ani nie usuwa obrazu używanego przez wcześniejsze wersje."
        ),
    )
    background_image = forms.ImageField(
        required=False,
        label=_("Duży obraz źródłowy"),
        help_text=_(
            "JPG, PNG lub WebP; maksymalnie 50 MB i 50 megapikseli. "
            "Z jednego obrazu powstaną powtarzalne, zróżnicowane kadry kart."
        ),
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
    )
    logo_image = forms.ImageField(
        required=False,
        label=_("Logo"),
        help_text=_("JPG, PNG lub WebP; przezroczysty PNG jest obsługiwany."),
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
    )
    layout_preset = forms.ChoiceField(
        choices=CardDesign.LayoutPreset.choices, label=_("Układ")
    )
    crop_mode = forms.ChoiceField(
        choices=CardDesign.CropMode.choices, label=_("Kadrowanie tła")
    )
    focal_x = forms.IntegerField(min_value=0, max_value=100, label=_("Punkt X (%)"))
    focal_y = forms.IntegerField(min_value=0, max_value=100, label=_("Punkt Y (%)"))
    width_px = forms.IntegerField(
        min_value=600, max_value=4000, label=_("Szerokość (px)")
    )
    height_px = forms.IntegerField(
        min_value=350, max_value=3000, label=_("Wysokość (px)")
    )
    dpi = forms.IntegerField(min_value=150, max_value=600, label=_("DPI"))
    bleed_mm = forms.DecimalField(
        min_value=0,
        max_value=10,
        max_digits=4,
        decimal_places=1,
        label=_("Spad (mm)"),
    )
    logo_width_px = forms.IntegerField(
        min_value=80, max_value=2000, label=_("Szerokość logo (px)")
    )
    front_text = forms.CharField(
        required=False,
        max_length=240,
        label=_("Tekst z przodu"),
        help_text=_("Puste pole użyje nazwy lub hasła z opublikowanej marki."),
    )
    back_text = forms.CharField(
        required=False,
        label=_("Tekst z tyłu"),
        help_text=_("Puste pole użyje danych kontaktowych z opublikowanej marki."),
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    foreground_color = forms.RegexField(
        regex=r"^#[0-9A-Fa-f]{6}$",
        label=_("Kolor tekstu"),
        widget=forms.TextInput(attrs={"type": "color"}),
    )
    panel_color = forms.RegexField(
        regex=r"^#[0-9A-Fa-f]{6}$",
        label=_("Kolor panelu"),
        widget=forms.TextInput(attrs={"type": "color"}),
    )
    barcode_foreground_color = forms.RegexField(
        regex=r"^#[0-9A-Fa-f]{6}$",
        label=_("Kolor kodu"),
        widget=forms.TextInput(attrs={"type": "color"}),
    )
    barcode_background_color = forms.RegexField(
        regex=r"^#[0-9A-Fa-f]{6}$",
        label=_("Tło kodu"),
        widget=forms.TextInput(attrs={"type": "color"}),
    )
    font_family = forms.ChoiceField(
        choices=(("barlow", "Barlow"),), label=_("Krój pisma")
    )
    sample_count = forms.IntegerField(
        min_value=3,
        max_value=12,
        initial=6,
        required=False,
        label=_("Liczba przykładowych kadrów"),
        help_text=_("Podgląd nie zapisuje ani nie przydziela kart."),
    )
    planned_card_count = forms.IntegerField(
        min_value=1,
        max_value=10_000_000,
        initial=600,
        required=False,
        label=_("Planowana liczba kart"),
        help_text=_(
            "System porówna tę liczbę z pojemnością wybranego obrazu. "
            "To pole nie zamawia druku."
        ),
    )

    SNAPSHOT_FIELDS = (
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

    def __init__(self, *args, tenant, current_design=None, **kwargs):
        self.tenant = tenant
        self.current_design = current_design
        if not args and "data" not in kwargs:
            if current_design:
                kwargs["initial"] = {
                    field: getattr(current_design, field) for field in self.SNAPSHOT_FIELDS
                }
                kwargs["initial"]["sample_count"] = 6
            else:
                kwargs["initial"] = {
                    "name": _("Projekt %(tenant)s") % {"tenant": tenant.name},
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
                    "sample_count": 6,
                }
        super().__init__(*args, **kwargs)
        sources = CardArtworkSource.objects.filter(tenant=tenant)
        self.fields["source_image"].queryset = sources
        if current_design and current_design.background_source:
            current_source = sources.filter(
                image=current_design.background_source.name
            ).first()
            if current_source:
                self.initial["source_image"] = current_source.pk
        style_portal_form(self)

    def _validate_uploaded_image(self, value, *, minimum_size=None, max_size_mb=50):
        if not value:
            return value
        image = getattr(value, "image", None)
        if image and image.format not in {"JPEG", "PNG", "WEBP"}:
            raise forms.ValidationError(_("Dozwolone formaty to JPG, PNG i WebP."))
        if value.size > max_size_mb * 1024 * 1024:
            raise forms.ValidationError(
                _("Plik może mieć maksymalnie %(size)s MB.")
                % {"size": max_size_mb}
            )
        if image and image.width * image.height > 50_000_000:
            raise forms.ValidationError(
                _("Obraz może mieć maksymalnie 50 megapikseli.")
            )
        if image and minimum_size and (image.width < minimum_size[0] or image.height < minimum_size[1]):
            raise forms.ValidationError(
                _("Obraz musi mieć co najmniej %(width)s × %(height)s px.")
                % {"width": minimum_size[0], "height": minimum_size[1]}
            )
        return value

    def clean_background_image(self):
        return self._validate_uploaded_image(
            self.cleaned_data.get("background_image"),
            minimum_size=(800, 500),
        )

    def clean_logo_image(self):
        return self._validate_uploaded_image(
            self.cleaned_data.get("logo_image"), max_size_mb=12
        )

    def clean(self):
        cleaned = super().clean()
        cleaned["planned_card_count"] = cleaned.get("planned_card_count") or 600
        has_background = bool(cleaned.get("background_image")) or bool(
            cleaned.get("source_image")
        ) or bool(
            self.current_design and self.current_design.background_source
        )
        if not has_background:
            self.add_error(
                "background_image",
                _("Dodaj obraz źródłowy dla pierwszej wersji projektu."),
            )
        if cleaned.get("logo_width_px") and cleaned.get("width_px") and cleaned["logo_width_px"] > cleaned["width_px"] - 40:
            self.add_error(
                "logo_width_px", _("Logo musi mieścić się w szerokości karty.")
            )
        return cleaned
