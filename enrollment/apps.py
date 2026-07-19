from django.apps import AppConfig


class EnrollmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "enrollment"
    verbose_name = "Enrollment"

    def ready(self):
        from . import checks  # noqa: F401
        from communications.registry import register_email_application_context_resolver

        from .links import email_application_context_for_job

        register_email_application_context_resolver(email_application_context_for_job)
