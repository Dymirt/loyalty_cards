# MB Studio Loyalty SaaS

Django loyalty-card SaaS whose first tenant is Marta Banaszek Atelier-Café. The
legacy live service is available at [club.mbstudio.online](https://club.mbstudio.online).

This repository began as a source-only recovery from `/var/www/loyalty_platform`
and now contains the modular SaaS conversion completed through Phase 11. Local
repository work is not automatically deployed to the legacy production service.
Production secrets, customer data, generated cards, Wallet passes, virtual
environments, databases, logs, and nested Git metadata are intentionally
excluded.

## Project status

| Area | Current state |
| --- | --- |
| Technical conversion | Phases 0–11 complete; modular Django platform and operational safety controls implemented |
| Automated baseline | 228 isolated tests pass on MariaDB; the earlier SQLite baseline has three expected database-specific skips |
| First tenant | Marta Banaszek Atelier-Café: 267 customers and 600 cards, of which 267 are assigned and 333 are available |
| Rollout | Additional paying tenants remain disabled until Marta completes the human acceptance checklist |
| Known provider issue | Marta's last stored Brevo result is `brevo_unauthorized`; it requires an explicit test or replacement of only her encrypted tenant key |
| Commercial/production inputs | Real printer specification, prices, limits, tax/shipping/payment ownership, and historical fulfillment ranges still require approval |

The current rollout work is tracked in [PLAN.md](PLAN.md). The completed
Phase 0–11 implementation history is preserved in
[docs/archive/saas-conversion-plan-phases-0-11.md](docs/archive/saas-conversion-plan-phases-0-11.md).
Phase 11 evidence and the first-tenant checklist are in
[docs/phase-11-production-hardening.md](docs/phase-11-production-hardening.md)
and [docs/runbooks/marta-acceptance.md](docs/runbooks/marta-acceptance.md).

## Product model and terminology

The product has two deliberately separate operating surfaces:

- The **tenant portal** lets a business manage its brand, card design,
  registration, Wallet presentation, POS/communications connections, billing
  view, and print requests.
- The **platform operations portal** lets MB Studio review proofs, approve and
  allocate immutable card batches, download protected production packages, and
  record printing, delivery, or compensating corrections.

| Term | Meaning |
| --- | --- |
| Tenant | A paying SaaS business, such as Marta Banaszek Atelier-Café |
| Customer or loyalty member | A person receiving that tenant's loyalty card |
| Platform operator | Authorized MB Studio staff operating the central print and SaaS service |

Printing is centralized. A tenant can approve a design and submit a request,
but only a platform superuser can download a production package or record
production and fulfillment. Historical events are append-only; corrections do
not rewrite the original event.

## Engineering invariants

- Never drop, truncate, reset, silently overwrite, or broadly delete database
  records, customer media, generated artifacts, Wallet identities, or historical
  integration state.
- Every schema or data transition uses a reviewed, forward Django migration.
  Migrations must be additive/state-preserving and must never call an external
  provider. Historical `dotykacka` migrations and tables remain intact.
- The approved runtime stack is Python, Django, HTMX and Tailwind CSS. Use
  ordinary server-rendered HTML as the fallback and JavaScript only for a
  browser capability that HTMX cannot provide.
- Keep one modular Django project and one primary database by default. Do not add
  an SPA, Redis, Celery, another runtime, or a payment provider without explicit
  approval and a demonstrated need. Durable background work uses database-backed
  jobs and separately supervised Django commands.
- Do not introduce PDF/sheet imposition until a real printer specification
  proves it necessary. Production formats are versioned and immutable.
- Never render or log API keys, connector secrets, refresh/access tokens,
  signing keys, customer data, or secret hashes. Tests and migrations must not
  cause unapproved network, SMTP, Wallet, POS, or production-print side effects.

## Current capabilities

- Tenant-branded loyalty-card registration by verified domain, explicit slug or globally unique card prefix, with barcode scanning.
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
- Immutable billing quotes, entitlement/pack consumption, and append-only physical-production usage.
- Tenant print requests, centralized platform approval/allocation, validated production ZIPs, and append-only fulfillment/corrections.
- Immutable enrollment/consent snapshots, expiring signed Wallet status links, and authorized follow-up retry/resend controls.
- Guarded email-delivery generations that block automatic replay when SMTP has an uncertain outcome.
- Public product, feature, integration, published-pricing, contact and legal pages rendered by Django/Tailwind.
- Read-only public billing projections that exclude drafts and tenant-specific commercial/customer data.
- Idempotent append-only marketing leads with exact versioned consent evidence and ordinary HTML/HTMX form behavior.
- A separately supervised database-backed print worker; no Redis or Celery runtime was added.
- Protected customer media, bounded uploads, database-backed public/connect rate limits, CSP/permissions/privacy headers, request IDs, and redacted JSON logs.
- Public liveness/readiness probes plus a superuser operations console with worker heartbeats and append-only alert acknowledgement/resolution history.
- Transaction-consistent MariaDB/runtime backup commands, checksum manifests, a nightly timer definition, and documented disposable restore drills.

## Runtime architecture

```text
Browser / mobile device
        |
Cloudflare + HTTPS
        |
Apache + mod_wsgi        integration worker       print worker       operations monitor
        |                       |                      |                    |
        +-----------------------+----------------------+--------------------+
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

The deployed baseline uses Python 3.11, Django 5.2.16, Apache, and MariaDB
10.11. The source was recovered from the live container on 16 July 2026; no
production deployment was changed while creating this repository.

## Domain boundaries

The codebase is a modular monolith. Dependencies point from reusable domain
primitives toward provider and workflow implementations, not back into legacy
views or higher-level orchestration:

```text
core
└── tenants
    ├── customers ── cards ── card_artwork
    ├── integrations
    │   ├── pos ── pos_dotykacka
    │   └── communications ── brevo
    ├── wallets ── wallet_apple / wallet_google
    └── billing ── printing

enrollment  -> explicit domain/provider services and durable jobs
marketing   -> read-only projection of published billing data
operations  -> read-only health plus append-only monitoring/alert actions
```

Provider apps implement neutral contracts; provider-specific response shapes
do not leak into tenant, customer, card, billing, or printing models. Billing
does not import printing, and card artwork does not fulfill requests.
Cross-domain workflows use explicit services, transactions and `on_commit`
handoffs rather than model signals with hidden external effects.

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
├── billing/, printing/    Entitlements/quotes plus centralized production and fulfillment
├── enrollment/            Tenant registration, consent snapshots, signed links, and follow-up orchestration
├── marketing/             Public site, published-price projection, legal pages, and append-only leads
├── operations/            Security middleware, protected media, health, alerts, heartbeats and backups
├── core/                  Extraction inventory and dependency safety rails
├── dotykacka/             Historical model/migration owner and thin compatibility shell
├── assets/css/            Tailwind source CSS
├── turnkey_app/           Historical source only; not installed or imported by active URLs
├── turnkey_project/       Deprecated import compatibility shim
├── templates/             Shared portal/marketing shell and compatibility templates
├── static/                Source fonts, CSS, JavaScript, and images
├── deploy/systemd/        Backup/monitor service and timer definitions
├── docs/runbooks/         Operator, client, billing, fulfillment, restore and acceptance procedures
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
# In a second supervised process:
python manage.py run_print_worker
# In a third supervised process:
python manage.py run_operational_monitor
```

Development defaults to SQLite and the console email backend. The marketing site
is available at `http://localhost:8000/`, loyalty registration at
`http://localhost:8000/dotykacka/register`, and administration at
`http://localhost:8000/admin/`.

Tenant integrations remain disabled until an authorized tenant owner configures
them in the integration settings page. Never copy production credentials into
Git.

Node is used only to compile/version static assets. It is not part of the Django
production runtime. The compiled CSS and pinned vendor scripts are committed so
the Apache container can run without Node. See `docs/phase-2-portal-shell.md`.

## Interface language

The launch interface is entirely Polish and `pl` is the only enabled language.
Django locale middleware, translation markers in active templates/Python UI
messages, and a project locale directory are already in place so another
language can be added without changing domain data or the frontend stack. The
language selector remains hidden until a complete second catalog is approved.
See [docs/localization.md](docs/localization.md) for the catalog workflow and
review rules.

## Mac replica of the deployed service

For development against a local copy of the deployed database and media, use
the Docker Compose environment. It mirrors Debian 12, Python 3.11, Django
5.2.16, Apache/mod_wsgi, and MariaDB 10.11.11.

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
Apache must load `loyalty_platform.wsgi` from the project virtual environment
and serve only collected static assets directly. Runtime media is authorized by
Django; do not add a broad Apache `/media/` alias.

## Continuous delivery

GitHub Actions runs the full isolated CI suite on every pull request and push to
`main`, including a MariaDB 10.11 job matching production. After the exact
`main` commit passes CI, the production workflow can deploy it through a
dedicated least-privilege SSH account.

The deployment uses versioned releases, keeps production secrets and runtime
data only on the server, creates a verified backup before migration, validates
before/after tenant aggregates, switches Apache atomically, supervises all
workers with systemd, checks public health, and restores the previous code if
startup fails. See [docs/runbooks/deployment.md](docs/runbooks/deployment.md)
for bootstrap, GitHub settings, release flow and rollback instructions.

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
| Protected storage | `MEDIA_ROOT`, `PRINT_PACKAGE_ROOT` (print packages must remain outside media and all web-server aliases) |
| Enrollment | `ENROLLMENT_LINK_TTL_DAYS` (finite signed status-link lifetime; default 30) |
| Public marketing/legal | `MARKETING_LEGAL_NAME`, `MARKETING_LEGAL_ADDRESS`, `MARKETING_CONTACT_EMAIL`, `MARKETING_PRIVACY_VERSION`, `MARKETING_TERMS_VERSION` |
| HTTPS/security | `DJANGO_SECURE_SSL_REDIRECT`, secure-cookie/HSTS flags, `DJANGO_TRUST_X_FORWARDED_PROTO`, `LOYALTY_TRUSTED_PROXY_CIDRS`, upload bounds and rate limits |
| Operations | heartbeat/monitor thresholds, entitlement/inventory warnings, retention review and `BACKUP_ROOT` |

Configuration ownership is intentional:

| Owner | Configuration |
| --- | --- |
| Platform environment/secret store | Django/database/SMTP settings; tenant-secret encryption keys; Dotykačka Client Application ID and secret; Google issuer and signing service account; Apple identifiers and signing material; storage and operational settings |
| Encrypted tenant database settings | Dotykačka Connector-returned authorization/Refresh Token, locked Cloud ID and discount group; Brevo API key, list ID and default phone country; integration enablement and safe status metadata |
| Ordinary tenant database settings | Tenant identity, brand, card design, domain/prefix, locale and other non-secret business configuration |

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
registration. One Client Application can connect multiple independent tenant
clouds. These values are not interchangeable with a Cloud ID or the
authorization/Refresh Token returned after a tenant logs in and approves its
cloud. The system-connections check names a missing environment variable
without exposing any credential value.

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

### Durable product decisions

- The first tenant's display brand is **Marta Banaszek Atelier-Café**. Its legal
  billing entity is **CENTRUM CONCEPT SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ**;
  display and legal names must not be silently merged.
- Card prefixes are globally unique. Marta retains the historical `MB` prefix.
- The local database is the business source of truth. External provider IDs,
  synchronization results and retry state are mirrored locally and remain
  auditable.
- A platform user can belong to more than one tenant, with an explicit role per
  membership. Tenant queries and downloads always require tenant scoping.
- Apple and Google Wallet issuer/signing accounts are platform-owned. The card's
  visible brand, colors, text and customer data come from an immutable tenant
  design snapshot.
- No price, plan assignment, tax/shipping rule, production cost, payment
  provider, invoice status, or legacy delivery event may be invented. These are
  published or appended only from an approved commercial/operator decision.
- Marta's historical `MB-1..600` production and delivery state remains unchanged
  until the operator confirms exact ranges, dates and references through the
  no-write reconciliation preview.

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

Production print ZIPs are stored separately under `PRINT_PACKAGE_ROOT` (default
`var/print-packages`) and streamed only by the audited superuser view. Never put
that root below `MEDIA_ROOT` or expose it with an Apache/static-media alias.

See `docs/apple-wallet-certificate-renewal.md` for the Pass Type ID certificate
renewal and deployment procedure.

## Main routes

| Method | Path | Access | Purpose |
| --- | --- | --- | --- |
| `GET` | `/` | Public | Marketing homepage and published-plan summary |
| `GET` | `/funkcje/` | Public | Product features and operating workflow |
| `GET` | `/integracje/` | Public | Supported POS, Wallet and communication capabilities |
| `GET` | `/cennik/` | Public | Active published plans and public production pricing |
| `GET`, `POST` | `/kontakt/` | Public | Consent-gated, idempotent contact lead form |
| `GET` | `/polityka-prywatnosci/`, `/regulamin/` | Public | Versioned legal pages |
| `GET` | `/turnkey/`, `/marketing/` | Public | Permanent compatibility redirects to `/` |
| `GET`, `POST` | `/dotykacka/register` | Public | Register a loyalty customer |
| `GET`, `POST` | `/dotykacka/c/<tenant-slug>/register` | Public | Tenant registration |
| `GET` | `/dotykacka/enrollment/status/<signed-token>` | Public capability link | Expiring redacted Wallet and follow-up status |
| `GET` | `/dotykacka/enrollment/status/<signed-token>/apple-pass` | Public capability link | Download the prepared Apple pass before link expiry |
| `GET` | `/accounts/login/` | Public | Client portal login |
| `GET` | `/health/live`, `/health/ready` | Public | Redacted supervisor/load-balancer liveness and readiness |
| `GET` | `/dotykacka/c/<tenant-slug>/portal` | Tenant member/platform superuser | Client dashboard |
| `GET` | `/dotykacka/c/<tenant-slug>/enrollments` | Tenant owner/platform superuser | Enrollment, domain-request and durable follow-up history |
| `POST` | `/dotykacka/c/<tenant-slug>/enrollments/<id>/*` | Tenant owner/platform superuser | Ensure missing jobs, retry a failed provider job, or explicitly resend email |
| `GET` | `/dotykacka/c/<tenant-slug>/billing` | Tenant owner/platform superuser | Subscription, usage, packs and immutable quote history |
| `POST` | `/dotykacka/c/<tenant-slug>/billing/quotes` | Tenant owner/platform superuser | Calculate allowance → pack → tier → shipping/tax (HTMX or normal POST) |
| `POST` | `/dotykacka/c/<tenant-slug>/billing/quotes/<id>/accept` | Tenant owner/platform superuser | Accept and freeze a quote and reserve proposed pack quantities |
| `GET` | `/dotykacka/c/<tenant-slug>/printing` | Tenant owner/platform superuser | Review and submit print requests from an accepted quote and published proof |
| `POST` | `/dotykacka/c/<tenant-slug>/printing/requests` | Tenant owner/platform superuser | Submit one idempotent immutable print request |
| `GET`, `POST` | `/dotykacka/c/<tenant-slug>/settings/integrations` | Tenant owner/platform superuser | Configure tenant integrations |
| `POST` | `/integrations/dotykacka/<tenant-slug>/connect` | Tenant owner/platform superuser | Start the tenant-authorized Connector v2 POST flow |
| `GET` | `/integrations/dotykacka/callback` | Initiating tenant owner/platform superuser | Verify state and store the encrypted Refresh Token and locked Cloud ID |
| `POST` | `/integrations/dotykacka/<tenant-slug>/disconnect` | Tenant owner/platform superuser | Disable the integration, clear active authorization and unlock Cloud selection without deleting history |
| `POST` | `/dotykacka/c/<tenant-slug>/settings/integrations/<provider>/test` | Tenant owner/platform superuser; Dotykačka platform-only | HTMX/plain-HTML connection test |
| `GET`, `POST` | `/dotykacka/c/<tenant-slug>/settings/card-design` | Tenant owner/platform superuser | Generate proofs and publish immutable design versions |
| `GET` | `/dotykacka/c/<tenant-slug>/artifacts/<id>/download` | Tenant owner/platform superuser | Protected proof/artifact download |
| `GET` | `/dotykacka/platform/print-center` | Platform superuser | Filtered centralized request queue, inventory and legacy no-write preview |
| `GET`, `POST` | `/dotykacka/platform/print-center/requests/<id>[/*]` | Platform superuser | Review, approve/reject, allocate, monitor, fulfill or compensate a print request |
| `GET` | `/dotykacka/platform/print-center/packages/<id>/download` | Platform superuser | Download an audited, size/checksum-validated immutable production ZIP |
| `GET`, `POST` | `/dotykacka/platform/billing` | Platform superuser | Publish plan/price versions and assign subscriptions/packs |
| `GET`, `POST` | `/dotykacka/platform/operations` | Platform superuser | Detailed health, safe provider configuration and append-only alert handling |
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
python manage.py check --deploy --fail-level WARNING
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py verify_app_extraction --strict --expect-marta
python manage.py verify_saas_rollout --expect-marta
python manage.py test --noinput
python manage.py run_print_worker --once
python manage.py run_operational_monitor --once
python manage.py create_platform_backup --label scheduled
python manage.py verify_platform_backup /protected/path/manifest.json
npm ci
npm run build
pip-audit -r requirements-production.txt
npm audit --audit-level=high
```

Use `--expect-marta` only on the protected first-tenant replica. Phase 11
evidence and the remaining human rollout gate are in
`docs/phase-11-production-hardening.md` and
`docs/runbooks/marta-acceptance.md`.

Tests use an isolated database, block unmocked network/SMTP calls, and cover the
legacy behavior plus tenant migration, authorization, encryption, isolation,
portal fallbacks, pinned static assets, deterministic card output, immutable
artifact retries, Connector state/401/429 behavior, Brevo consent/duplicates,
durable worker recovery, Wallet identity, and cross-tenant download denial.
Billing coverage adds seat/card limits, usage idempotency, allowance/pack/tier
boundaries, decimal/currency calculations, role isolation, and frozen quotes.
Printing coverage adds request/job idempotency, frozen proof/design/quote/layout
snapshots, transactional allocation and quote consumption, manifest/file checksums,
platform authorization, controlled fulfillment/corrections and legacy no-write preview.
Enrollment coverage adds domain/slug/prefix tenant resolution, locked card assignment,
frozen brand and consent evidence, post-commit follow-ups, expiring signed links,
tenant-isolated retry/resend actions and ambiguous-email replay protection.
Marketing coverage adds active/latest-published filtering, draft and tenant-data
exclusion, truthful empty pricing, ordinary/HTMX form paths, idempotent consent
evidence, append-only enforcement, legal configuration checks and direct legacy redirects.
Operations coverage adds safe headers/log redaction, authorization-aware media,
rate limits, redacted health, alert lifecycle, heartbeat handling and backup
checksum/archive verification. The complete suite currently contains 228 tests.

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

## Completed modernization history

| Phases | Delivered outcome |
| --- | --- |
| 0–3 | Safety tests, tenant/Marta foundation, Django/HTMX/Tailwind portal, versioned designs and unified bounded generators |
| 4–5 | Project rename safety rails and extraction of tenants, customers, cards and artwork into owned Django domains |
| 6–7 | Provider-neutral POS/communications/Wallet integrations, encrypted tenant credentials, durable jobs, billing, entitlements and immutable pricing |
| 8–9 | Central print request/production/fulfillment and durable tenant enrollment/follow-up workflows |
| 10–11 | Public marketing/published pricing plus production security, monitoring, backups, CI, restore drills and rollout runbooks |

The detailed completed plan, including acceptance evidence and preserved
decisions, is archived at
[docs/archive/saas-conversion-plan-phases-0-11.md](docs/archive/saas-conversion-plan-phases-0-11.md).
The active [PLAN.md](PLAN.md) begins with Phase 12: Marta acceptance, commercial
and printer certification, a second-tenant pilot, and measured compatibility
retirement. Technical rollout checks pass, but launch still requires the human
and provider gates described there.

## What belongs in Git

Commit source code, migrations, templates, non-secret static artwork,
requirements, documentation, and sanitized configuration examples.

Do not commit `.env`, virtual environments, nested `.git` directories,
databases, media, Google service-account files, Apple signing material,
generated Wallet passes, customer exports, logs, or backups.
