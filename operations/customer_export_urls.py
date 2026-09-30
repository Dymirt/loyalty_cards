"""Public URL routes for token-authenticated customer exports."""

from django.urls import path

from . import customer_export_views


app_name = "customers_api"

urlpatterns = [path("clients/", customer_export_views.client_list, name="clients")]
