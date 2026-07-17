# MB Studio Loyalty SaaS

Django loyalty-card SaaS whose first tenant is Atelier-Café Marta Banaszek. The
legacy live service is available at [club.mbstudio.online](https://club.mbstudio.online).

This repository is a source-only snapshot of the complete application deployed
from `/var/www/turnkey_project` on the TurnKey container. Production secrets,
customer data, generated cards, Wallet passes, virtual environments, databases,
logs, and nested Git metadata are intentionally excluded.

## Current capabilities

- Public loyalty-card registration with barcode scanning.
- Local customer records in Django/MariaDB.
- Customer creation and synchronization with the Dotykačka Cloud API.
- Apple Wallet `.pkpass` generation and email delivery.
- Google Wallet loyalty-object JWT generation.
- Brevo contact synchronization.
- HTML and plain-text card emails over SMTP.
- Administrative customer listing, pass generation, and bulk delivery.
- Helper scripts for card artwork, barcode images, crops, manifests, and passes.
- Tenant-owned customers, physical-card inventory, branding, users, and integrations.
- Encrypted per-tenant Dotykačka/Brevo credentials and tenant settings UI.
- Shared accessible Django portal shell with separate client and platform navigation.
- Locally served HTMX enhancements and compiled Tailwind CSS with ordinary HTML fallbacks.
- Versioned tenant brand/card design settings with server-rendered proofs.
- Deterministic physical-card artwork, immutable checksummed artifacts, and protected proof downloads.
- Stable Apple Wallet serials and Google Wallet object identities per tenant customer.

## Runtime architecture

```text
Browser / mobile device
        |
Cloudflare + HTTPS
        |
Apache + mod_wsgi on TurnKey Linux
        |
Django 5.2 application
        |
        +-- MariaDB (customers and cached Dotykačka tokens)
        +-- Dotykačka Cloud API
        +-- Google Wallet API / signed save links
        +-- Apple Wallet / OpenSSL-signed .pkpass files
        +-- Brevo contacts API
        +-- SMTP email
```

The deployed baseline uses Python 3.11.2, Django 5.2.1, Apache, and MariaDB
10.11. The source was recovered from the live container on 16 July 2026; no
production deployment was changed while creating this repository.

## Repository layout

```text
.
├── dotykacka/             Loyalty domain, integrations, views, and migrations
│   └── google_wallet/     Google Wallet save-link generation
├── assets/css/            Tailwind source CSS
├── turnkey_app/           Original TurnKey example application
├── turnkey_project/       Django project settings and root URLs
├── templates/             Root landing-page templates
├── static/                Source fonts, CSS, JavaScript, and images
├── mypass_template/       Non-secret Apple Wallet artwork
├── media/                 Runtime data; ignored except for .gitkeep
├── var/logs/              Runtime application logs; ignored
├── add_logo.py            Compatibility entry point for the shared card command
├── RandomImageCropper.py  Compatibility entry point for deterministic generation
├── generate_pass.py       Compatibility entry point for the Wallet command
├── package.json           Pinned build-only frontend dependencies and asset commands
└── manage.py              Django command entry point
```

## Local setup

Install Python 3.11 and the system packages needed by Pillow, cryptography, and
OpenSSL. Then:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
npm ci
npm run build
cp .env.example .env
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
python manage.py runserver
```

Development defaults to SQLite and the console email backend. The registration
page is available at `http://localhost:8000/`; administration is at
`http://localhost:8000/admin/`.

Tenant integrations remain disabled until an authorized tenant owner configures
them in the integration settings page. Never copy production credentials into
Git.

Node is used only to compile/version static assets. It is not part of the Django
production runtime. The compiled CSS and pinned vendor scripts are committed so
the Apache container can run without Node. See `docs/phase-2-portal-shell.md`.

## Mac replica of the TurnKey deployment

For development against a local copy of the deployed database and media, use
the Docker Compose environment. It mirrors Debian 12, Python 3.11, Django
5.2.1, Apache/mod_wsgi, and MariaDB 10.11.11.

The private local replica requires these ignored files copied from the server:

```text
.env
local-data/database.sql.gz
local-data/media/
local-data/mypass_template/
secrets/google-wallet-service-account.json
```

Start it with:

```bash
docker compose up --build -d
docker compose ps
```

Open `http://localhost:8000/`. MariaDB is available to local database tools at
`127.0.0.1:3307` with the application credentials from `.env`.

The SQL dump is imported only when the `loyalty-cards_loyalty-db` volume is
created for the first time. To import a fresh copy later, stop the stack and
remove that named volume before starting again. Removing the volume permanently
deletes the local database copy, so confirm the target carefully.

> [!CAUTION]
> The copied environment contains production integration credentials. Actions
> performed locally can create real Dotykačka customers, change Brevo contacts,
> generate live Wallet objects, and send real email. Do not use real customer
> addresses for development tests unless that external effect is intentional.

## Production dependencies

The TurnKey deployment uses MariaDB, so production also needs the MySQL client
headers and driver:

```bash
python -m pip install -r requirements-production.txt
```

The Apple Wallet generator calls the `openssl` and `zip` command-line tools.
Apache must be configured to load `turnkey_project.wsgi` from the project
virtual environment and to serve static/media paths with appropriate access
controls.

## Configuration

Copy `.env.example` to `.env` and configure the platform-owned groups:

| Group | Important variables |
| --- | --- |
| Django | `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `APP_BASE_URL` |
| Database | `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` |
| Email | `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` |
| Tenant-secret encryption | `TENANT_SECRETS_ENCRYPTION_KEYS` |
| Integration transport | `DOTYKACKA_HTTP_TIMEOUT` |
| Google Wallet platform | `GOOGLE_WALLET_SERVICE_ACCOUNT_FILE`, `GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL`, `GOOGLE_WALLET_ORIGINS` |
| Apple Wallet | `APPLE_WALLET_PASS_TYPE_IDENTIFIER`, `APPLE_WALLET_TEAM_IDENTIFIER` |

For production, use `DJANGO_DEBUG=False`, secure cookies, HTTPS redirect, the
real public origin, and the MariaDB configuration. The TurnKey
`/var/lib/django/allowed_hosts` file is read automatically when present; its
path can be overridden with `TURNKEY_ALLOWED_HOSTS_FILE`.

Dotykačka cloud ID, discount group and authorization token; Brevo list ID, API
key and default phone country; and Google Wallet issuer/class are tenant-owned
database settings. Secrets are Fernet-encrypted and are never shown again after
entry. Migration `0010` reads the old environment values once to initialize
Marta, after which runtime integrations read only the tenant records. See
`docs/phase-1-tenant-configuration.md` for the ownership boundary and key
rotation rules.

## Wallet credentials and runtime assets

Google Wallet expects its service-account JSON at the path configured by
`GOOGLE_WALLET_SERVICE_ACCOUNT_FILE`. The default is:

```text
secrets/google-wallet-service-account.json
```

Apple Wallet signing expects these files at runtime under
`media/mypass_template/`:

```text
AppleWWDR.pem
certificate.pem
key.pem
icon.png
icon@2x.png
logo@2x.png
```

Signing keys, service-account JSON, generated `.pkpass` files, customer images,
and the entire production `media/` tree must be provisioned separately. They
must never be committed.

## Main routes

| Method | Path | Access | Purpose |
| --- | --- | --- | --- |
| `GET` | `/` | Public | Registration landing page |
| `GET`, `POST` | `/dotykacka/register` | Public | Register a loyalty customer |
| `GET`, `POST` | `/dotykacka/c/<tenant-slug>/register` | Public | Tenant registration |
| `GET` | `/accounts/login/` | Public | Client portal login |
| `GET` | `/dotykacka/c/<tenant-slug>/portal` | Tenant member/platform superuser | Client dashboard |
| `GET`, `POST` | `/dotykacka/c/<tenant-slug>/settings/integrations` | Tenant owner/platform superuser | Configure tenant integrations |
| `GET`, `POST` | `/dotykacka/c/<tenant-slug>/settings/card-design` | Tenant owner/platform superuser | Generate proofs and publish immutable design versions |
| `GET` | `/dotykacka/c/<tenant-slug>/artifacts/<id>/download` | Tenant owner/platform superuser | Protected proof/artifact download |
| `GET` | `/dotykacka/platform/print-center` | Platform superuser | Centralized print-center shell and tenant inventory |
| `GET` | `/admin/` | Staff | Django administration |
| `GET` | `/dotykacka/customers` | Superuser | Customer and card operations |
| `POST` | `/dotykacka/send_pass/<barcode>` | Superuser | Send one customer's passes |
| `POST` | `/dotykacka/add_all_to_brevo` | Superuser | Synchronize contacts to Brevo |
| `POST` | `/dotykacka/generate_jwt_passes` | Superuser | Refresh Google Wallet save links |
| `POST` | `/dotykacka/send_passes_to_all` | Superuser | Bulk email all customer passes |

The legacy access-token diagnostic route is restricted to superusers and never
renders the token value.

## Checks

```bash
python manage.py check
python manage.py makemigrations --check
python manage.py test
npm ci
npm run build
```

Tests use an isolated database, block unmocked network/SMTP calls, and cover the
legacy behavior plus tenant migration, authorization, encryption, isolation,
portal fallbacks, pinned static assets, deterministic card output, immutable
artifact retries, Wallet identity, and cross-tenant download denial.

Safe bounded generator commands replace the former standalone loops:

```bash
python manage.py generate_card_artifacts \
  --tenant marta-banaszek-atelier-cafe --start 1 --end 10 --dry-run
python manage.py generate_wallet_passes \
  --tenant marta-banaszek-atelier-cafe --start 1 --end 10 --wallet apple --dry-run
python manage.py verify_card_design_backfill
```

Remove `--dry-run` only after reviewing the tenant, design version, selected
codes, and count. Every run publishes to a new tenant/design/batch/run path;
existing artifacts are never overwritten. See `docs/phase-3-card-designs.md`.

## Security and privacy

- Customer names, phone numbers, email addresses, barcodes, images, card files,
  and bulk-send logs are personal or operational data and stay outside Git.
- API tokens cached in the `AccessToken` table are deliberately hidden from
  Django admin and templates.
- All administrative and bulk routes must remain superuser-only and POST-only
  where they mutate state.
- Rotate any production credential that has previously appeared in source,
  logs, shell output, or an older repository history.
- Use a secret manager or root-readable environment file on TurnKey; never store
  live values in `.env.example`.
- Back up MariaDB and runtime media separately and encrypt those backups.

## Modernization roadmap

The recovered application works, but it needs a production-hardening phase:

1. Add tests for registration, duplicate cards, Dotykačka failures, email, and
   both Wallet integrations.
2. Move email, CRM synchronization, and pass generation from daemon threads to
   a durable job queue with retries and observability.
3. Generate Apple passes on demand and store stable pass serial numbers.
4. Manage Google Wallet classes/objects through a dedicated service layer and
   support card updates.
5. Add consent versioning, privacy retention rules, and customer deletion/data
   export workflows.
6. Replace print statements and PII-heavy CSV logs with structured, redacted
   logging.
7. Add Docker/TurnKey deployment automation, health checks, backups, and CI.
8. Remove the unused TurnKey example app and legacy batch scripts after their
   behavior is covered elsewhere.

## What belongs in Git

Commit source code, migrations, templates, non-secret static artwork,
requirements, documentation, and sanitized configuration examples.

Do not commit `.env`, virtual environments, nested `.git` directories,
databases, media, Google service-account files, Apple signing material,
generated Wallet passes, customer exports, logs, or backups.
