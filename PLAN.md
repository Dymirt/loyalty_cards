# MB Studio Loyalty SaaS Conversion Plan

Status: in progress — Phases 0–3 complete; roadmap revised for modular extraction

Prepared: 2026-07-17

Application: Django loyalty-card service at `mbstudio-loyalty-app`

Progress: Phases 0–3 implemented and verified on the backed-up local MariaDB replica on 2026-07-17; migrations `0008` through `0013` are applied. Phase 3 added only versioned design, artifact, Wallet identity, and nullable batch-design metadata.

## 1. Product outcome

Turn the existing Marta Banaszek / Atelier-Café application into a multi-tenant SaaS product and a maintainable Django modular monolith while preserving the working first-client installation and every existing database record and generated card asset.

The product will have two operational sides:

1. **Client portal** — each SaaS client configures its brand, card design, registration experience, Wallet content, POS connection, and submits physical-card print requests.
2. **Platform operations** — the application administrator reviews client proofs, generates immutable card batches, downloads production print packages, prints the cards centrally, and records fulfillment.

The codebase will be decomposed into domain-owned Django apps inside this Django project. This is an internal boundary change, not a microservice rewrite: one Python/Django deployment and one database remain the default. The applications communicate through explicit service interfaces and model references, not network APIs.

Interpretation of the printing requirement: SaaS clients can preview and approve their designs and request printing, but only platform administrators can download production-ready print packages. This protects centralized card allocation and printing. A future permission may allow selected clients to download print files if that is later required.

## 2. Non-negotiable constraints

- Do not delete, truncate, reset, replace, or overwrite production or replica database data.
- Every database schema or data transformation must be performed by a reviewed Django migration.
- Use additive, forward-only migrations for the SaaS conversion. Production rollback means deploying compatible application code, not reversing data migrations.
- Never regenerate or overwrite a legacy card, crop, barcode, or Wallet pass during migration. Import them as immutable legacy assets.
- Preserve the current Python, Django, HTMX, and Tailwind stack.
- Do not introduce a frontend framework, SPA, or another runtime stack.
- Use HTMX for page interactions. Use JavaScript only where browser APIs make it unavoidable; the existing camera/barcode scanner is the accepted case.
- Do not add Celery, Redis, or another queue technology without explicit approval. Use a Django/database-backed work queue and a Django management-command worker initially.
- Do not add a print/PDF dependency without approval. Start from the existing Pillow capability; request approval only if confirmed printer requirements need PDF features Pillow cannot reliably provide.
- Never expose POS, Wallet, email, or signing credentials in templates, logs, audit payloads, or downloadable files.
- No migration may call Dotykačka, Brevo, SMTP, Google Wallet, Apple services, or any other external service.
- Keep a single Django project and deployment unless a future measured production constraint justifies another service and the change is separately approved.
- Do not rename historical migration files or delete the legacy `dotykacka` migrations. New apps receive new migrations; existing tables move only through reviewed state-preserving migrations.

## 3. Verified current baseline

The following was verified read-only against the running local replica on 2026-07-17:

| Area | Current state |
| --- | --- |
| Django | 5.2.1; `manage.py check` passes after Phase 3 |
| Database | MariaDB replica with migrations `0008` through `0013` applied |
| Application users | 1 active user: `admin`; staff and superuser |
| Loyalty customers | 267 `Klient` records |
| Card identifiers | 267 valid `MB-*` numeric codes, range `MB-1` through `MB-494`; no duplicates and no empty IDs |
| Cached POS tokens | 262 tenant-owned append-only `AccessToken` records after a normal refresh |
| Physical card inventory | Complete assets for `MB-1` through `MB-600` |
| Per-card legacy assets | front image, back image, barcode PNG, cropped background, and Apple `.pkpass` all present |
| Expected imported inventory | 600 Marta cards: 267 assigned, 333 available |
| Tests | 80 automated tests covering the legacy baseline, migrations, tenancy, roles, integrations, portal, deterministic generators, immutable artifacts, Wallet identity, and golden output |
| UI | Accessible server-rendered Django/HTMX portal with locally compiled Tailwind and no runtime CDN on active loyalty routes |
| Working tree | Existing uncommitted Docker, configuration, README, and Wallet-path work must be preserved |

### Current helper and workflow inventory

| Existing code | Current purpose | SaaS destination |
| --- | --- | --- |
| `RandomImageCropper.py` | Random card-size crops from a master background | `card_artwork.services`; reproducible crop plans, tenant-scoped previews, and immutable artifacts |
| `add_logo.py` / `CardGenerator` | Logo, text, barcode, front/back JPEG generation | `card_artwork.services.PhysicalCardRenderer`; configuration comes from a versioned tenant card design |
| `generate_manifest.py` | Standalone Apple manifest generation | Internal method of `wallet_apple`; remove the duplicate execution path only after parity tests |
| `generate_pass.py` | Legacy batch Apple pass generation from CLI | Thin Django management command calling `wallet_apple` |
| `dotykacka/apple_wallet_pass.py` | In-app Apple `.pkpass` generation | `wallet_apple`; stable serial numbers, platform signing credentials, and tenant-owned content |
| `dotykacka/google_wallet/JWT.py` | Google Wallet save URL generation | `wallet_google`; platform issuer credentials and tenant-owned class/content configuration |
| `dotykacka/api_utils.py` | Dotykačka authentication/customer creation | `pos_dotykacka`; Connector v2 onboarding and a tenant-aware adapter behind the `pos` contract |
| `dotykacka/brevo.py` | Brevo contact synchronization | `brevo`; tenant API key/list configuration behind the `communications` contract |
| Bulk actions in `views.py` | Global generation, sync, and email loops | Authorized service calls and durable database jobs scoped to one tenant or platform batch |

Existing CLI workflows will remain available as Django management commands, but both CLI commands and web actions will call the same service layer. There must be only one implementation of each generator.

## 4. Remaining gaps before calling the app SaaS-ready

### Data, tenancy, and boundaries

- The tenant foundation and Marta backfill exist, but all business models still have the legacy `dotykacka` app label and most forms/views/admin/provider code remain in that one app.
- `Klient` means a loyalty-program customer, not a SaaS client; use the code/UI term `Customer` before considering a risky model/table rename.
- The current global customer/admin workflow still treats Dotykačka as a list source in places instead of consistently using the tenant-scoped local database as source of truth.
- Existing uniqueness is globally strict for the verified prefix/code strategy. Any move to tenant-composite uniqueness must be a deliberate migration and must not weaken globally unique scannable card codes accidentally.

### Card, artwork, and Wallet generation

- Phase 3 introduced versioned tenant design, stable Wallet identity and immutable artifacts, but the implementation is still under `dotykacka` and legacy standalone helpers remain parallel entry points.
- Deterministic background variation exists, but the target editor still needs an explicit persisted `CropPlan`/sample-sheet workflow for exact source coordinates and operator review.
- Legacy generated assets must remain readable while all new and production downloads move through tenant-authorized protected views.
- Apple/Google implementation must be separated into provider apps with centralized platform signing/issuer secrets and tenant-owned visible content.

### Registration and operations

- Registration form/code/race fixes exist, but versioned consent evidence is not yet a first-class record.
- Daemon threads can still lose POS sync, Wallet generation, and email work when the web process restarts; durable database jobs are not implemented yet.
- Tenant integration credentials are encrypted, but the `AccessToken` cache model still stores token text without explicit expiry/invalidation and must become connection/cloud scoped.
- The portal shell is Tailwind/HTMX, but legacy routes and bulk views still coexist and need domain extraction plus consistent authorization/job behavior.

### Application structure and product operations

- Nearly all domain models, forms, views, provider adapters, Wallet code, card generation, and admin behavior still live under the `dotykacka` app even after their services were stabilized.
- `turnkey_project`, `turnkey_app`, `/turnkey/`, and `TURNKEY_ALLOWED_HOSTS_FILE` no longer describe the product. The project package name leaks into deployment entry points and tests.
- There is no subscription, entitlement, metered-usage, price-book, quote, or card-pack model, so user limits and print overages cannot be enforced consistently.
- Existing legacy cards have inventory state but no append-only printing/delivery record that an operator can safely backfill without altering assignment or regenerating files.
- Public marketing and pricing pages have no bounded owner and should not be mixed into the authenticated tenant portal.

## 5. Target Django modular-monolith architecture

### Naming and project package

- Rename the Django project configuration package from `turnkey_project` to `loyalty_platform`. This is a code/deployment rename; it must not rename database tables or historical migrations.
- Replace the unused `turnkey_app` demo with the future `marketing` app. Remove `/turnkey/` only after adding a temporary redirect and checking that no production link depends on it.
- Update `manage.py`, ASGI/WSGI, root URL configuration, the custom test runner, Docker/Apache paths, documentation, and deployment commands in one bounded change.
- Introduce `LOYALTY_ALLOWED_HOSTS_FILE`. Read the old `TURNKEY_ALLOWED_HOSTS_FILE` as a deprecated fallback for one release, then remove it only after deployment configuration has been verified.
- Do not rename `dotykacka` historical migration modules. The legacy app remains installed as a compatibility owner while behavior is extracted.

Use precise product language throughout the code and UI:

- **tenant** means a paying SaaS client, such as Marta Banaszek / Atelier-Café;
- **customer** or **loyalty member** means the person who receives a loyalty card;
- **platform operator** means MB Studio staff who centrally produce and deliver cards.

### Target Django apps

| Django app | Ownership and responsibilities |
| --- | --- |
| `core` | Small shared primitives only: redacted audit trail, database-backed jobs, immutable artifact metadata/helpers, clocks/IDs, and common validation. It must not import a provider or high-level business app. |
| `tenants` | `Tenant`, memberships/roles, tenant resolution, organization profile, brand/contact data, tenant feature state, and tenant-scoped authorization helpers. Keep Django’s standard `User`; do not introduce a custom user-model migration. |
| `customers` | Loyalty customer records, profiles, external-provider identifiers, consent references, search/listing, and customer lifecycle. Preserve the existing `Klient` table and expose a clearer code-facing name before considering any table/model rename. |
| `cards` | Card-code parsing, physical card inventory, batches, allocation/assignment, card lifecycle, and stable links between a customer and a card. No image generation or provider calls. |
| `card_artwork` | Versioned brand/design snapshots, master-image upload, crop/editor settings, deterministic crop plans, barcode and front/back rendering, proofs, and immutable rendered artifacts. This absorbs `RandomImageCropper.py`, `add_logo.py`, and related CLI helpers. |
| `integrations` | Provider-neutral encrypted connection storage, health state, credential fingerprints, job/retry records, and adapter registry. It owns no POS- or email-specific payload rules. |
| `pos` | Provider-neutral POS capabilities and orchestration: validate/test connection, customer upsert/reconcile, future points policy, normalized errors, and provider contract tests. |
| `pos_dotykacka` | Dotykačka Connector v2 onboarding, refresh/access-token handling, cloud and discount-group configuration, customer mapping, pagination/filtering, retry/rate-limit behavior, and the concrete `DotykackaAdapter`. |
| `communications` | Provider-neutral communication requests, templates, consent-aware recipient selection, delivery state, and idempotent send orchestration. Django email remains a supported adapter. |
| `brevo` | Tenant-owned Brevo API key/list configuration, contact upsert/list membership, rate-limit handling, webhook validation if enabled later, and a concrete communications/contact adapter. |
| `wallets` | Stable wallet identity owned by customer/card, provider-neutral status, and wallet issuance orchestration. It contains no Apple certificate or Google REST implementation. |
| `wallet_apple` | Apple `pass.json`, assets, manifest/signature/package generation, protected `.pkpass` delivery, and future update-web-service behavior. |
| `wallet_google` | Google Wallet class/object mapping, object upsert, signed save URL generation, and provider status. One stable object ID is reused per wallet identity. |
| `billing` | Plans, subscriptions, entitlements, billing periods, append-only usage, price books, overage tiers, prepaid card packs, and immutable quotes. Payment collection remains out of scope until a provider is approved. |
| `printing` | Client print requests, proof approval, production quotes, platform queue, allocation, print runs/packages, checksum validation, printed/delivered events, and platform-only downloads/actions. |
| `enrollment` | Public tenant-branded registration, card assignment policy, versioned consent evidence, and durable orchestration of Wallet/POS/Brevo/email follow-ups. |
| `marketing` | Public homepage, feature pages, published pricing, contact/lead form, legal pages, and redirects from legacy public/demo URLs. It must not become a second tenant portal. |

Do not create an app only to hold a few utility functions. For example, audit and jobs start as modules/models in `core`; split them later only if they gain a separate lifecycle and substantial behavior. Views, forms, templates, admin registrations, services, and tests should live with the domain that owns the behavior.

### Dependency direction

The required direction is:

```text
core
  └── tenants
       ├── customers ── cards ── card_artwork
       ├── integrations
       │    ├── pos ── pos_dotykacka
       │    └── communications ── brevo
       ├── wallets ── wallet_apple / wallet_google
       └── billing ── printing

enrollment orchestrates customers/cards/wallets/pos/communications
marketing reads only public published plan data from billing
```

- Provider apps implement interfaces owned by `pos`, `communications`, or `wallets`; core domain apps never import `pos_dotykacka`, `brevo`, `wallet_apple`, or `wallet_google` directly.
- `billing` cannot import `printing`; printing asks billing for an entitlement decision and immutable quote.
- `card_artwork` renders artifacts but cannot mark cards printed or delivered.
- Critical workflows use explicit application services and `transaction.on_commit`, not hidden cross-app model signals.
- Cross-app writes occur through the owning app’s service. Direct model imports are acceptable for read-only relationships during extraction but should not become arbitrary write access.

### Configuration and credential ownership

| Configuration | Owner and storage |
| --- | --- |
| Dotykačka refresh/authorization token returned for a tenant connection | Tenant-owned; encrypted in the database |
| Dotykačka cloud ID and discount-group ID | Tenant-owned; normal database configuration |
| Dotykačka short-lived access token, cloud, and expiry | Tenant connection cache; encrypted in the database and replaceable without changing the refresh token |
| Dotykačka Connector `client_id` and `client_secret` for this SaaS integrator | Platform-owned; `.env`/secret manager, never client-editable |
| Brevo API key | Tenant-owned; encrypted in the database |
| Brevo list ID, attribute mapping, enabled state | Tenant-owned; normal database configuration |
| Tenant names, logos, text, colors, card/wallet content, class suffixes | Tenant-owned; versioned database records plus protected uploaded assets |
| Apple signing certificate/private key/password, WWDR certificate, team/pass-type identifiers under a centralized issuer | Platform-owned; environment references and protected secret files, never database-editable from the client portal |
| Google service-account key and central issuer ID | Platform-owned; environment/protected secret file |
| Django secret, database, SMTP, encryption keys, storage, allowed hosts | Platform-owned; `.env`/secret manager |

If the product later permits a tenant to bring its own Apple/Google issuer account, that is a separate credential model and security review. The initial plan uses centralized platform issuers while all visible brand content remains tenant-versioned.

### Safe extraction rules

1. Add import/dependency tests and snapshot current URL names, admin actions, commands, permissions, content types, and table names.
2. Rename the project configuration package independently because it has no business tables. Keep temporary import/environment aliases for one release.
3. Create destination apps and move services, forms, views, URLs, templates, admin classes, and tests first while importing existing legacy models. This creates domain boundaries without touching stored data.
4. Put all newly introduced models in their final owning apps. Keep existing models physically/state-owned by `dotykacka` until each model move has a specific reason and rehearsal.
5. If an existing model must move, preserve its exact table with `Meta.db_table`; use `SeparateDatabaseAndState` or an equivalent state-only migration, and migrate `django_content_type`, permissions, and admin-log references explicitly. Never create-copy-drop a production table merely to change a Python import path.
6. Preserve primary keys, foreign keys, storage paths, URL names, command aliases, and compatibility imports during the transition. Mark aliases deprecated; remove them only after at least one verified release.
7. Extract one bounded context at a time and run the fresh-install plus upgraded-replica suites after every slice. A failed slice rolls back application code while the additive schema remains readable.
8. Historical migrations and immutable legacy artifacts remain in place permanently unless a future archival plan is separately approved.

## 6. Target domain model

Names may be refined during implementation, but the boundaries and ownership must remain.

| Owner | Model | Purpose and important fields |
| --- | --- | --- |
| `tenants` | `Tenant` | SaaS client account: display/legal name, unique slug, status, locale, timezone, card prefix, and public registration state |
| `tenants` | `TenantMembership` | User-to-tenant relationship with `owner` or `staff` role; platform superusers retain platform access but receive explicit tenant context when acting for a client |
| `tenants` | `TenantBrand` / immutable `TenantBrandRevision` | Organization/contact data and versioned visible brand content reused by artwork, Wallet, registration, and communications |
| `customers` | existing `Klient`, code-facing alias `Customer` | Preserve table, primary keys, PII, and links. Keep the existing model/table owner during early extraction and expose a clearer name through services/query APIs |
| `customers` | `CustomerExternalIdentity` | Tenant, customer, provider, remote ID, remote version and sync timestamps; avoids provider fields on the customer table |
| `customers` | `ConsentRecord` | Tenant, customer, purpose, policy version, text/hash, timestamp, source, and revocation state |
| `cards` | `CardBatch` | Tenant-owned allocation of card codes using a frozen design reference; allocation/generation state and legacy marker |
| `cards` | `PhysicalCard` | One physical code/inventory item: tenant, batch, code/number, assignment state, legacy flag, and optional customer relation |
| `card_artwork` | `CardDesign` | Versioned, immutable-after-publication physical design settings: master image, logo, text, crop/focal rules, barcode, dimensions, bleed, DPI, and checksum |
| `card_artwork` | `CropPlan` | Card/design, deterministic seed, source checksum, exact crop rectangle/transform and render version so “random” cards can be reproduced exactly |
| `card_artwork` | `CardArtifact` | Immutable protected artifact path, kind, checksum, size, render metadata, and optional design/batch/card relation |
| `integrations` / provider app | `IntegrationConnection` | Tenant/provider, enabled state, non-secret configuration, encrypted credential envelope, key version, health and last error; provider details are validated by the provider app |
| `pos_dotykacka` | `DotykackaToken` or evolved `AccessToken` | Connection-owned encrypted access-token cache with cloud ID, obtained/expiry timestamps and invalidation state. Legacy rows remain intact |
| `wallets` | `WalletPass` | Stable provider-neutral identity per customer/card and protected provider state; Apple serial and Google object identity never change after issuance |
| `billing` | `Plan`, `PlanVersion` | Public plan identity plus immutable commercial version: currency, billing interval, included seats, included issued cards, and enabled capabilities |
| `billing` | `TenantSubscription`, `BillingPeriod` | Tenant’s plan/version, status, current period, trial/cancellation timestamps, and immutable plan snapshot |
| `billing` | `UsageEvent` | Append-only idempotent usage ledger for `seat_active`, `card_issued`, `card_printed`, pack consumption, and adjustments with actor/reason |
| `billing` | `PriceBook`, `PrintPriceTier`, `CardPack` | Versioned per-card overage and bulk pricing such as a 100-card pack; amounts and currency use decimal fields, never floats |
| `billing` | `Quote` / `QuoteLine` | Immutable price/entitlement snapshot accepted by a print request so later price changes cannot rewrite an order |
| `printing` | `PrintRequest` | Tenant request with quantity, design, proof checksum, accepted quote, delivery address snapshot, notes, and controlled state |
| `printing` | `PrintRun`, `PrintPackage` | Platform production run, allocated cards, layout snapshot, immutable manifest/files, checksums and operator timestamps |
| `printing` | `FulfillmentEvent` | Append-only `printed`, `packed`, `dispatched`, `delivered`, or correction event with card/request/run scope, actor, timestamp, reference and reason |
| `core` | `IntegrationJob` | Database-backed durable work item for provider, Wallet, email, artwork, and print work; idempotency key, attempts, next retry, and redacted error summary |
| `core` | `AuditEvent` | Actor, tenant, action, object reference, timestamp, and redacted metadata for privileged or commercially relevant changes |

### Required constraints

- Unique `Tenant.slug`.
- Unique `Tenant.card_prefix` initially, because physical barcodes may be scanned outside application context.
- Unique `(tenant, membership.user)`.
- Keep `PhysicalCard.code` and existing `Klient.klient_id` globally unique and normalized for the first release because tenant prefixes are globally unique and cards may be scanned without tenant context.
- Unique `(tenant, PhysicalCard.number)` and database checks that customer/card/batch/design relationships stay within one tenant.
- Unique `(tenant, IntegrationConnection.provider)` for the first release.
- Unique `UsageEvent.idempotency_key`; usage events and accepted quotes are append-only.
- Unique `(tenant, provider, remote_id)` where a provider supplies a stable remote customer identifier.
- Unique `(Dotykačka connection, cloud_id)` token context; a token must never be reused for another cloud or tenant.
- A plan/version, price book, accepted quote, published design, print package, crop plan, and fulfillment event is never edited in place. Corrections create a new version or compensating event.
- A `PrintRequest` always references a published design version; changing settings creates a new design version and never changes an existing print request.
- A print request cannot become `approved` without a current entitlement decision and accepted immutable quote, including a zero-value quote when fully included in the subscription.
- Tenant-owned file paths include stable tenant, design/batch, and card identifiers. User-provided filenames never determine storage paths.

## 7. Tenant and authorization rules

Three roles are required:

1. **Platform administrator/operator** — manages tenants, sees the global print queue, allocates batches, downloads print packages, records printing/fulfillment, and can support a tenant using an explicit tenant context.
2. **Client owner** — manages only their tenant’s brand, design, staff, POS connection, customers, proofs, and print requests.
3. **Client staff** — operates customers and allowed day-to-day actions but cannot change credentials, ownership, or production design settings unless granted a specific permission.

Implementation rules:

- Resolve tenant context explicitly from the authenticated membership or a public tenant slug; never infer it from a submitted object ID.
- Every tenant-owned query must begin from the resolved tenant or use a tenant-scoped service/repository helper.
- Object lookups must include both primary key and tenant.
- Platform-wide behavior must use a separate platform view/service, not a bypass flag in client views.
- Public enrollment moves to a tenant route such as `/c/<tenant-slug>/register/`. The current `/` and `/dotykacka/register` routes remain compatible redirects to Marta’s tenant during rollout.
- Protected downloads stream files through authorized Django views. Production must not expose the whole media root directly.
- Add negative tests proving a member of tenant A cannot enumerate, mutate, download, or trigger work for tenant B.

## 8. Tenant settings, artwork, subscriptions, and printing UX

### Client settings area

Build Django template pages styled with compiled Tailwind and enhanced with HTMX fragments:

- **Organization** — names, contacts, locale/timezone, public registration state, and card prefix before the first new batch is allocated.
- **Brand assets** — upload/replace logo and a large master background image with file type, size, dimensions, source checksum, and decompression-bomb validation.
- **Physical card artwork** — controlled layout preset, logo, tagline, contact text, colors, approved bundled font, barcode placement, crop mode, focal area, variation strength, bleed, safe area, and DPI.
- **Crop proof sheet** — generate a bounded sample of deterministic “random” crops from the master image. Store the seed and exact crop rectangle for any published/card render so the same output can always be reproduced.
- **Live proof** — HTMX POST renders a server-side low-resolution front/back preview without saving a published design. Publishing creates a new immutable design version.
- **Registration and communications** — public text, consent policy/version, email subject/body/footer, Wallet descriptions, and sender identity.
- **POS integration** — choose a supported provider, enter masked credentials/configuration, test the connection, and view last sync/error state.
- **Subscription and usage** — current immutable plan version, active-seat count/limit, card-issuance use for the billing period, pack balance, overage rules, and a usage ledger understandable to the tenant owner.
- **Print requests** — choose a published design, quantity, notes/delivery details, see a quote split into subscription allowance/pack/overage, approve the proof and quote, submit the request, and view status/history.

No free-form browser canvas is planned. The first editor uses controlled crop/focal fields plus server-rendered HTMX previews, so it requires no custom JavaScript. If later usability testing proves that direct manipulation is necessary, use only the minimum browser JavaScript for pointer/crop coordinates and keep the authoritative render in Python/Pillow.

### Platform print center

- Queue across tenants with tenant, quantity, design version, request date, delivery, and status filters.
- Open the exact frozen proof and compare its checksum with the request.
- Approve/reject with an audit note.
- Allocate the next card code range transactionally so concurrent requests cannot overlap.
- Generate in a background database job and show progress through HTMX polling.
- Validate dimensions, DPI, bleed, fronts/backs count, code uniqueness, filenames, and checksums before making a package downloadable.
- Download a protected, immutable package containing front and back print sheets or per-card files, a manifest, and a human-readable job summary.
- Record `printing`, `printed`, `fulfilled`, or `cancelled` transitions with actor and timestamps. Cancellation never deletes generated artifacts or reuses issued codes.
- Provide a legacy-card reconciliation view for the imported Marta inventory. A platform operator can select an explicit card range/batch, preview aggregate counts, and append `printed` and `delivered` fulfillment events without regenerating files, changing customer assignment, repricing historical work, or deleting anything.
- Require confirmation with exact affected counts for any bulk fulfillment action. Record actor, tenant, timestamp, delivery date, reference, notes and a reason for later corrections.

Print layout settings must be confirmed with the real printer before production generation: finished card size, bleed, safe area, DPI, color profile, sheet size, cards per sheet, crop marks, duplex order/flip, file format, and filename convention.

## 9. Shared service architecture

Move business behavior out of views and standalone scripts into small Python/Django services:

```text
HTTP view or management command
            |
            v
tenant-aware application service
            |
    +-------+---------+-------------+-------------+
    |                 |             |             |
card artwork     Wallet passes   POS adapter   notifications
    |                 |             |             |
Pillow/files      Apple/Google   Dotykačka     Django email/Brevo
            |
            v
database job + audit event + immutable artifact metadata
```

Service rules:

- Views validate forms, resolve authorization, call one service, and render/redirect; they do not build images, call POS APIs, or compose email.
- Management commands are thin adapters over the same services and support `--tenant`, `--dry-run`, and bounded card/batch selection.
- Generators accept explicit tenant/design/card inputs. They do not read global business configuration directly from Django settings.
- Generation writes to a temporary unique directory, validates all output, then atomically publishes a new immutable artifact path.
- Store a configuration snapshot and checksum with every generated batch.
- Retrying the same job is idempotent and cannot allocate a second code or send duplicate email without an explicit resend action.
- Local database records are the application source of truth. POS data is synchronized external state with provider IDs and timestamps.

## 10. Provider integration design

Create a provider interface with these initial operations:

- validate configuration;
- test/authenticate connection;
- create or update one loyalty customer idempotently;
- fetch/reconcile customers;
- optionally read/write points only after the expected ownership rules are defined;
- normalize provider errors into redacted, user-safe statuses;
- expose provider capabilities so the UI does not assume every POS supports the same functions.

Implement `DotykackaAdapter` first by refactoring existing API behavior. Its cloud ID, discount group, refresh credential, access token, and remote IDs become tenant/connection scoped. Platform timeouts/base URLs remain environment/default configuration. No global tenant-business value such as `DOTYKACKA_CLOUD_ID` or `DOTYKACKA_DISCOUNT_GROUP_ID` may be used after the transition compatibility period.

### Dotykačka contract based on the current official documentation

- Use Connector v2 for new SaaS clients. The browser-facing connection request is a form POST signed with HMAC-SHA256 using the platform `client_id`/`client_secret`, timestamp, redirect URI, and a cryptographically random `state` value. Verify `state` and the tenant/session before accepting the redirect.
- The redirect supplies a tenant refresh token and selected cloud ID. Encrypt the refresh token in the tenant’s Dotykačka connection and store the cloud ID as tenant configuration; never render the token again.
- Exchange it at `POST /v2/signin/token` with JSON `{\"_cloudId\": ...}` and `Authorization: User <refresh-token>`. Use the resulting access token only as `Authorization: Bearer <access-token>` and only for that tenant/cloud.
- Treat the documented one-hour access-token validity as an upper bound, not a guarantee. Store obtained/expected-expiry timestamps with a safety skew, refresh on expiry or one authorized `401`, and serialize refreshes per connection to prevent a token stampede.
- Customer reads/writes use `/v2/clouds/{cloudId}/customers`; create payloads are arrays. Use a stable local external ID/idempotency mapping, the configured discount group, page/limit bounded to the documented maximum, supported filters, and ETag headers when useful.
- Respect the published request limit and provider status. Prefer reconciliation/webhooks over aggressive polling; `429`, `5xx`, and network failures are retryable, while invalid configuration/authentication requires tenant action.
- Do not enable points/balance writes until the business source-of-truth and tax/ledger responsibilities are explicitly approved.

Official basis: [Dotykačka authorization and Connector v2](https://docs.api.dotypos.com/authorization/), [customer API](https://docs.api.dotypos.com/entity/customer/), [general method/pagination rules](https://docs.api.dotypos.com/api-reference/general/methods/), and [API overview and query-limit guidance](https://manual.dotypos.com/apidotykacka.html).

### Brevo contract based on the current official documentation

- `BREVO_API_KEY` is a tenant secret and `BREVO_LIST_ID` plus attribute mapping are tenant configuration. Store them in the database as described in section 5, not as global settings.
- Authenticate with the `api-key` header. Never log request headers or expose a key fingerprint that reveals more than a short non-sensitive suffix/hash.
- Upsert one contact idempotently using a stable local identifier (`ext_id` where appropriate), normalized email/phone, declared Brevo attributes, tenant list IDs, and `updateEnabled`/explicit update semantics. Never automatically use `forceMerge`, because it can merge/delete a conflicting contact.
- Contact synchronization is not consent evidence. `ConsentRecord` remains the source for whether marketing sync/send is allowed, and unsubscribe/blocklist state from Brevo must not be overwritten blindly.
- Read `x-sib-ratelimit-*` headers, retry `429` after the reset with bounded exponential backoff/jitter, and expose a redacted retry status. Contact endpoints have provider/account-tier limits, so bulk sync runs as resumable jobs rather than request-time loops.
- Use the existing Python HTTP capability first. Replacing the legacy SDK with a new dependency requires a dependency/security review but not another runtime stack.

Official basis: [Brevo API-key authentication](https://developers.brevo.com/docs/api-key-authentication), [create/upsert contact](https://developers.brevo.com/reference/create-contact), [update contact](https://developers.brevo.com/reference/update-contact), and [rate limits](https://developers.brevo.com/docs/api-limits).

### Apple and Google Wallet provider boundaries

- `wallet_apple` builds a source package from tenant-versioned text/images plus stable card/customer identity, creates `pass.json`, hashes the packaged files into a manifest, signs it with platform credentials, and publishes a new immutable `.pkpass`. A retry never changes the Apple serial or overwrites an earlier artifact. See [Apple Wallet Passes](https://developer.apple.com/documentation/walletpasses) and [Creating the Source for a Pass](https://developer.apple.com/documentation/walletpasses/creating-the-source-for-a-pass).
- `wallet_google` maps tenant-versioned shared appearance to a Google Pass Class and each card/customer identity to one stable Pass Object. Save links use signed JWT claims for the existing object; retries must not create duplicate object IDs. The platform service account/issuer stays server-side. See [Google loyalty cards](https://developers.google.com/wallet/retail/loyalty-cards), [classes and objects](https://developers.google.com/wallet/generic/overview/how-classes-objects-work), and [REST credentials](https://developers.google.com/wallet/generic/getting-started/auth/rest).

Credential rules:

- Continue using the already installed Python `cryptography` package for encryption at rest; do not invent reversible obfuscation.
- Keep an encryption key separate from the database and Django templates. Support key version metadata for later rotation.
- Forms display only whether a secret is configured plus a short non-sensitive fingerprint; leaving the secret blank retains the current value.
- Never audit or log secret values, bearer tokens, signed Wallet URLs, or service-account JSON.

Durability rules:

- Replace daemon threads with `IntegrationJob` records claimed using database transactions.
- Run a Django management-command worker under the existing deployment process supervisor/cron approach.
- Use bounded retries and exponential backoff for retryable failures; validation/authentication failures require client action.
- Outbound work begins only after the customer database transaction commits.
- Add idempotency keys and store remote provider identifiers/responses in a redacted form.

Additional POS providers must be added as adapters plus contract tests, without adding provider-specific fields to customer views or card generators.

## 11. Safe migration and extraction plan for Marta as the first tenant

### Pre-migration safeguards

- Take and verify an encrypted MariaDB backup and a separate immutable media backup.
- Restore both into a disposable staging environment and run the full migration there first.
- Record pre-migration counts for every table and checksums/counts for card asset directories.
- Put external integrations and email into safe/test mode during migration verification.
- Run a read-only preflight command that fails on duplicate card IDs, malformed codes, missing assets, or unexpected tenant-sensitive rows.
- Never remove a Docker/database volume as part of the migration procedure.

### Migration sequence

The original tenant/backfill portion below is complete on the verified local replica through migration `0013`. It remains documented because every future extraction must preserve these invariants.

1. **Add tenant foundation** — create tenant, membership, mutable brand profile, inventory, integration, and audit tables. Add nullable tenant/relationship fields to existing `Klient` and `AccessToken`. Do not alter or drop existing fields.
2. **Create first tenant** — a forward data migration creates a stable Marta Banaszek / Atelier-Café tenant, initial brand profile, and a legacy physical-card batch for `MB-1` through `MB-600`.
3. **Assign current user** — the same reviewed data migration creates Marta tenant membership for every user that exists at the time of migration. In the verified replica this is the single `admin` user. Its superuser status remains unchanged so it can also perform platform operations.
4. **Assign all customers** — attach every pre-existing `Klient` row to Marta without modifying any personal data, card code, primary key, or Wallet URL.
5. **Import card inventory metadata** — create exactly one `PhysicalCard` row for each verified legacy code `MB-1` to `MB-600`. Attach the 267 matching customer records and mark those cards assigned; mark the remaining 333 available. Reference existing files as immutable legacy paths; do not copy, rename, or regenerate them in this migration.
6. **Assign POS state** — create Marta’s Dotykačka connection from non-secret existing configuration references and attach all existing `AccessToken` rows to it as legacy token records. Do not expose, rewrite, or delete the token values. New tokens use the encrypted connection-scoped path.
7. **Enforce tenant ownership** — only after verification, make required tenant foreign keys non-null and add composite uniqueness/check constraints in a separate migration.
8. **Switch application reads** — deploy tenant-scoped code while keeping all legacy columns and paths readable.
9. **Add card design/Wallet identity metadata** — add immutable design, artifact, batch-design and stable Wallet records without replacing legacy files.
10. **Deferred cleanup** — do not drop `google_jwt_url`, global compatibility settings, legacy token data, old model names, or legacy file paths in this project phase. Any later cleanup requires a separate retention/archival plan, backup verification, user approval, and new migrations.

Data migrations should be idempotent by stable natural keys and have a no-op reverse. A production code rollback must continue to understand the additive schema; production must not reverse the tenant data migration.

### Future app-extraction sequence

1. Take a fresh database/media backup and record the current migration/content-type/permission/admin-log aggregates before each extraction release.
2. Extract behavior and UI into a destination app with compatibility imports and unchanged URL names. Do not move any table in the same release.
3. Add new schema only in the destination app through additive migrations, then run a fresh install and an upgraded Marta replica.
4. If model state ownership must move, use a rehearsed state-preserving migration with the existing table name. Verify primary keys, foreign keys, content types, permissions, admin logs, generic references and row counts before and after.
5. Keep `dotykacka` installed and its historical migrations available. It becomes a compatibility shell until all runtime imports are gone and at least one production release has passed.
6. Never “clean up” old tables, columns, token rows, files, or compatibility paths during extraction. Cleanup is a separate future migration/retention project requiring explicit approval.

### Required migration verification report

The deployment runbook must capture only non-sensitive aggregates:

- table counts before and after;
- null tenant/relationship counts;
- duplicate and malformed code counts;
- card status totals;
- orphan customer/card/assets counts;
- asset counts and checksums without customer PII;
- migration list and `manage.py check` output.

## 12. Revised implementation phases

### Phase 0 — Safety net and current-behavior stabilization

- [x] Add factories/fixtures with synthetic data only; never copy production PII into tests.
- [x] Add tests for registration, code validation, duplicates/races, customer listing, Apple/Google services, email, Dotykačka failures, and every privileged POST action.
- [x] Add a “no external calls” test guard and mocked provider contracts.
- [x] Fix prefix parsing using an explicit parser, not `strip`.
- [x] Add a proper Django form with server-side validation and normalize card codes.
- [x] Separate Google generation from email sending and ensure Apple generation is explicit.
- [x] Replace PII CSV logging with structured, redacted application/job records.
- [x] Create the read-only legacy inventory preflight command.
- [x] Document backup, restore, safe local mode, and production rollback steps.

Acceptance gate: existing behavior is covered, tests do not make external calls, the replica counts/assets match the verified baseline, and no data or media changed.

### Phase 1 — Tenant foundation and Marta backfill

- [x] Add tenant, membership, authorization helpers, audit model, and tenant context.
- [x] Add tenant ownership to existing data using the additive migration sequence in section 11.
- [x] Import the `MB-1..600` inventory metadata and bind 267 customers.
- [x] Move client-owned Dotykačka/Brevo values and Google Wallet identifiers into tenant database settings with encrypted credential envelopes where then required. Phase 6 will normalize centralized issuer credentials to platform secrets without deleting legacy values.
- [x] Add an owner-only integration settings page with masked secret retention and redacted audit events.
- [x] Replace global/unscoped customer, POS token, integration, and bulk queries with tenant-scoped services.
- [x] Keep compatibility routes for Marta and add the explicit tenant registration route.
- [x] Add migration, encryption, cross-tenant isolation, and platform/owner/staff role tests using a synthetic second tenant.

Acceptance gate: passed on 2026-07-17. Marta’s current user, all 267 customers, 600 cards, 261 migration-time token rows, and legacy assets remained intact; all null/orphan/mismatch checks were zero and the synthetic second tenant could not access Marta resources. The append-only token count can grow during normal refreshes and is verified by ownership rather than a permanently fixed total.

### Phase 2 — Django/HTMX/Tailwind portal shell

- [x] Add a reusable Django base template, accessible navigation, forms, messages, and error fragments.
- [x] Compile Tailwind into versioned static CSS using the approved build-only Node approach.
- [x] Vendor pinned HTMX 2.0.10 locally; no loyalty screen depends on a runtime CDN.
- [x] Remove Bootstrap and legacy jQuery from active loyalty screens after parity checks.
- [x] Build client settings navigation and the separate platform print-center navigation.
- [x] Keep only minimal custom JavaScript for camera access/barcode scanning; vendor the compatible pinned ZXing 0.21.3 library and document why it is required.

Acceptance gate: passed on 2026-07-17. Public registration and all portal forms remain ordinary Django HTML flows without custom JavaScript; integration forms progressively enhance with local HTMX and retain normal POST/redirect behavior when HTMX is unavailable. Desktop and mobile browser checks passed without console errors.

### Phase 3 — Tenant card design and unified generators

- [x] Create versioned tenant brand and `CardDesign` forms/models.
- [x] Refactor crop, logo/text composition, barcode rendering, front/back generation, manifest signing, Apple Wallet, and Google Wallet into tenant-aware services.
- [x] Add server-rendered HTMX proof generation and validation.
- [x] Add stable Apple serial and Google object records.
- [x] Store new artifacts in immutable tenant/design/batch paths with checksums.
- [x] Replace standalone loops with safe management commands using the shared services and `--dry-run`.
- [x] Write golden-image/metadata tests for existing Marta output plus a clearly different synthetic tenant.

Acceptance gate: passed on 2026-07-17. Marta v1 retains the verified 1011×638, 300-DPI legacy layout and asset references; the pinned golden render is stable, a synthetic tenant produces distinct output, retries publish new paths without overwriting prior bytes, and CLI/web generation calls the same renderer. The read-only post-migration verifier reports one Marta design, one brand revision, 267 Wallet identities, one linked legacy batch, and zero tenant mismatches.

### Phase 4 — Project rename and extraction safety rails

- [ ] Add an architecture test that rejects forbidden imports from core/domain apps into concrete provider apps and inventory all current URLs, management commands, admin actions, model labels, tables, content types and permissions.
- [ ] Rename `turnkey_project` to `loyalty_platform` across `manage.py`, settings, URLs, ASGI/WSGI, test runner, Docker/Apache/deployment commands, tests and documentation.
- [ ] Add `LOYALTY_ALLOWED_HOSTS_FILE` with a one-release fallback to `TURNKEY_ALLOWED_HOSTS_FILE`.
- [ ] Create empty destination app packages from section 5 with namespaced URLs/tests, without moving models or changing tables.
- [ ] Turn `turnkey_app` into a compatibility redirect toward the `marketing` app; do not remove the old route in this phase.
- [ ] Add a read-only `verify_app_extraction` command that reports table counts, model labels, content types, permissions, admin-log references and migration state.

Acceptance gate: the fresh database and upgraded Marta replica have the same business row counts, model tables, permissions and working routes; no business-data migration is created; all 80+ existing tests and the rename/deployment checks pass.

### Phase 5 — Extract tenants, customers, cards, and card artwork

- [ ] Move tenant resolution/authorization/UI to `tenants`, customer forms/views/services to `customers`, card code/inventory behavior to `cards`, and renderer/design UI to `card_artwork`.
- [ ] Keep existing model state/table ownership in `dotykacka` during the first behavior extraction. Add compatibility imports and unchanged URL names/command aliases.
- [ ] Put any new models (`CustomerExternalIdentity`, `ConsentRecord`, `CropPlan`) directly in their final apps using additive migrations.
- [ ] Extend the artwork workflow to upload one large master image, produce an HTMX sample sheet of deterministic varied crops, store exact crop plans, and apply the published tenant brand to each card.
- [ ] Keep all generation paths unified: web, worker and CLI call the same `card_artwork` services; standalone scripts become deprecated wrappers only.
- [ ] Move templates, admin classes and tests beside their owning domain and remove cross-domain writes from views.

Acceptance gate: all active tenant/customer/card/artwork views import their application services from the destination apps; the Marta golden render and every legacy path/checksum remain stable; two identical crop inputs reproduce identical bytes and metadata; no existing table was copied, dropped, or renamed.

### Phase 6 — Extract integrations, Dotykačka, Brevo, and Wallet providers

- [ ] Move encrypted connection/job primitives to `integrations`/`core`; create provider contracts in `pos`, `communications`, and `wallets`.
- [ ] Implement `pos_dotykacka` against Connector v2: HMAC connection initiation, CSRF `state`, refresh-token callback, cloud-scoped access-token cache, safe refresh/401 behavior, customer upsert/reconcile, pagination, retry and provider contract tests.
- [ ] Implement `brevo` contact upsert/list sync with tenant database credentials, consent gates, rate-limit headers, resumable jobs and no automatic force-merge.
- [ ] Extract stable identity/orchestration to `wallets`, Apple package/signing to `wallet_apple`, and Google class/object/save-link behavior to `wallet_google`.
- [ ] Normalize centralized Apple/Google issuer secrets to platform environment/protected files while retaining any legacy encrypted values unread/destructively unchanged until a separate cleanup is approved.
- [ ] Add owner-only tenant settings and “connect/test/reconnect” flows using Django forms and HTMX status fragments. Secret fields remain masked and blank means retain.
- [ ] Replace daemon-thread work with transactionally claimed database jobs and a supervised Django management-command worker.
- [ ] Keep deprecated functions in `dotykacka.api_utils`, `dotykacka.brevo`, and Wallet modules as thin adapters until callers have migrated.

Acceptance gate: two synthetic tenants connect with different Dotykačka/Brevo configuration without credential, token, customer or list crossover; provider tests cover timeout/401/429/duplicate/retry paths; Apple/Google retries reuse stable identities; a web-process restart cannot silently lose work.

### Phase 7 — Subscription, entitlements, usage, and pricing

- [ ] Add `billing` models through additive migrations: plan/version, tenant subscription, billing period, entitlement policy, append-only usage event, versioned price book, per-card tier, card pack, immutable quote and quote lines.
- [ ] Define an active seat as an active `TenantMembership`; enforce the plan limit on invite/reactivation while never deactivating an existing user automatically.
- [ ] Define card issuance as the first successful transition that activates/assigns a physical or digital card identity. Record it once through an idempotency key; proof generation and retries never consume quota.
- [ ] Support a plan’s included issuance/print allowance, per-produced-card overage, and prepaid/bulk packs such as 100 cards. Resolve allowance → eligible pack balance → per-card tier deterministically and show the calculation before acceptance.
- [ ] Store money as decimal amount plus ISO currency. Freeze plan/price/tax/shipping inputs in a quote; later price changes never alter an accepted print request.
- [ ] Add owner and platform views for subscription, usage and pricing. Platform operators publish plan/price versions; tenant owners cannot edit commercial records.
- [ ] Do not add Stripe, another payment processor, or automated invoicing in this phase. Record commercial obligations/quotes first; payment collection needs a separately approved provider and accounting flow.

Acceptance gate: concurrent/retried actions create one usage event; seat/card limits are tenant-isolated; boundary tests cover included quota, 1-card overage, tier edge and 100-card pack; accepted quotes remain unchanged after a new price version is published.

### Phase 8 — Centralized print request, production, and fulfillment

- [ ] Implement client proof/quote approval and idempotent print-request submission in `printing`.
- [ ] Implement the platform queue, controlled status transitions, transactional code allocation, database generation jobs, artifact validation, protected package download and fulfillment history.
- [ ] Build the production manifest, frozen layout/design/quote snapshots and per-file checksums.
- [ ] Implement the confirmed printer layout using Pillow first; request approval only if the real printer specification requires unsupported PDF/color-management behavior.
- [ ] Enforce quantity/entitlement decisions, duplicate-submit prevention, immutable files, non-reusable allocated codes, and audit events.
- [ ] Add a dry-run legacy reconciliation report for Marta’s `MB-1..600`, then a separately confirmed bulk action that appends printed/delivered events for selected existing cards without changing assignment, files, usage or price.
- [ ] Allow corrections only through compensating fulfillment events with a reason; never delete or rewrite the historical event.

Acceptance gate: concurrent requests cannot overlap codes or double-consume packs; only a platform operator can download production files or record fulfillment; every new print is traceable to tenant, accepted quote, request, design, crop plan, batch/run and checksums; legacy marking changes only additive fulfillment/audit records.

### Phase 9 — Tenant enrollment and durable follow-up workflow

- [ ] Move public registration to `enrollment` under tenant slug/domain and render the published tenant brand.
- [ ] Allocate only the tenant’s available card or follow the approved virtual-first policy; enforce database constraints under concurrency.
- [ ] Store versioned consent evidence and expose tenant/customer consent history.
- [ ] Orchestrate Wallet, POS, Brevo and email through idempotent database jobs after the local customer transaction commits.
- [ ] Generate tenant-branded communications with protected, expiring application links where required.
- [ ] Add authorized retry/resend actions and visible redacted status; a resend is explicit and audited.

Acceptance gate: tenant A can never allocate/use tenant B’s card, branding, provider connection or quota; consent and one issuance event are recorded; failures can be retried after restart without duplicate customers, Wallet objects, Brevo contacts or emails.

### Phase 10 — Marketing and published pricing site

- [ ] Build `marketing` server-rendered Django/Tailwind pages for the product overview, features, supported POS/Wallet capabilities, published plans/pricing, contact/lead form, privacy/terms and login entry.
- [ ] Render only active published `PlanVersion`/price summaries through a read-only billing query. Never expose tenant data or draft/internal prices.
- [ ] Redirect the legacy `/turnkey/` route and remove the `turnkey_app` runtime dependency after access-log/deployment verification; historical files/migrations remain if Django requires them.
- [ ] Keep public interactions as normal Django forms with HTMX enhancement where useful. Add no marketing frontend framework.

Acceptance gate: pricing shown publicly matches the published billing version, pages work without JavaScript, no authenticated tenant data is queryable, and no active code/deployment path contains the “turnkey” product name except the documented deprecated environment fallback.

### Phase 11 — Production hardening and SaaS rollout

- [ ] Add security headers, upload limits, protected media, public-registration/connect rate limits, webhook verification where applicable, and redacted structured logging.
- [ ] Add health checks for web, database, worker heartbeat, storage write/read and provider configuration without exposing secrets.
- [ ] Add database/media backup schedules and perform a restore drill after the app extraction migrations.
- [ ] Add CI for tests, migration consistency, architecture boundaries, template/static build and dependency/security checks.
- [ ] Add monitoring for failed jobs, print failures, low inventory/pack balance, approaching entitlement limits, and repeated provider authentication failures.
- [ ] Write operator/client/billing/fulfillment runbooks and a first-tenant extraction/verification report.
- [ ] Run a staged Marta acceptance test before enabling additional paying tenants.

Acceptance gate: restore drill passes; isolation, billing and extraction checks pass; Marta signs off on the complete flow; operations can trace/retry provider and print failures without direct database edits.

## 13. Test and release matrix

At minimum, every release must run:

- `python manage.py check`
- `python manage.py makemigrations --check`
- `python manage.py migrate --plan`
- full Django test suite on a fresh database and on an upgraded copy of the legacy schema;
- tenant isolation tests for list/detail/create/update/delete-like actions, downloads, jobs, and guessed IDs;
- migration assertions for the verified Marta counts and a blank-install path;
- app-extraction assertions for model labels, table names, content types, permissions and admin-log references;
- architecture tests that reject forbidden provider imports and circular app dependencies;
- generator golden tests for dimensions, barcode value/readability, design snapshot, manifest, and checksums;
- crop-plan tests for deterministic seed/coordinates, source checksum, reproducibility and tenant-distinct output;
- authorization tests for client owner, client staff, platform operator, anonymous registration, and cross-tenant denial;
- Dotykačka contract tests for HMAC/state callback validation, cloud-scoped token reuse/refresh, 401, pagination, 429/5xx, duplicate and reconciliation behavior;
- Brevo contract tests for consent gating, contact upsert/list membership, blocklist preservation, 429 headers, duplicate and retry behavior;
- Apple/Google tests for immutable serial/object identity, credential isolation, signed metadata, package checksums and retry behavior;
- billing tests for active-seat limits, issuance idempotency, period boundaries, decimal/currency handling, allowance/pack/tier order and immutable quotes;
- print allocation, quote/pack consumption, legacy fulfillment, concurrency and idempotency tests;
- HTMX and ordinary POST response tests;
- an external-call deny-list during tests and migrations.

No production release proceeds if it would produce an unplanned migration, null tenant owner, duplicate code, orphan card/customer, missing legacy asset, cross-tenant access, or external call during migration.

## 14. Decisions required before their phases

Completed Phases 0–3 are not blocked by these. The named future phase must not proceed past its design gate without the relevant decision:

1. Confirm the first tenant’s exact display/legal name and public slug. The repository currently uses “Marta Banaszek / Atelier-Café”.
2. Confirm whether card prefixes must be globally unique across tenants and whether Marta keeps `MB` permanently. The recommended answer is yes to both.
3. **Before Phase 4:** accept `loyalty_platform` as the replacement configuration package name. It is the recommended neutral name.
4. **Before Phase 7:** define the first plan(s), PLN/EUR currency, tax display, billing interval, included active seats, included card issuances/prints, whether unused quota rolls over, per-card overage, 100-card pack price/expiry, shipping and cancellation/refund rules.
5. **Before Phase 7 payment work:** choose an invoicing/payment provider and accounting ownership. No provider is assumed by this plan.
6. **Before Phase 8:** provide the printer’s finished size, bleed, safe area, DPI, color profile, sheet/imposition, crop marks, duplex orientation, preferred file type and naming convention.
7. **Before Phases 8–9:** confirm the allocation rule: preprinted card scanned at registration, digital-first then printed, or both.
8. **Before Phase 8:** confirm that tenant users receive low-resolution proofs only and platform operators alone download production files; this is the recommended policy.
9. **Before Phase 6 production onboarding:** obtain/verify Dotykačka partner `client_id`/`client_secret`, redirect URI and production access; define who can reconnect a tenant.
10. **Before Phase 6 points support:** define source of truth for customer fields, discounts, points/balance, transactions and conflict resolution. Initial scope should remain customer upsert/reconciliation only.
11. **Before Phase 6 Wallet production:** confirm centralized Apple Pass Type/Team and Google Wallet Issuer ownership; centralized MB Studio credentials are recommended.
12. **Before Phase 8 Marta reconciliation:** identify which legacy `MB-1..600` cards were actually printed and delivered, the delivery date/reference to record, and whether one bulk event or smaller verified groups are needed.
13. Decide whether one user may belong to multiple tenants in the first release. The current model supports it.
14. Decide whether custom tenant domains are required initially or tenant slugs are sufficient.
15. Defer a physical `Klient` model/table rename until the modular extraction is stable; a code-facing `Customer` name is sufficient initially.

## 15. Recommended next implementation slice

Start Phase 4 as a no-data-change slice:

1. Capture the current app-label/table/content-type/permission/URL/command baseline in tests and a read-only report.
2. Rename only the Django configuration package to `loyalty_platform`, update deployment references, and keep the allowed-host environment fallback.
3. Create the destination app packages and architecture test without moving models or adding business schema.
4. Run the full suite on a fresh database and the upgraded, backed-up Marta replica.
5. Compare the aggregate report and migration plan; stop if any business row, table, content type, permission, URL, card asset or checksum changes unexpectedly.

Only after that gate should Phase 5 move tenant/customer/card/artwork behavior. Existing model ownership and database tables stay in `dotykacka` during the first extraction release.

## 16. Documentation review basis

Provider behavior in this plan was rechecked against current official documentation on 2026-07-17:

- Dotykačka: [API availability/onboarding](https://dotykacka.cz/api), [Connector v2 and access tokens](https://docs.api.dotypos.com/authorization/), [customers](https://docs.api.dotypos.com/entity/customer/), and [general methods](https://docs.api.dotypos.com/api-reference/general/methods/).
- Brevo: [API-key authentication](https://developers.brevo.com/docs/api-key-authentication), [create contact](https://developers.brevo.com/reference/create-contact), [update contact](https://developers.brevo.com/reference/update-contact), and [rate limits/headers](https://developers.brevo.com/docs/api-limits).
- Apple Wallet: [Wallet Passes](https://developer.apple.com/documentation/walletpasses) and [pass source structure](https://developer.apple.com/documentation/walletpasses/creating-the-source-for-a-pass).
- Google Wallet: [loyalty-card overview](https://developers.google.com/wallet/retail/loyalty-cards), [class/object model](https://developers.google.com/wallet/generic/overview/how-classes-objects-work), and [REST authentication credentials](https://developers.google.com/wallet/generic/getting-started/auth/rest).

Recheck provider documentation, breaking changes, rate limits, production-access requirements and credential flows at the start of each provider implementation and before launch. Tests remain offline and migrations never call these APIs.
