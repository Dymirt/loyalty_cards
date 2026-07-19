from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PrintingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "printing"
    verbose_name = _("Druk")

    def ready(self):
        from . import checks  # noqa: F401
