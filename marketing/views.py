"""Public, server-rendered product and contact pages."""

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods

from billing.public_catalog import published_public_catalog
from operations.rate_limits import rate_limit_response

from .forms import MarketingLeadForm
from .services import record_marketing_lead


def _context(**extra):
    return {
        "marketing_page": True,
        "marketing_contact_email": settings.MARKETING_CONTACT_EMAIL,
        "marketing_legal_name": settings.MARKETING_LEGAL_NAME,
        "marketing_legal_address": settings.MARKETING_LEGAL_ADDRESS,
        "privacy_version": settings.MARKETING_PRIVACY_VERSION,
        "privacy_consent_text": settings.MARKETING_PRIVACY_CONSENT_TEXT,
        "terms_version": settings.MARKETING_TERMS_VERSION,
        **extra,
    }


@require_GET
def home(request):
    return render(
        request,
        "marketing/home.html",
        _context(**published_public_catalog()),
    )


@require_GET
def features(request):
    return render(request, "marketing/features.html", _context())


@require_GET
def integrations(request):
    return render(request, "marketing/integrations.html", _context())


@require_GET
def pricing(request):
    return render(
        request,
        "marketing/pricing.html",
        _context(**published_public_catalog()),
    )


def _contact_form_response(request, form, *, status=200):
    template_name = (
        "marketing/partials/contact_form.html"
        if request.headers.get("HX-Request") == "true"
        else "marketing/contact.html"
    )
    return render(request, template_name, _context(form=form), status=status)


@require_http_methods(["GET", "POST"])
def contact(request):
    if request.method == "GET":
        return _contact_form_response(request, MarketingLeadForm())
    limited = rate_limit_response(
        request,
        scope="marketing.contact",
        limit=settings.MARKETING_CONTACT_RATE_LIMIT,
        window_seconds=settings.PUBLIC_RATE_LIMIT_WINDOW_SECONDS,
    )
    if limited is not None:
        return limited
    form = MarketingLeadForm(request.POST)
    if form.is_valid():
        try:
            record_marketing_lead(
                cleaned_data=form.cleaned_data,
                source_path=request.path,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            if request.headers.get("HX-Request") == "true":
                return render(
                    request,
                    "marketing/partials/contact_success.html",
                    _context(),
                )
            messages.success(
                request, _("Dziękujemy. Zapytanie zostało bezpiecznie zapisane.")
            )
            return redirect("marketing:contact_thanks")
    return _contact_form_response(
        request,
        form,
        status=200 if request.headers.get("HX-Request") == "true" else 400,
    )


@require_GET
def contact_thanks(request):
    return render(request, "marketing/contact_thanks.html", _context())


@require_GET
def privacy(request):
    return render(request, "marketing/privacy.html", _context())


@require_GET
def terms(request):
    return render(request, "marketing/terms.html", _context())


@require_GET
def legacy_redirect(request):
    return redirect("marketing:home", permanent=True)


__all__ = [
    "contact",
    "contact_thanks",
    "features",
    "home",
    "integrations",
    "legacy_redirect",
    "pricing",
    "privacy",
    "terms",
]
