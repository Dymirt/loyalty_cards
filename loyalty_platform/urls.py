"""Root URL configuration for the MB Studio loyalty platform."""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from . import views


urlpatterns = [
    path(
        "turnkey/",
        include(("turnkey_app.urls", "turnkey_compat"), namespace="turnkey_compat"),
    ),
    path("marketing/", include(("marketing.urls", "marketing"), namespace="marketing")),
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
    path("", views.index, name="index"),
]
