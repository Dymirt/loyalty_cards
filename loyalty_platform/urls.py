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
    path("dotykacka/", include("dotykacka.urls")),
    path("", views.index, name="index"),
]
