"""WSGI config for the MB Studio loyalty platform."""

import os

from django.core.wsgi import get_wsgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "loyalty_platform.settings")

application = get_wsgi_application()
