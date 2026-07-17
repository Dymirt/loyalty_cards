from django.urls import path

from . import views


app_name = "cards"
urlpatterns = [
    path("platform/print-center", views.platform_print_center, name="platform_print_center"),
]
