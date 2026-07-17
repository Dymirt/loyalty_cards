"""Django settings for the MB Studio loyalty application."""

from pathlib import Path

from decouple import AutoConfig
from django.core.management.utils import get_random_secret_key


BASE_DIR = Path(__file__).resolve().parent.parent
config = AutoConfig(search_path=str(BASE_DIR))


def csv_setting(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in config(name, default=default).split(",") if item.strip()]


DEBUG = config("DJANGO_DEBUG", default=False, cast=bool)
SECRET_KEY = config("DJANGO_SECRET_KEY", default="")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = get_random_secret_key()
    else:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false")

ALLOWED_HOSTS = csv_setting("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
allowed_hosts_file = config(
    "TURNKEY_ALLOWED_HOSTS_FILE",
    default="/var/lib/django/allowed_hosts",
)
if allowed_hosts_file and Path(allowed_hosts_file).is_file():
    ALLOWED_HOSTS.extend(
        host.strip()
        for host in Path(allowed_hosts_file).read_text(encoding="utf-8").splitlines()
        if host.strip()
    )
ALLOWED_HOSTS = list(dict.fromkeys(ALLOWED_HOSTS))

CSRF_TRUSTED_ORIGINS = csv_setting("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "dotykacka.apps.DotykackaConfig",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "turnkey_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "turnkey_project.wsgi.application"
ASGI_APPLICATION = "turnkey_project.asgi.application"

database_engine = config("DB_ENGINE", default="django.db.backends.sqlite3")
if database_engine == "django.db.backends.sqlite3":
    database_name = config("DB_NAME", default="")
    DATABASES = {
        "default": {
            "ENGINE": database_engine,
            "NAME": database_name or BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": database_engine,
            "NAME": config("DB_NAME"),
            "USER": config("DB_USER"),
            "PASSWORD": config("DB_PASSWORD"),
            "HOST": config("DB_HOST", default=""),
            "PORT": config("DB_PORT", default=""),
            "CONN_MAX_AGE": config("DB_CONN_MAX_AGE", default=60, cast=int),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pl-pl"
TIME_ZONE = config("DJANGO_TIME_ZONE", default="Europe/Warsaw")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
TEST_RUNNER = "turnkey_project.test_runner.NoExternalCallsDiscoverRunner"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"

EMAIL_BACKEND = config(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_USE_SSL = config("EMAIL_USE_SSL", default=False, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default=EMAIL_HOST_USER or "webmaster@localhost")
EMAIL_TIMEOUT = config("EMAIL_TIMEOUT", default=15, cast=int)

DOTYKACKA_AUTHORIZATION_TOKEN = config("DOTYKACKA_AUTHORIZATION_TOKEN", default="")
DOTYKACKA_CLOUD_ID = config("DOTYKACKA_CLOUD_ID", default=0, cast=int)
DOTYKACKA_DISCOUNT_GROUP_ID = config("DOTYKACKA_DISCOUNT_GROUP_ID", default=0, cast=int)
DOTYKACKA_HTTP_TIMEOUT = config("DOTYKACKA_HTTP_TIMEOUT", default=15, cast=int)

BREVO_API_KEY = config("BREVO_API_KEY", default="")
BREVO_LIST_ID = config("BREVO_LIST_ID", default=25, cast=int)
DEFAULT_PHONE_COUNTRY_CODE = config("DEFAULT_PHONE_COUNTRY_CODE", default="+48")

google_wallet_keyfile = Path(
    config(
        "GOOGLE_WALLET_SERVICE_ACCOUNT_FILE",
        default="secrets/google-wallet-service-account.json",
    )
)
if not google_wallet_keyfile.is_absolute():
    google_wallet_keyfile = BASE_DIR / google_wallet_keyfile
GOOGLE_WALLET_SERVICE_ACCOUNT_FILE = google_wallet_keyfile
GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL = config("GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL", default="")
GOOGLE_WALLET_ISSUER_ID = config("GOOGLE_WALLET_ISSUER_ID", default="")
GOOGLE_WALLET_CLASS_SUFFIX = config("GOOGLE_WALLET_CLASS_SUFFIX", default="MB")
GOOGLE_WALLET_ORIGINS = csv_setting("GOOGLE_WALLET_ORIGINS")

APPLE_WALLET_PASS_TYPE_IDENTIFIER = config("APPLE_WALLET_PASS_TYPE_IDENTIFIER", default="")
APPLE_WALLET_TEAM_IDENTIFIER = config("APPLE_WALLET_TEAM_IDENTIFIER", default="")
apple_wallet_template_dir = Path(
    config(
        "APPLE_WALLET_TEMPLATE_DIR",
        default=str(MEDIA_ROOT / "mypass_template"),
    )
)
if not apple_wallet_template_dir.is_absolute():
    apple_wallet_template_dir = BASE_DIR / apple_wallet_template_dir
APPLE_WALLET_TEMPLATE_DIR = apple_wallet_template_dir

APP_BASE_URL = config("APP_BASE_URL", default="http://localhost:8000").rstrip("/")
LEGACY_DEFAULT_TENANT_SLUG = config(
    "LEGACY_DEFAULT_TENANT_SLUG",
    default="marta-banaszek-atelier-cafe",
)
TENANT_SECRETS_ENCRYPTION_KEYS = csv_setting("TENANT_SECRETS_ENCRYPTION_KEYS")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = config("DJANGO_SECURE_SSL_REDIRECT", default=False, cast=bool)
SESSION_COOKIE_SECURE = config("DJANGO_SESSION_COOKIE_SECURE", default=not DEBUG, cast=bool)
CSRF_COOKIE_SECURE = config("DJANGO_CSRF_COOKIE_SECURE", default=not DEBUG, cast=bool)
