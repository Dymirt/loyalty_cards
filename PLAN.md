# MB Studio Loyalty SaaS Conversion Plan

Status: proposed implementation plan

Prepared: 2026-07-17

Application: Django loyalty-card service at `mbstudio-loyalty-app`

Progress: Phases 0 and 1 implemented and verified on the backed-up local MariaDB replica on 2026-07-17; migrations `0008` through `0011` are applied.

## 1. Product outcome

Turn the existing Marta Banaszek / Atelier-Café application into a multi-tenant SaaS product while preserving the working first-client installation and every existing database record and generated card asset.

The product will have two operational sides:

1. **Client portal** — each SaaS client configures its brand, card design, registration experience, Wallet content, POS connection, and submits physical-card print requests.
2. **Platform operations** — the application administrator reviews client proofs, generates immutable card batches, downloads production print packages, prints the cards centrally, and records fulfillment.

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

## 3. Verified current baseline

The following was verified read-only against the running local replica on 2026-07-17:

| Area | Current state |
| --- | --- |
| Django | 5.2.1; `manage.py check` passes after Phase 1 |
| Database | MariaDB replica with Phase 1 migrations `0008` through `0011` applied |
| Application users | 1 active user: `admin`; staff and superuser |
| Loyalty customers | 267 `Klient` records |
| Card identifiers | 267 valid `MB-*` numeric codes, range `MB-1` through `MB-494`; no duplicates and no empty IDs |
| Cached POS tokens | 261 global `AccessToken` records |
| Physical card inventory | Complete assets for `MB-1` through `MB-600` |
| Per-card legacy assets | front image, back image, barcode PNG, cropped background, and Apple `.pkpass` all present |
| Expected imported inventory | 600 Marta cards: 267 assigned, 333 available |
| Tests | 64 automated tests covering the legacy baseline, upgrade migration, tenant isolation, roles, and encrypted settings |
| UI | Server-rendered templates using Bootstrap CDN and legacy jQuery; HTMX and Tailwind are not yet implemented |
| Working tree | Existing uncommitted Docker, configuration, README, and Wallet-path work must be preserved |

### Current helper and workflow inventory

| Existing code | Current purpose | SaaS destination |
| --- | --- | --- |
| `RandomImageCropper.py` | Random card-size crops from a master background | `CardArtworkService`; deterministic crop metadata and tenant-scoped previews |
| `add_logo.py` / `CardGenerator` | Logo, text, barcode, front/back JPEG generation | `PhysicalCardRenderer`; configuration comes from a versioned tenant card design |
| `generate_manifest.py` | Standalone Apple manifest generation | Internal method of `AppleWalletService`; remove duplicate execution path only after parity tests |
| `generate_pass.py` | Legacy batch Apple pass generation from CLI | Thin Django management command calling `AppleWalletService` |
| `dotykacka/apple_wallet_pass.py` | In-app Apple `.pkpass` generation | Tenant-aware `AppleWalletService` with stable serial numbers and immutable output |
| `dotykacka/google_wallet/JWT.py` | Google Wallet save URL generation | Tenant-aware `GoogleWalletService` using per-tenant class/content configuration |
| `dotykacka/api_utils.py` | Global Dotykačka authentication/customer creation | First adapter behind a tenant-aware POS service interface |
| `dotykacka/brevo.py` | Global Brevo contact synchronization | Optional tenant integration service, configured and audited per tenant |
| Bulk actions in `views.py` | Global generation, sync, and email loops | Authorized service calls and durable database jobs scoped to one tenant or platform batch |

Existing CLI workflows will remain available as Django management commands, but both CLI commands and web actions will call the same service layer. There must be only one implementation of each generator.

## 4. Problems to fix before calling the app SaaS-ready

### Data and tenancy

- There is no tenant/client model. Customers, tokens, settings, Wallet identifiers, assets, and operations are global.
- `Klient` means a loyalty-program customer, not a SaaS client; this naming is dangerous in a multi-tenant system.
- `klient_id` has no database uniqueness constraint even though registration treats it as unique.
- Customer lists and bulk operations use unscoped `.objects.all()` calls.
- The current customer page treats Dotykačka as the list source instead of the local database, so the application cannot operate reliably when a POS is unavailable.

### Card and Wallet generation

- Branding, prefix `MB`, address, telephone number, tagline, email copy, Wallet text, Google class suffix, and file paths are hard-coded or global.
- The cropper is random but does not persist crop coordinates or a design version, so output is not reproducible.
- Batch scripts use fixed numeric ranges and write to shared paths, which can overwrite files.
- Apple pass serial numbers change on regeneration rather than representing a stable card/pass identity.
- Registration imports `build_pass` but does not generate an Apple pass; email assumes a pre-generated file exists.
- Google URL generation and the “generate” bulk action are coupled to email sending.
- Direct media URLs expose card and customer-related artifacts without tenant authorization.

### Registration and operations

- Barcode validation accepts some malformed values, and `.strip("MB-")` is incorrectly used to remove a prefix.
- Duplicate protection is application-only and is race-prone.
- Marketing consent is browser-required but has no submitted field name, policy version, timestamp, or stored evidence.
- Daemon threads can lose POS sync, Wallet generation, and emails when the web process restarts; their failures are not visible or retryable.
- Bulk email writes personally identifying information and raw errors to a CSV log.
- POS access tokens are global and stored as plaintext records.
- The UI mixes Bootstrap, old jQuery, inline CSS, and an unpinned `@latest` barcode library instead of the required Tailwind/HTMX approach.

## 5. Target domain model

Names may be refined during implementation, but the boundaries and ownership must remain.

| Model | Purpose and important fields |
| --- | --- |
| `Tenant` | SaaS client account: display/legal name, unique slug, status, locale, timezone, card prefix, public registration state |
| `TenantMembership` | User-to-tenant relationship with `owner` or `staff` role; platform superusers retain platform access but also receive explicit tenant membership where appropriate |
| `TenantBrand` | Contact details, logo and brand assets, email sender/copy, public-page text, colors, and approved font choices |
| `CardDesign` | Versioned, immutable-after-publication physical design settings: backgrounds, logo, front/back text, crop/focal settings, barcode settings, dimensions, bleed, DPI, and a design checksum |
| `CardBatch` | Tenant-owned allocation of card codes using a frozen design snapshot; generation status, code range, checksums, and immutable output paths |
| `PhysicalCard` | One physical code/inventory item: tenant, batch, code, status (`available`, `assigned`, `void`, `printed`), legacy flag, front/back/barcode artifacts, and optional customer relation |
| `PrintRequest` | Client request with quantity, approved design version, notes, delivery details, and status (`requested`, `review`, `approved`, `generated`, `printing`, `fulfilled`, `cancelled`) |
| existing `Klient` | Preserve the table and fields initially; add non-null tenant and optional physical-card relationships after backfill. Expose it in code as a loyalty customer. Rename only in a later explicit migration after the rollout is proven. |
| `WalletPass` | Stable Apple serial and Google object identifiers, version/status, generation timestamps, and protected artifact reference per customer/card |
| `POSConnection` | Tenant and provider (`dotykacka` first), non-secret configuration, encrypted credential material, connection state, and last successful test/sync |
| `POSToken` / evolved `AccessToken` | Token cache owned by a POS connection with expiry. Existing token rows remain intact and are marked as legacy during backfill. |
| `IntegrationJob` | Database-backed durable work item for POS sync, Wallet generation, email, and bulk operations; attempts, status, next retry, and redacted error summary |
| `ConsentRecord` | Tenant, customer, purpose, policy version, text/version hash, timestamp, source, and revocation state |
| `AuditEvent` | Actor, tenant, action, object reference, timestamp, and redacted metadata for design, printing, integration, and privileged operations |

### Required constraints

- Unique `Tenant.slug`.
- Unique `Tenant.card_prefix` initially, because physical barcodes may be scanned outside application context.
- Unique `(tenant, membership.user)`.
- Unique `(tenant, PhysicalCard.code)` plus a normalized code validator.
- Unique `(tenant, existing Klient.klient_id)` after the pre-constraint duplicate audit passes.
- Unique `(tenant, POSConnection.provider)` for the first release.
- A `PrintRequest` always references a published design version; changing settings creates a new design version and never changes an existing print request.
- Tenant-owned file paths include stable tenant, design/batch, and card identifiers. User-provided filenames never determine storage paths.

## 6. Tenant and authorization rules

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

## 7. Settings and printing UX

### Client settings area

Build Django template pages styled with compiled Tailwind and enhanced with HTMX fragments:

- **Organization** — names, contacts, locale/timezone, public registration state, and card prefix before the first new batch is allocated.
- **Brand assets** — upload/replace logo and background source images with file type, size, dimension, and decompression-bomb validation.
- **Physical card design** — controlled layout preset, front/back background, logo, tagline, contact text, colors, font from an approved bundled list, barcode type/placement, crop method, bleed, and DPI.
- **Live proof** — HTMX POST renders a server-side low-resolution front/back preview without saving a published design. Publishing creates a new immutable design version.
- **Registration and communications** — public text, consent policy/version, email subject/body/footer, Wallet descriptions, and sender identity.
- **POS integration** — choose a supported provider, enter masked credentials/configuration, test the connection, and view last sync/error state.
- **Print requests** — choose a published design, quantity, notes/delivery details, approve the proof, submit the request, and view status/history.

No free-form browser canvas is planned. A controlled form plus server-rendered preview is safer, reproducible, accessible, and achievable with HTMX. If a future drag-and-drop designer is desired, it requires a separate product and technology decision.

### Platform print center

- Queue across tenants with tenant, quantity, design version, request date, delivery, and status filters.
- Open the exact frozen proof and compare its checksum with the request.
- Approve/reject with an audit note.
- Allocate the next card code range transactionally so concurrent requests cannot overlap.
- Generate in a background database job and show progress through HTMX polling.
- Validate dimensions, DPI, bleed, fronts/backs count, code uniqueness, filenames, and checksums before making a package downloadable.
- Download a protected, immutable package containing front and back print sheets or per-card files, a manifest, and a human-readable job summary.
- Record `printing`, `printed`, `fulfilled`, or `cancelled` transitions with actor and timestamps. Cancellation never deletes generated artifacts or reuses issued codes.

Print layout settings must be confirmed with the real printer before production generation: finished card size, bleed, safe area, DPI, color profile, sheet size, cards per sheet, crop marks, duplex order/flip, file format, and filename convention.

## 8. Shared service architecture

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

## 9. POS integration design

Create a provider interface with these initial operations:

- validate configuration;
- test/authenticate connection;
- create or update one loyalty customer idempotently;
- fetch/reconcile customers;
- optionally read/write points only after the expected ownership rules are defined;
- normalize provider errors into redacted, user-safe statuses;
- expose provider capabilities so the UI does not assume every POS supports the same functions.

Implement `DotykackaAdapter` first by refactoring existing API behavior. Its cloud ID, discount group, authorization credential, access token, timeouts, and remote IDs become tenant/connection scoped. No global `DOTYKACKA_*` business setting may be used after the transition compatibility period.

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

## 10. Safe migration plan for Marta as the first tenant

### Pre-migration safeguards

- Take and verify an encrypted MariaDB backup and a separate immutable media backup.
- Restore both into a disposable staging environment and run the full migration there first.
- Record pre-migration counts for every table and checksums/counts for card asset directories.
- Put external integrations and email into safe/test mode during migration verification.
- Run a read-only preflight command that fails on duplicate card IDs, malformed codes, missing assets, or unexpected tenant-sensitive rows.
- Never remove a Docker/database volume as part of the migration procedure.

### Migration sequence

1. **Add tenant foundation** — create tenant, membership, brand/design, inventory, print, integration, consent, audit, and job tables. Add nullable tenant/relationship fields to existing `Klient` and `AccessToken`. Do not alter or drop existing fields.
2. **Create first tenant** — a forward data migration creates a stable Marta Banaszek / Atelier-Café tenant, initial brand/design snapshot, and a legacy physical-card batch for `MB-1` through `MB-600`.
3. **Assign current user** — the same reviewed data migration creates Marta tenant membership for every user that exists at the time of migration. In the verified replica this is the single `admin` user. Its superuser status remains unchanged so it can also perform platform operations.
4. **Assign all customers** — attach every pre-existing `Klient` row to Marta without modifying any personal data, card code, primary key, or Wallet URL.
5. **Import card inventory metadata** — create exactly one `PhysicalCard` row for each verified legacy code `MB-1` to `MB-600`. Attach the 267 matching customer records and mark those cards assigned; mark the remaining 333 available. Reference existing files as immutable legacy paths; do not copy, rename, or regenerate them in this migration.
6. **Assign POS state** — create Marta’s Dotykačka connection from non-secret existing configuration references and attach all existing `AccessToken` rows to it as legacy token records. Do not expose, rewrite, or delete the token values. New tokens use the encrypted connection-scoped path.
8. **Enforce tenant ownership** — only after verification, make required tenant foreign keys non-null and add composite uniqueness/check constraints in a separate migration.
9. **Switch application reads** — deploy tenant-scoped code while keeping all legacy columns and paths readable.
10. **Deferred cleanup** — do not drop `google_jwt_url`, global compatibility settings, legacy token data, old model names, or legacy file paths in this project phase. Any later cleanup requires a separate retention/archival plan, backup verification, user approval, and new migrations.

Data migrations should be idempotent by stable natural keys and have a no-op reverse. A production code rollback must continue to understand the additive schema; production must not reverse the tenant data migration.

### Required migration verification report

The deployment runbook must capture only non-sensitive aggregates:

- table counts before and after;
- null tenant/relationship counts;
- duplicate and malformed code counts;
- card status totals;
- orphan customer/card/assets counts;
- asset counts and checksums without customer PII;
- migration list and `manage.py check` output.

## 11. Implementation phases

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
- [x] Add tenant ownership to existing data using the additive migration sequence in section 10.
- [x] Import the `MB-1..600` inventory metadata and bind 267 customers.
- [x] Move client-owned Dotykačka, Brevo, and Google Wallet identifiers plus encrypted credentials into tenant database settings.
- [x] Add an owner-only integration settings page with masked secret retention and redacted audit events.
- [x] Replace global/unscoped customer, POS token, integration, and bulk queries with tenant-scoped services.
- [x] Keep compatibility routes for Marta and add the explicit tenant registration route.
- [x] Add migration, encryption, cross-tenant isolation, and platform/owner/staff role tests using a synthetic second tenant.

Acceptance gate: passed on 2026-07-17. Marta’s current user, all 267 customers, 600 cards, 261 tokens, 267 Wallet references, and legacy assets remain intact; all null/orphan/mismatch checks are zero and the synthetic second tenant cannot access Marta resources.

### Phase 2 — Django/HTMX/Tailwind portal shell

- [ ] Add a reusable Django base template, accessible navigation, forms, messages, and error fragments.
- [ ] Compile Tailwind into versioned static CSS using the approved build approach.
- [ ] Vendor a pinned HTMX build locally; do not depend on a runtime `latest` CDN.
- [ ] Remove Bootstrap and legacy jQuery from active loyalty screens after parity checks.
- [ ] Build client settings navigation and the separate platform print-center navigation.
- [ ] Keep only minimal JavaScript for camera access/barcode scanning; pin/vendor the scanner library and document why it is required.

Acceptance gate: core pages work without custom JavaScript; HTMX failures gracefully fall back to normal Django form submissions.

### Phase 3 — Tenant card design and unified generators

- [ ] Create versioned tenant brand and `CardDesign` forms/models.
- [ ] Refactor crop, logo/text composition, barcode rendering, front/back generation, manifest signing, Apple Wallet, and Google Wallet into tenant-aware services.
- [ ] Add server-rendered HTMX proof generation and validation.
- [ ] Add stable Apple serial and Google object records.
- [ ] Store new artifacts in immutable tenant/design/batch paths with checksums.
- [ ] Replace standalone loops with safe management commands using the shared services and `--dry-run`.
- [ ] Write golden-image/metadata tests for existing Marta output plus a clearly different synthetic tenant.

Acceptance gate: Marta’s proof remains visually compatible, a second tenant produces distinct branding/text/prefix, retries do not overwrite artifacts, and CLI/web paths produce equivalent results.

### Phase 4 — Centralized print request and fulfillment

- [ ] Implement client proof approval and print-request submission.
- [ ] Implement platform queue, status transitions, transactional code allocation, generation jobs, validation, protected download, and fulfillment history.
- [ ] Build the production package manifest and per-file checksums.
- [ ] Implement confirmed printer layout settings using Pillow first.
- [ ] Add quantity limits, allowed status transitions, duplicate-submit prevention, and audit events.
- [ ] Make generated production files immutable and prevent code reuse after cancellation.

Acceptance gate: two concurrent requests cannot receive overlapping codes; only a platform operator can download production files; every printed file can be traced to tenant, request, design version, batch, and checksum.

### Phase 5 — Tenant registration, Wallet, and communications

- [ ] Route public registration through tenant slug/domain and render tenant branding.
- [ ] Allocate only an existing available physical card or follow an explicitly chosen virtual-first policy.
- [ ] Store versioned consent evidence.
- [ ] Generate tenant-branded Apple/Google passes from stable records.
- [ ] Generate tenant-branded email from templates/settings with protected links.
- [ ] Use durable jobs for Wallet generation, POS sync, Brevo sync, and email; expose retryable status to authorized users.
- [ ] Add idempotent resend/retry actions with audit records.

Acceptance gate: registration for tenant A cannot allocate tenant B’s card, all branding is tenant-owned, consent is recorded, and a web-process restart cannot silently lose required work.

### Phase 6 — Dotykačka adapter and POS framework

- [ ] Add `POSConnection`, encrypted secrets, capability interface, job handling, and provider contract tests.
- [ ] Refactor Dotykačka authentication, token caching, customer creation, and reconciliation into the first adapter.
- [ ] Add tenant-scoped settings/test-connection/sync status UI.
- [ ] Decide and document source-of-truth/conflict behavior for profile data and loyalty points.
- [ ] Add webhook support only when a provider requires it, including signed request verification, tenant resolution, idempotency, and replay protection.
- [ ] Document the checklist for adding another POS without touching core views.

Acceptance gate: two synthetic tenants can use different provider configurations without token/customer crossover; provider downtime does not lose the local customer or block unrelated tenants.

### Phase 7 — Production hardening and SaaS rollout

- [ ] Add security headers, upload limits, protected media, rate limits for public registration, and redacted structured logging.
- [ ] Add health checks for web, database, worker heartbeat, storage write/read, and integration configuration without exposing secrets.
- [ ] Add database/media backup schedules and perform a restore drill.
- [ ] Add CI for tests, migration consistency, template/static build, and dependency/security checks.
- [ ] Add monitoring for failed jobs, print-generation failures, low card inventory, and repeated POS authentication failures.
- [ ] Write operator/client runbooks and a first-tenant migration/verification report.
- [ ] Run a staged Marta acceptance test before enabling creation of additional tenants.

Acceptance gate: restore drill passes, tenant isolation tests pass, Marta signs off on the migrated flow, and operations can trace/retry failures without direct database edits.

## 12. Test and release matrix

At minimum, every release must run:

- `python manage.py check`
- `python manage.py makemigrations --check`
- `python manage.py migrate --plan`
- full Django test suite on a fresh database and on an upgraded copy of the legacy schema;
- tenant isolation tests for list/detail/create/update/delete-like actions, downloads, jobs, and guessed IDs;
- migration assertions for the verified Marta counts and a blank-install path;
- generator golden tests for dimensions, barcode value/readability, design snapshot, manifest, and checksums;
- authorization tests for client owner, client staff, platform operator, anonymous registration, and cross-tenant denial;
- POS contract tests with success, timeout, authentication failure, rate limit, duplicate, and retry cases;
- print allocation concurrency and idempotency tests;
- HTMX and ordinary POST response tests;
- an external-call deny-list during tests and migrations.

No production release proceeds if it would produce an unplanned migration, null tenant owner, duplicate code, orphan card/customer, missing legacy asset, cross-tenant access, or external call during migration.

## 13. Decisions required before their phases

These do not block Phase 0 or the additive tenant foundation:

1. Confirm the first tenant’s exact display/legal name and public slug. The repository currently uses “Marta Banaszek / Atelier-Café”.
2. Confirm whether card prefixes must be globally unique across tenants and whether Marta keeps `MB` permanently. The recommended answer is yes to both.
3. Provide the printer’s production specification: finished size, bleed, safe area, DPI, color space/profile, sheet/imposition, crop marks, duplex orientation, preferred file type, and filename convention.
4. Confirm the card allocation rule: preprinted card scanned during customer registration, card assigned digitally first and printed later, or both.
5. Confirm what client users may download: recommended is low-resolution proof only, while production files remain platform-admin-only.
6. Define the initial POS contract beyond customer creation: customer updates, points/balance ownership, transaction sync, discounts, imports, and conflict rules.
7. Decide whether one user may belong to multiple tenant accounts in the first release. The proposed model supports it.
8. Decide whether custom client domains are required for the first release or tenant slugs are sufficient.
9. Define print-request commercial operations (billing, shipping, minimum quantity, and cancellation). Payment processing is not included in this plan without a separate approved scope.

## 14. Recommended first implementation slice

Start with Phase 0 plus the schema-only portion of Phase 1:

1. Add test coverage and the read-only preflight report.
2. Add tenant/membership models and nullable tenant foreign keys through migrations.
3. Add tenant-scoping helpers and isolation tests with synthetic data.
4. Implement and rehearse the Marta data migration on a restored replica.
5. Produce the aggregate verification report before applying any non-null constraint.

Do not begin visual settings, new card generation, or POS credential editing until this foundation proves that the existing 267 customer records and 600-card inventory remain unchanged and isolated under Marta’s tenant.
