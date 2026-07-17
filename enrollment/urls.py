from django.urls import path

from . import views


app_name = "enrollment"
urlpatterns = [
    path("register", views.register_customer_form, name="register"),
    path("c/<slug:tenant_slug>/register", views.register_customer_form, name="tenant_register"),
]
