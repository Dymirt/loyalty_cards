from django import forms

from tenants.forms import style_portal_form


class AlertActionForm(forms.Form):
    reason = forms.CharField(
        label="Powód / notatka operatora",
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_portal_form(self)

