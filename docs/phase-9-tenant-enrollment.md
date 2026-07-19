# Phase 9 tenant enrollment and durable follow-up workflow

Phase 9 was implemented and verified on 18 July 2026. It moves the public
registration transaction into the `enrollment` app and keeps the existing
preprinted-card policy: a customer scans or enters a card already present in
that tenant's available inventory. No virtual-first allocation rule was
invented.

## Safety and recovery evidence

Before any Phase 9 schema migration, the local MariaDB replica and runtime
artifacts were backed up and validated:

| Backup | SHA-256 |
| --- | --- |
| `local-data/backups/pre-phase9-20260718-020239.sql.gz` | `d067d36957a4d4a41ca0bb25afe08466891d070c66f25ebdf7e31eb3a5de2d8b` |
| `local-data/backups/pre-phase9-runtime-20260718-020239.tar.gz` | `14cae74d3cdcdc372cf81f3dcf24fa0493d4138fecdb3b353ee0af210e806837` |

`gzip -t` passed for the SQL dump. The runtime archive was listed successfully
and contains `local-data/media`, `local-data/mypass_template`, and the protected
print-package directory. These files contain private replica data and remain
ignored by Git.

Recovery is forward-only. If the application code must be rolled back, keep the
new tables and deploy code compatible with them. Restore the SQL and runtime
archives only as a separately approved replica recovery; do not reverse or
delete enrollment history.

## Additive schema

The following migrations were applied:

- `communications.0001_initial`
- `enrollment.0001_initial`
- `tenants.0001_initial`
- `tenants.0002_portable_primary_domain`
- `tenants.0003_backfill_primary_domain_marker`
- `tenants.0004_primary_domain_marker_constraint`

They add these records without changing historical customer, card, token,
Wallet, integration, billing, or printing rows:

- `Enrollment` freezes the committed tenant, customer, physical card, consent,
  optional managed-billing usage event, brand revision, design, and snapshots.
- `EnrollmentAccessLink` stores only a random selector, purpose, reason and
  database expiry. The capability presented to the customer is signed with the
  platform secret; no raw token is stored.
- `EnrollmentFollowUp` links one enrollment operation and generation to one
  durable integration job.
- `EnrollmentEvent` is the append-only, idempotent workflow/audit timeline.
- `CommunicationDelivery` guards an SMTP attempt and stores a recipient hash,
  frozen subject, generation, and sent/unknown outcome rather than an address.
- `TenantDomain` records pending, verified, or disabled registration hostnames.
  A nullable one-to-one marker gives MariaDB a real database constraint for at
  most one primary domain per tenant.

No Marta enrollments were inferred from the 267 historical customers. The new
tables were empty immediately after migration.

## Registration transaction

The local transaction is the source of truth and performs these operations in
order:

1. resolve the tenant from a verified domain, explicit tenant slug, or globally
   unique card prefix;
2. lock the tenant and matching available physical card;
3. create the tenant-owned customer and assign the locked card;
4. record the managed billing issuance when the tenant has an active
   subscription, plus one local issuance event in all cases;
5. hash and store the exact consent text and policy version;
6. freeze the published brand/design and consent snapshots in `Enrollment`;
7. create an expiring signed status link and redacted audit event;
8. commit, then enqueue provider work through `transaction.on_commit`.

If another request wins the row lock or a constraint, the entire losing
transaction rolls back. It cannot leave an orphan customer, consent, usage
event, or card assignment. The global registration route preserves Marta's
existing path and recognizes other tenants by prefix. When the prefix resolves
to a different tenant, the form shows that tenant's brand and consent text and
requires confirmation before committing.

## Durable follow-ups and email safety

Available integrations produce stable version-1 job keys for Apple Wallet,
Google Wallet, Dotykačka customer upsert, Brevo contact upsert, and the card
email. Jobs contain identifiers only; provider secrets and customer contact
data are never copied into job payloads.

Provider retries reuse the original job and provider idempotency behavior. A
tenant owner or platform superuser can inspect redacted status and explicitly
retry a terminal non-email failure. Repeating the same action key returns the
same result.

SMTP cannot prove exactly-once delivery across a process crash. Therefore a
delivery is recorded as `sending` before calling the backend. If the call fails
or a worker restarts while that state is unresolved, the result becomes
`outcome_unknown` and automatic replay is blocked. An authorized user must use
the explicit resend action, which creates a new generation, a new expiring
link, a new durable job, and an audit event. A confirmed sent generation is
never sent automatically a second time.

## Public and tenant surfaces

- `/dotykacka/register` — compatible global route; resolves a tenant by the
  globally unique card prefix.
- `/dotykacka/c/<tenant-slug>/register` — explicit tenant registration.
- a verified tenant hostname — resolves the same form without exposing another
  tenant.
- `/dotykacka/enrollment/status/<signed-token>` — public, expiring, redacted
  Wallet/follow-up status.
- `/dotykacka/enrollment/status/<signed-token>/apple-pass` — protected Wallet
  file response using the same capability and expiry.
- `/dotykacka/c/<tenant-slug>/enrollments` — owner/platform enrollment history,
  domain requests and consent/follow-up access.

Tenant domain requests remain pending until a platform operator verifies DNS,
TLS, allowed-host and proxy routing, then marks the hostname verified. A request
never activates external routing automatically.

`ENROLLMENT_LINK_TTL_DAYS` is platform configuration and defaults to 30. A
security system check rejects zero, negative, or non-numeric values.

## Verification result

The final isolated SQLite suite passes 192 tests; three database-specific cases
are skipped on SQLite. The focused Phase 9 suite covers tenant-prefix and domain
resolution, cross-tenant authorization, access-link expiry, immutable snapshots,
consent evidence, post-commit/idempotent jobs, explicit retry/resend generations,
ambiguous email delivery and database primary-domain uniqueness.

The existing Django database user has separately approved privileges limited to
`test_django.*`. All three MariaDB row-lock tests pass against that isolated
database: two submissions converge on one enrollment/card assignment, concurrent
billing retries converge on one issuance event, and concurrent print allocations
produce non-overlapping ranges. `--keepdb` preserves this test schema for later
runs; none of these tests use the Marta replica database.

After migration:

- `check`: passed;
- `makemigrations --check --dry-run`: no changes;
- `migrate --plan`: no pending operations;
- `verify_app_extraction --strict --expect-marta`: passed with 52 models,
  52 content types, 208 permissions, 352 URL patterns, 39 commands, and 47 admin
  registrations;
- Marta: 267 customers, 600 cards (267 assigned, 333 available), 263 historical
  access-token rows, 267 Wallet identities, one membership and three integration
  connections;
- Phase 8 print requests/runs/packages/events: all zero;
- Phase 9 domains/enrollments/links/events/follow-ups/deliveries: all zero.

No test or migration contacted Dotykačka, Brevo, Apple, Google, or SMTP.
