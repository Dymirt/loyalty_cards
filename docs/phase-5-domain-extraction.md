# Phase 5 tenant, customer, card, and artwork extraction

Completed: 2026-07-17

Phase 5 moves behavior and UI ownership without moving any historical model or
table. The `dotykacka` app remains installed and its migrations `0001` through
`0013`, all 13 model labels, all `dotykacka_*` table names, primary keys,
foreign keys, content types, permissions, admin-log references, URL names and
media paths remain intact.

## Domain ownership

- `tenants` owns tenant lookup, membership authorization, brand form, portal
  query service, portal view/template, admin classes and tests.
- `customers` exposes `Customer` as a code-facing alias of historical
  `dotykacka.Klient`, and owns customer persistence/query services, customer
  forms/templates/admin/tests, `CustomerExternalIdentity`, and append-only
  `ConsentRecord`.
- `cards` owns card-code parsing, transactional inventory assignment/query
  services, the current platform inventory view/template, admin and tests.
- `card_artwork` owns the card-design form/view/templates/admin, deterministic
  renderer, exact crop-plan calculation, immutable artifact publisher, and
  `generate_card_artifacts` command.
- `enrollment` is a small orchestrator over customer and card services. It
  preserves public registration while removing direct cross-domain writes from
  the HTTP view. Durable follow-up jobs remain Phase 6 work.

Canonical namespaced routes are registered before the compatibility URLconf.
Every old `dotykacka:*` reverse name and path remains available and points to
the same extracted view. `dotykacka.card_codes`, `dotykacka.tenancy`,
`dotykacka.services.card_designs`, old templates, and standalone artwork
scripts are deprecated import/dispatch wrappers.

## Additive schema

Four migrations create exactly three final-owner tables and then add explicit
per-integration synchronization state to the new external-identity table:

```text
customers.0001_customer_domain_models
  customers_customerexternalidentity
  customers_consentrecord
customers.0002_external_identity_sync_status
  pending/synced/failed/disabled status, attempt time, redacted error code
customers.0003_external_identity_pending_remote_id
  allow multiple pending identities before a provider returns a remote ID

card_artwork.0001_crop_plan
  card_artwork_cropplan
```

The reviewed MariaDB SQL contains `CREATE TABLE`, constraints, indexes and
foreign keys on these new tables only. It contains no rename, copy, update,
delete, truncate, drop, or alteration of a pre-Phase-5 business table. All
migrations were applied forward with `--noinput`; they contain no data
operation and initially created zero rows.

`ConsentRecord` is append-only and stores the submitted policy text plus its
SHA-256 checksum. `CustomerExternalIdentity` stores a remote ID/version plus an
explicit per-provider sync status and attempt/success timestamps. `CropPlan` is immutable and stores design/card identity,
deterministic seed, source checksum/dimensions, resized dimensions, exact crop
rectangle and renderer version. Cross-tenant validation is enforced before a
new record is saved.

## Master-image and generator flow

The tenant owner uploads one large source image and optional logo. A normal
Django multipart form, enhanced by HTMX, calls `card_artwork.services` to render
3–12 deterministic branded sample cards. A draft sample sheet does not allocate
a card or write a crop plan. Publishing creates a new immutable design and
brand revision; proof and card generation persist/reuse the exact crop plan.

Web previews, proof publication, the management command, Apple Wallet's
temporary compatibility caller, and the standalone wrapper scripts call the
same renderer. A retry reuses the crop plan and produces identical card bytes,
but publishes artifacts under a new run path and never overwrites old bytes.

## Safety and verification

Before migration, transaction-consistent database and media backups were
created under the ignored `local-data/backups/` directory:

- `pre-phase5-20260717.sql.gz` — 299 KB, SHA-256
  `2fed04a00ef0f6fc2883026ccaaad15b02b5392b3427f2d66b42ba17b73657ff`;
- `pre-phase5-media-20260717.tar.gz` — 533 MB, SHA-256
  `7d4fe6ef6c0647188007d4d9149ae7632e111173bc5df1549102c3b712b94563`.

The pre- and post-migration checks report:

| Check | Result |
| --- | --- |
| Legacy customer/card/token aggregates | 267 customers; 600 cards; 263 tokens |
| Card status | 267 assigned; 333 available |
| Legacy data/media errors | 0 duplicates, malformed/out-of-range codes, or missing assets |
| Wallet/design invariants | 267 Wallet identities; 1 design; 1 brand revision; 1 linked batch; 0 tenant mismatches |
| Migration consistency | No model changes detected; no migrations left to apply |
| Extraction inventory | 22 models, 22 content types, 88 permissions, 139 URL patterns, 37 commands, 17 admin registrations |
| Fresh isolated database | 101 tests pass; unmocked external calls remain blocked |
| Marta golden artwork | Existing pinned SHA-256 remains byte-identical |
| Deterministic crop test | Identical input produces identical coordinates, metadata and bytes |

Run the release gate with:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py verify_app_extraction --strict --expect-marta
python manage.py preflight_legacy_inventory --expect-customers 267 --expect-users 1 --json
python manage.py test
```

## Rollback

Rollback means deploying the prior compatible application code. Do not reverse
the Phase 5 migrations in a protected environment: future consent, identity or
crop-plan rows may exist, and reversing would drop their tables. The prior code
ignores the additive tables. Never remove the MariaDB volume, media directory,
historical migrations, compatibility paths, token rows or generated assets as
part of rollback.
