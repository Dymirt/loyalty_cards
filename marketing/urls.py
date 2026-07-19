from django.urls import path

from . import views


app_name = "marketing"
urlpatterns = [
    path("", views.home, name="home"),
    path("funkcje/", views.features, name="features"),
    path("integracje/", views.integrations, name="integrations"),
    path("cennik/", views.pricing, name="pricing"),
    path("kontakt/", views.contact, name="contact"),
    path("kontakt/dziekujemy/", views.contact_thanks, name="contact_thanks"),
    path("polityka-prywatnosci/", views.privacy, name="privacy"),
    path("regulamin/", views.terms, name="terms"),
]
