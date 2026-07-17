"""Versioned tenant card-artwork forms."""

from django import forms

from tenants.forms import style_portal_form

from .models import CardDesign


class CardDesignForm(forms.Form):
    name = forms.CharField(max_length=160, label="Nazwa wersji projektu")
    background_image = forms.ImageField(
        required=False,
        label="Duży obraz źródłowy",
        help_text=(
            "JPG, PNG lub WebP; maksymalnie 12 MB i 40 megapikseli. "
            "Z jednego obrazu powstaną powtarzalne, zróżnicowane kadry kart."
        ),
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
    )
    logo_image = forms.ImageField(
        required=False,
        label="Logo",
        help_text="JPG, PNG lub WebP; przezroczysty PNG jest obsługiwany.",
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
    )
    layout_preset = forms.ChoiceField(choices=CardDesign.LayoutPreset.choices, label="Układ")
    crop_mode = forms.ChoiceField(choices=CardDesign.CropMode.choices, label="Kadrowanie tła")
    focal_x = forms.IntegerField(min_value=0, max_value=100, label="Punkt X (%)")
    focal_y = forms.IntegerField(min_value=0, max_value=100, label="Punkt Y (%)")
    width_px = forms.IntegerField(min_value=600, max_value=4000, label="Szerokość (px)")
    height_px = forms.IntegerField(min_value=350, max_value=3000, label="Wysokość (px)")
    dpi = forms.IntegerField(min_value=150, max_value=600, label="DPI")
    bleed_mm = forms.DecimalField(min_value=0, max_value=10, max_digits=4, decimal_places=1, label="Spad (mm)")
    logo_width_px = forms.IntegerField(min_value=80, max_value=2000, label="Szerokość logo (px)")
    front_text = forms.CharField(
        required=False,
        max_length=240,
        label="Tekst z przodu",
        help_text="Puste pole użyje nazwy lub hasła z opublikowanej marki.",
    )
    back_text = forms.CharField(
        required=False,
        label="Tekst z tyłu",
        help_text="Puste pole użyje danych kontaktowych z opublikowanej marki.",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    foreground_color = forms.RegexField(regex=r"^#[0-9A-Fa-f]{6}$", label="Kolor tekstu", widget=forms.TextInput(attrs={"type": "color"}))
    panel_color = forms.RegexField(regex=r"^#[0-9A-Fa-f]{6}$", label="Kolor panelu", widget=forms.TextInput(attrs={"type": "color"}))
    barcode_foreground_color = forms.RegexField(regex=r"^#[0-9A-Fa-f]{6}$", label="Kolor kodu", widget=forms.TextInput(attrs={"type": "color"}))
    barcode_background_color = forms.RegexField(regex=r"^#[0-9A-Fa-f]{6}$", label="Tło kodu", widget=forms.TextInput(attrs={"type": "color"}))
    font_family = forms.ChoiceField(choices=(("barlow", "Barlow"),), label="Krój pisma")
    sample_count = forms.IntegerField(
        min_value=3,
        max_value=12,
        initial=6,
        required=False,
        label="Liczba przykładowych kadrów",
        help_text="Podgląd nie zapisuje ani nie przydziela kart.",
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
                    "sample_count": 6,
                }
        super().__init__(*args, **kwargs)
        style_portal_form(self)

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
        if image and minimum_size and (image.width < minimum_size[0] or image.height < minimum_size[1]):
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
            self.add_error("background_image", "Dodaj obraz źródłowy dla pierwszej wersji projektu.")
        if cleaned.get("logo_width_px") and cleaned.get("width_px") and cleaned["logo_width_px"] > cleaned["width_px"] - 40:
            self.add_error("logo_width_px", "Logo musi mieścić się w szerokości karty.")
        return cleaned
