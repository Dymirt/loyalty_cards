from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class MarketingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "marketing"
    verbose_name = _("Marketing")

    def ready(self):
        from . import checks  # noqa: F401
