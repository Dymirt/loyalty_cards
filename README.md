# MB Studio Loyalty SaaS

Django loyalty-card SaaS whose first tenant is Atelier-Café Marta Banaszek. The
legacy live service is available at [club.mbstudio.online](https://club.mbstudio.online).

This repository is a source-only snapshot of the complete application deployed
from `/var/www/loyalty_platform` on the legacy production container. Production secrets,
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
- Domain-owned tenant/customer/card/artwork services with legacy import and URL compatibility.
- Master-image sample sheets, immutable exact crop plans, customer external identities, and append-only consent evidence.
- Stable Apple Wallet serials and Google Wallet object identities per tenant customer.
- Dotykačka Connector v2 onboarding with HMAC-signed POST, tenant/session-bound CSRF state, encrypted cloud token cache, 401 refresh and customer reconciliation.
- Consent-gated Brevo upsert/list sync with rate-limit-aware retries and no automatic force-merge.
- Durable tenant-scoped provider jobs claimed by a separately supervised Django worker.

## Runtime architecture

```text
Browser / mobile device
        |
Cloudflare + HTTPS
        |
Apache + mod_wsgi        supervised Django job worker
        |                         |
        +------------+------------+
        |
Django 5.2 application
        |
        +-- MariaDB (domain data, encrypted provider tokens, durable jobs)
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
├── loyalty_platform/      Active Django settings, root URLs, ASGI/WSGI, and test runner
├── tenants/, customers/   Tenant/customer behavior, external identities, consent evidence
├── cards/, card_artwork/  Card inventory, deterministic renderer, crop plans, and artifact command
├── integrations/          Encrypted credential primitive, durable jobs, settings/worker orchestration
├── pos/, pos_dotykacka/   POS contract and Dotykačka Connector v2/customer adapter
├── communications/, brevo/ Contact contract, email delivery, and Brevo adapter
├── wallets/, wallet_*/    Stable Wallet identities plus Apple/Google implementations
├── core/                  Extraction inventory and dependency safety rails
├── dotykacka/             Historical model/migration owner and thin compatibility shell
├── assets/css/            Tailwind source CSS
├── turnkey_app/           Deprecated `/turnkey/` redirect compatibility shim
├── turnkey_project/       Deprecated import compatibility shim
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
# In another supervised process:
python manage.py run_integration_worker
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

## Mac replica of the deployed service

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

The production deployment uses MariaDB, so it also needs the MySQL client
headers and driver:

```bash
python -m pip install -r requirements-production.txt
```

The Apple Wallet generator calls the `openssl` and `zip` command-line tools.
Apache must be configured to load `loyalty_platform.wsgi` from the project
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
| Integration transport | `INTEGRATION_HTTP_RETRIES`, `DOTYKACKA_HTTP_TIMEOUT`, `BREVO_HTTP_TIMEOUT` |
| Dotykačka platform | `DOTYKACKA_CONNECTOR_CLIENT_ID`, `DOTYKACKA_CONNECTOR_CLIENT_SECRET`, `DOTYKACKA_CONNECTOR_URL`, `DOTYKACKA_API_BASE_URL` |
| Google Wallet platform | `GOOGLE_WALLET_SERVICE_ACCOUNT_FILE`, `GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL`, `GOOGLE_WALLET_ISSUER_ID`, `GOOGLE_WALLET_ORIGINS`, `GOOGLE_WALLET_API_BASE_URL` |
| Apple Wallet | `APPLE_WALLET_PASS_TYPE_IDENTIFIER`, `APPLE_WALLET_TEAM_IDENTIFIER` |

For production, use `DJANGO_DEBUG=False`, secure cookies, HTTPS redirect, the
real public origin, and the MariaDB configuration. The legacy host’s
`/var/lib/django/allowed_hosts` file is read automatically when present; its
path can be overridden with `LOYALTY_ALLOWED_HOSTS_FILE`.
`TURNKEY_ALLOWED_HOSTS_FILE` remains a deprecated fallback for one release.

Dotykačka Refresh Token, cloud ID and discount group; and Brevo list ID, API
key and default phone country are tenant-owned database settings. The Refresh
Token returned by Connector is encrypted on its tenant connection and exchanged
with that tenant's Cloud ID for a short-lived, cloud-scoped access token. It is
never rendered after authorization. Google Wallet uses the
platform issuer from `GOOGLE_WALLET_ISSUER_ID`; a tenant's class identity is
derived internally from its unique card prefix, while visible Wallet content
comes from tenant branding. Migration `0010` reads old environment values once
to initialize Marta. Migration `0014` promotes Marta's historical encrypted
authorization value to the canonical tenant `refresh_token` key without
deleting the legacy value. Runtime tenant settings then read database records. See
`docs/phase-1-tenant-configuration.md` for the ownership boundary and key
rotation rules.

`DOTYKACKA_CONNECTOR_CLIENT_ID` and `DOTYKACKA_CONNECTOR_CLIENT_SECRET` are the
two platform Client Application credentials issued by Dotykačka after
registration. They are not interchangeable with a tenant Cloud ID or tenant
Refresh Token. The system-connections check names a missing environment
variable without exposing any credential value.

Superusers can run redacted, non-destructive infrastructure checks at
`/dotykacka/platform/system-connections`. Google Wallet is tested with a
read-only issuer request; SMTP authenticates without sending a message; Apple
Wallet validates signing material; active Dotykačka clouds are tested with
their encrypted tenant Refresh Tokens and database-owned Cloud IDs; and active Brevo
connections are tested from their encrypted database credentials.

Dotykačka onboarding lives on each tenant's integration settings page. An
authorized tenant owner starts the browser-based Connector flow, logs into
Dotykačka and selects the company cloud. The resulting Cloud ID remains locked
and cannot be edited or replaced until that tenant explicitly disconnects the
integration. Connector credentials and Refresh Tokens are never rendered.

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

See `docs/apple-wallet-certificate-renewal.md` for the Pass Type ID certificate
renewal and deployment procedure.

## Main routes

| Method | Path | Access | Purpose |
| --- | --- | --- | --- |
| `GET` | `/` | Public | Registration landing page |
| `GET`, `POST` | `/dotykacka/register` | Public | Register a loyalty customer |
| `GET`, `POST` | `/dotykacka/c/<tenant-slug>/register` | Public | Tenant registration |
| `GET` | `/accounts/login/` | Public | Client portal login |
| `GET` | `/dotykacka/c/<tenant-slug>/portal` | Tenant member/platform superuser | Client dashboard |
| `GET` | `/dotykacka/c/<tenant-slug>/billing` | Tenant owner/platform superuser | Subscription, usage, packs and immutable quote history |
| `POST` | `/dotykacka/c/<tenant-slug>/billing/quotes` | Tenant owner/platform superuser | Calculate allowance → pack → tier → shipping/tax (HTMX or normal POST) |
| `POST` | `/dotykacka/c/<tenant-slug>/billing/quotes/<id>/accept` | Tenant owner/platform superuser | Accept and freeze a quote and reserve proposed pack quantities |
| `GET`, `POST` | `/dotykacka/c/<tenant-slug>/settings/integrations` | Tenant owner/platform superuser | Configure tenant integrations |
| `POST` | `/integrations/dotykacka/<tenant-slug>/connect` | Tenant owner/platform superuser | Start the tenant-authorized Connector v2 POST flow |
| `GET` | `/integrations/dotykacka/callback` | Initiating tenant owner/platform superuser | Verify state and store the encrypted Refresh Token and locked Cloud ID |
| `POST` | `/integrations/dotykacka/<tenant-slug>/disconnect` | Tenant owner/platform superuser | Disable the integration, clear active authorization and unlock Cloud selection without deleting history |
| `POST` | `/dotykacka/c/<tenant-slug>/settings/integrations/<provider>/test` | Tenant owner/platform superuser; Dotykačka platform-only | HTMX/plain-HTML connection test |
| `GET`, `POST` | `/dotykacka/c/<tenant-slug>/settings/card-design` | Tenant owner/platform superuser | Generate proofs and publish immutable design versions |
| `GET` | `/dotykacka/c/<tenant-slug>/artifacts/<id>/download` | Tenant owner/platform superuser | Protected proof/artifact download |
| `GET` | `/dotykacka/platform/print-center` | Platform superuser | Centralized print-center shell and tenant inventory |
| `GET`, `POST` | `/dotykacka/platform/billing` | Platform superuser | Publish plan/price versions and assign subscriptions/packs |
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
python manage.py verify_app_extraction --strict
python manage.py test
npm ci
npm run build
```

Use `--expect-marta` only on the protected first-tenant replica. See
`docs/phase-7-billing-entitlements.md` for the current additive schema contract,
compatibility map, verification results, and rollback procedure.

Tests use an isolated database, block unmocked network/SMTP calls, and cover the
legacy behavior plus tenant migration, authorization, encryption, isolation,
portal fallbacks, pinned static assets, deterministic card output, immutable
artifact retries, Connector state/401/429 behavior, Brevo consent/duplicates,
durable worker recovery, Wallet identity, and cross-tenant download denial.
Billing coverage adds seat/card limits, usage idempotency, allowance/pack/tier
boundaries, decimal/currency calculations, role isolation, and frozen quotes.

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
- Historical plaintext-compatible `AccessToken` rows are retained unchanged and
  hidden from Django admin/templates. All new runtime Dotykačka access tokens use
  encrypted, expiring, cloud-scoped `DotykackaAccessToken` records.
- All administrative and bulk routes must remain superuser-only and POST-only
  where they mutate state.
- Rotate any production credential that has previously appeared in source,
  logs, shell output, or an older repository history.
- Use a secret manager or root-readable environment file on the host; never store
  live values in `.env.example`.
- Back up MariaDB and runtime media separately and encrypt those backups.

## Modernization roadmap

Phases 0–7 provide the test safety net, tenant/Marta backfill, HTMX/Tailwind
portal, unified generators, modular safety rails, domain extraction, provider
adapters, durable jobs, and subscription/entitlement/pricing foundation. The remaining printing, enrollment,
marketing, and production-hardening sequence is maintained in `PLAN.md`.

## What belongs in Git

Commit source code, migrations, templates, non-secret static artwork,
requirements, documentation, and sanitized configuration examples.

Do not commit `.env`, virtual environments, nested `.git` directories,
databases, media, Google service-account files, Apple signing material,
generated Wallet passes, customer exports, logs, or backups.
