"""Bearer-authenticated virtual-card API routes."""

from django.urls import path

from . import api_views


app_name = "virtual_cards_api"
urlpatterns = [
    path("virtual-card-designs/", api_views.design_list, name="designs"),
    path("virtual-cards/", api_views.create_virtual_card, name="create"),
    path(
        "virtual-cards/<uuid:public_id>/",
        api_views.virtual_card_detail,
        name="detail",
    ),
]
