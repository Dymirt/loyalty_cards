from django.urls import path

from . import views


app_name = "tenants"
urlpatterns = [
    path("c/<slug:tenant_slug>/portal", views.tenant_portal, name="portal"),
]
