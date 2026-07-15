"""Compatibility exports for the Dotykačka integration.

New configuration belongs in ``turnkey_project.settings``. Keeping these
exports avoids changing every integration import in the initial source
snapshot.
"""

from django.conf import settings as django_settings


DOTYKACKA_AUTHORIZATION_TOKEN = django_settings.DOTYKACKA_AUTHORIZATION_TOKEN
DOTYKACKA_CLOUD_ID = django_settings.DOTYKACKA_CLOUD_ID
