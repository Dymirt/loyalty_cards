"""Django settings for the MB Studio loyalty application."""

from pathlib import Path

from decouple import AutoConfig
from django.core.management.utils import get_random_secret_key
from django.utils.translation import gettext_lazy as _

from .configuration import config_with_legacy_alias


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
allowed_hosts_file = config_with_legacy_alias(
    config,
    "LOYALTY_ALLOWED_HOSTS_FILE",
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
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Existing model/table owner. It remains installed throughout extraction.
    "dotykacka.apps.DotykackaConfig",
    # Phase 5 adds only final-owner additive models; legacy tables stay above.
    "core.apps.CoreConfig",
    "tenants.apps.TenantsConfig",
    "customers.apps.CustomersConfig",
    "cards.apps.CardsConfig",
    "card_artwork.apps.CardArtworkConfig",
    "integrations.apps.IntegrationsConfig",
    "pos.apps.PosConfig",
    "pos_dotykacka.apps.PosDotykackaConfig",
    "communications.apps.CommunicationsConfig",
    "brevo.apps.BrevoConfig",
    "wallets.apps.WalletsConfig",
    "wallet_apple.apps.WalletAppleConfig",
    "wallet_google.apps.WalletGoogleConfig",
    "billing.apps.BillingConfig",
    "printing.apps.PrintingConfig",
    "enrollment.apps.EnrollmentConfig",
    "marketing.apps.MarketingConfig",
    "operations.apps.OperationsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "operations.middleware.PlatformSecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "loyalty_platform.urls"

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

WSGI_APPLICATION = "loyalty_platform.wsgi.application"
ASGI_APPLICATION = "loyalty_platform.asgi.application"

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

LANGUAGE_CODE = "pl"
LANGUAGES = [
    ("pl", _("Polski")),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = config("DJANGO_TIME_ZONE", default="Europe/Warsaw")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
configured_media_root = Path(config("MEDIA_ROOT", default="media"))
MEDIA_ROOT = (
    configured_media_root
    if configured_media_root.is_absolute()
    else BASE_DIR / configured_media_root
)
configured_print_package_root = Path(
    config("PRINT_PACKAGE_ROOT", default="var/print-packages")
)
PRINT_PACKAGE_ROOT = (
    configured_print_package_root
    if configured_print_package_root.is_absolute()
    else BASE_DIR / configured_print_package_root
)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
TEST_RUNNER = "loyalty_platform.test_runner.NoExternalCallsDiscoverRunner"
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

# Legacy first-tenant import aliases. Runtime tenant configuration is database-owned;
# these values are read only by historical migrations/verification.
DOTYKACKA_AUTHORIZATION_TOKEN = config("DOTYKACKA_AUTHORIZATION_TOKEN", default="")
DOTYKACKA_CLOUD_ID = config("DOTYKACKA_CLOUD_ID", default=0, cast=int)
DOTYKACKA_DISCOUNT_GROUP_ID = config("DOTYKACKA_DISCOUNT_GROUP_ID", default=0, cast=int)
DOTYKACKA_HTTP_TIMEOUT = config("DOTYKACKA_HTTP_TIMEOUT", default=15, cast=int)
DOTYKACKA_CONNECTOR_CLIENT_ID = config("DOTYKACKA_CONNECTOR_CLIENT_ID", default="")
DOTYKACKA_CONNECTOR_CLIENT_SECRET = config(
    "DOTYKACKA_CONNECTOR_CLIENT_SECRET", default=""
)
DOTYKACKA_CONNECTOR_URL = config(
    "DOTYKACKA_CONNECTOR_URL",
    default="https://admin.dotykacka.cz/client/connect/v2",
)
DOTYKACKA_API_BASE_URL = config(
    "DOTYKACKA_API_BASE_URL", default="https://api.dotykacka.cz"
)
DOTYKACKA_TOKEN_EXPIRY_SKEW = config(
    "DOTYKACKA_TOKEN_EXPIRY_SKEW", default=120, cast=int
)
DOTYKACKA_MAX_PAGES = config("DOTYKACKA_MAX_PAGES", default=1000, cast=int)

BREVO_API_KEY = config("BREVO_API_KEY", default="")
BREVO_LIST_ID = config("BREVO_LIST_ID", default=25, cast=int)
BREVO_API_BASE_URL = config("BREVO_API_BASE_URL", default="https://api.brevo.com/v3")
BREVO_HTTP_TIMEOUT = config("BREVO_HTTP_TIMEOUT", default=15, cast=int)
DEFAULT_PHONE_COUNTRY_CODE = config("DEFAULT_PHONE_COUNTRY_CODE", default="+48")
INTEGRATION_HTTP_RETRIES = config("INTEGRATION_HTTP_RETRIES", default=2, cast=int)

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
GOOGLE_WALLET_ORIGINS = csv_setting("GOOGLE_WALLET_ORIGINS")
GOOGLE_WALLET_API_BASE_URL = config(
    "GOOGLE_WALLET_API_BASE_URL",
    default="https://walletobjects.googleapis.com/walletobjects/v1",
)
GOOGLE_WALLET_HTTP_TIMEOUT = config("GOOGLE_WALLET_HTTP_TIMEOUT", default=15, cast=int)
GOOGLE_WALLET_REMOTE_SYNC_ENABLED = config(
    "GOOGLE_WALLET_REMOTE_SYNC_ENABLED", default=True, cast=bool
)

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
ENROLLMENT_LINK_TTL_DAYS = config(
    "ENROLLMENT_LINK_TTL_DAYS",
    default=30,
    cast=int,
)
MARKETING_LEGAL_NAME = config("MARKETING_LEGAL_NAME", default="MB Studio")
MARKETING_LEGAL_ADDRESS = config("MARKETING_LEGAL_ADDRESS", default="")
MARKETING_CONTACT_EMAIL = config(
    "MARKETING_CONTACT_EMAIL",
    default="kontakt@mbstudio.online",
)
MARKETING_PRIVACY_VERSION = config(
    "MARKETING_PRIVACY_VERSION",
    default="2026-07-18",
)
MARKETING_TERMS_VERSION = config(
    "MARKETING_TERMS_VERSION",
    default="2026-07-18",
)
MARKETING_PRIVACY_CONSENT_TEXT = (
    "Wyrażam zgodę na kontakt w sprawie zapytania i potwierdzam zapoznanie się "
    f"z polityką prywatności w wersji {MARKETING_PRIVACY_VERSION}."
)
LEGACY_DEFAULT_TENANT_SLUG = config(
    "LEGACY_DEFAULT_TENANT_SLUG",
    default="marta-banaszek-atelier-cafe",
)
TENANT_SECRETS_ENCRYPTION_KEYS = csv_setting("TENANT_SECRETS_ENCRYPTION_KEYS")

if config("DJANGO_TRUST_X_FORWARDED_PROTO", default=False, cast=bool):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = config("DJANGO_SECURE_SSL_REDIRECT", default=False, cast=bool)
SESSION_COOKIE_SECURE = config("DJANGO_SESSION_COOKIE_SECURE", default=not DEBUG, cast=bool)
CSRF_COOKIE_SECURE = config("DJANGO_CSRF_COOKIE_SECURE", default=not DEBUG, cast=bool)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = config("DJANGO_SECURE_HSTS_SECONDS", default=0, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False, cast=bool
)
SECURE_HSTS_PRELOAD = config("DJANGO_SECURE_HSTS_PRELOAD", default=False, cast=bool)

# The artwork form accepts at most two validated 12 MB images. Django and Apache
# reject larger request bodies before Pillow performs any decoding.
DATA_UPLOAD_MAX_MEMORY_SIZE = config(
    "DATA_UPLOAD_MAX_MEMORY_SIZE", default=28 * 1024 * 1024, cast=int
)
FILE_UPLOAD_MAX_MEMORY_SIZE = config(
    "FILE_UPLOAD_MAX_MEMORY_SIZE", default=2_621_440, cast=int
)
DATA_UPLOAD_MAX_NUMBER_FIELDS = config(
    "DATA_UPLOAD_MAX_NUMBER_FIELDS", default=200, cast=int
)
DATA_UPLOAD_MAX_NUMBER_FILES = config(
    "DATA_UPLOAD_MAX_NUMBER_FILES", default=4, cast=int
)

MARKETING_CONTACT_RATE_LIMIT = config(
    "MARKETING_CONTACT_RATE_LIMIT", default=5, cast=int
)
ENROLLMENT_RATE_LIMIT = config("ENROLLMENT_RATE_LIMIT", default=10, cast=int)
DOTYKACKA_CONNECT_RATE_LIMIT = config(
    "DOTYKACKA_CONNECT_RATE_LIMIT", default=10, cast=int
)
PUBLIC_RATE_LIMIT_WINDOW_SECONDS = config(
    "PUBLIC_RATE_LIMIT_WINDOW_SECONDS", default=3600, cast=int
)
CONNECT_RATE_LIMIT_WINDOW_SECONDS = config(
    "CONNECT_RATE_LIMIT_WINDOW_SECONDS", default=900, cast=int
)
LOYALTY_TRUSTED_PROXY_CIDRS = csv_setting("LOYALTY_TRUSTED_PROXY_CIDRS")

WORKER_HEARTBEAT_INTERVAL_SECONDS = config(
    "WORKER_HEARTBEAT_INTERVAL_SECONDS", default=15, cast=int
)
WORKER_HEARTBEAT_MAX_AGE_SECONDS = config(
    "WORKER_HEARTBEAT_MAX_AGE_SECONDS", default=90, cast=int
)
OPERATIONS_MONITOR_INTERVAL_SECONDS = config(
    "OPERATIONS_MONITOR_INTERVAL_SECONDS", default=60, cast=int
)
MONITOR_LOW_INVENTORY_THRESHOLD = config(
    "MONITOR_LOW_INVENTORY_THRESHOLD", default=50, cast=int
)
MONITOR_ENTITLEMENT_WARNING_PERCENT = config(
    "MONITOR_ENTITLEMENT_WARNING_PERCENT", default=80, cast=int
)
MONITOR_PROVIDER_AUTH_FAILURE_THRESHOLD = config(
    "MONITOR_PROVIDER_AUTH_FAILURE_THRESHOLD", default=3, cast=int
)
MARKETING_LEAD_RETENTION_DAYS = config(
    "MARKETING_LEAD_RETENTION_DAYS", default=365, cast=int
)
BACKUP_ROOT = Path(config("BACKUP_ROOT", default="local-data/backups"))
if not BACKUP_ROOT.is_absolute():
    BACKUP_ROOT = BASE_DIR / BACKUP_ROOT

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "redact": {"()": "operations.logging.RedactingFilter"},
    },
    "formatters": {
        "json": {"()": "operations.logging.JsonLogFormatter"},
    },
    "handlers": {
        "json_console": {
            "class": "logging.StreamHandler",
            "filters": ["redact"],
            "formatter": "json",
        },
    },
    "loggers": {
        "loyalty": {
            "handlers": ["json_console"],
            "level": config("LOYALTY_LOG_LEVEL", default="INFO"),
            "propagate": False,
        },
        "django.request": {
            "handlers": ["json_console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["json_console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
