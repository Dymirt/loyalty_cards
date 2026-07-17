from django.urls import path

from . import views


app_name = "turnkey_compat"
urlpatterns = [
    path("", views.index, name="index"),
]
