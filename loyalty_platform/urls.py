"""Root URL configuration for the MB Studio loyalty platform."""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from marketing import views as marketing_views
from operations.media import protected_media
from operations import views as operations_views


turnkey_compat_patterns = (
    [path("", marketing_views.legacy_redirect, name="index")],
    "turnkey_compat",
)


urlpatterns = [
    path("health/live", operations_views.liveness, name="health_live"),
    path("health/ready", operations_views.readiness, name="health_ready"),
    path("media/<path:path>", protected_media, name="protected_media"),
    path(
        "turnkey/",
        include(turnkey_compat_patterns, namespace="turnkey_compat"),
    ),
    path("marketing/", marketing_views.legacy_redirect, name="legacy_marketing"),
    path("admin/", admin.site.urls),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Phase 5 canonical domain routes precede the legacy namespace aliases.
    path("dotykacka/", include(("tenants.urls", "tenants"), namespace="tenants")),
    path("dotykacka/", include(("customers.urls", "customers"), namespace="customers")),
    path("dotykacka/", include(("printing.urls", "printing"), namespace="printing")),
    path("dotykacka/", include(("cards.urls", "cards"), namespace="cards")),
    path("dotykacka/", include(("billing.urls", "billing"), namespace="billing")),
    path(
        "dotykacka/",
        include(("integrations.urls", "integrations"), namespace="integrations"),
    ),
    path(
        "dotykacka/",
        include(("card_artwork.urls", "card_artwork"), namespace="card_artwork"),
    ),
    path("dotykacka/", include(("enrollment.urls", "enrollment"), namespace="enrollment")),
    path("dotykacka/", include("dotykacka.urls")),
    path(
        "integrations/",
        include(("pos_dotykacka.urls", "pos_dotykacka"), namespace="pos_dotykacka"),
    ),
    path(
        "dotykacka/",
        include(("operations.urls", "operations"), namespace="operations"),
    ),
    path("", marketing_views.home, name="index"),
    path("", include(("marketing.urls", "marketing"), namespace="marketing")),
]
