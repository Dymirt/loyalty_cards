# Loyalty Studio SaaS Rollout Plan

Status: technical platform complete; first-tenant launch approval pending

Updated: 2026-07-19

This plan starts after the completed Phase 0–11 conversion. The historical plan
is preserved in `docs/archive/saas-conversion-plan-phases-0-11.md`. Stable
product, architecture, configuration and safety rules are maintained in
`README.md` and apply to every phase below.

## Objective

Move the verified modular Django platform from technical readiness to a
controlled SaaS launch: approve Marta as the first tenant, certify the real
commercial/printing workflow, onboard one additional tenant safely, and then
remove only those compatibility paths proven unnecessary.

The immediate goal is not feature expansion. It is a traceable first production
cycle with valid provider connections, approved commercial data, verified
backups, central printing and signed tenant acceptance.

## Current baseline

- Phases 0–11 are implemented and the current MariaDB suite passes all 228
  automated tests; the earlier SQLite baseline has three expected
  database-specific skips.
- The active public, tenant and platform interfaces use Polish; native Django
  locale middleware and translation catalogs are the extension point for future
  languages. No second language is exposed before its catalog is complete.
- Marta Banaszek Atelier-Café owns 267 customers and 600 physical cards: 267
  assigned and 333 available. Existing business and media data remain intact.
- The platform, integration, print and monitor processes are healthy; backup and
  restore drills pass.
- No plan, price book, payment provider or historical fulfillment event has been
  invented for Marta.
- Additional paying tenants remain disabled.

## Launch blockers

1. Marta has not completed the human acceptance checklist.
2. Marta's Brevo connection retains the redacted status `brevo_unauthorized` and
   needs an explicit platform test or tenant-key replacement.
3. Apple, Google Wallet, SMTP and Dotykačka must pass the production system
   checks at launch time; configuration presence alone is not approval.
4. The real printer specification and one supervised production proof/package
   have not been approved.
5. Plan limits, prices, tax, shipping, invoicing/payment ownership and legal
   publication inputs are not yet approved.
6. Marta's historical `MB-1..600` printed/delivered ranges and references remain
   unknown, so no reconciliation event may be recorded yet.

## Phase 12 — Marta launch acceptance

- [ ] Create and verify a current database/runtime backup, and confirm a recent
  encrypted off-host generation exists.
- [ ] Verify production host, HTTPS, HSTS, secure-cookie, trusted-proxy, CSRF,
  storage and supervisor settings using the deployment gate in `README.md`.
- [ ] Run the platform system checks for Apple Wallet, Google Wallet, SMTP and
  Dotykačka; expose no secret or token values in evidence.
- [ ] Run the explicit Brevo connection test. If it fails, replace only Marta's
  encrypted tenant API key and retest; never move the key back to `.env`.
- [ ] Marta verifies brand/legal/contact data, tenant isolation and portal access.
- [ ] Perform one controlled enrollment with an approved unused card and test
  contact details; verify POS, Brevo, Wallet, email and redacted follow-up state.
- [ ] Review one approved quote and print-request preview without recording
  production or delivery unless separately authorized.
- [ ] Record acceptance date, approver, results and safe references without
  credentials or customer data.

Acceptance gate: every applicable item in
`docs/runbooks/marta-acceptance.md` is signed; all critical health checks are
green; the controlled enrollment is traceable and idempotent; no cross-tenant
access or unapproved external/production action occurred.

## Phase 13 — Commercial and print-production certification

- [ ] Obtain the printer's written finished size, bleed, safe area, DPI, color
  profile, sheet/imposition, crop-mark, duplex orientation, file-format and
  naming requirements.
- [ ] Decide whether `per-card-jpeg-zip-v1` is accepted or implement a new
  versioned profile only after the printer requirements prove it necessary.
- [ ] Generate one supervised test package from an immutable approved proof;
  verify manifest, file count, dimensions, checksums and physical output.
- [ ] Approve monthly plan limits, card allowances, pack quantities, overage
  tiers, PLN prices, tax, shipping, expiry and cancellation/refund terms.
- [ ] Decide invoicing/payment ownership. Keep manual invoicing if approved;
  introduce no payment provider without a separate design/security review.
- [ ] Publish immutable plan and price-book versions, then explicitly assign
  Marta. Do not back-bill historical users, cards or print work.
- [ ] Confirm legal company data and publish the approved pricing/legal pages.
- [ ] Obtain Marta's verified historical printed/delivered card ranges, dates and
  references; run the no-write preview and append only the confirmed events.

Acceptance gate: a physical production sample is approved, published prices
match the signed commercial decision, Marta's subscription begins explicitly,
and any legacy fulfillment reconciliation exactly matches the operator's
confirmed preview.

## Phase 14 — Second-tenant onboarding pilot

- [ ] Select one pilot tenant and record display/legal name, owner, globally
  unique prefix, locale/timezone and subscription before activation.
- [ ] Create membership and tenant configuration without copying Marta's brand,
  customer, card, credential, Wallet or commercial records.
- [ ] Publish the tenant's own brand/design proof and allocate only its inventory.
- [ ] Configure tenant-owned POS/Brevo values and platform-owned Wallet/SMTP
  services through the documented ownership boundary.
- [ ] Verify slug/domain registration, portal roles, guessed-ID denial, protected
  downloads and provider/job isolation against Marta.
- [ ] Run a controlled enrollment and quote/print preview for the pilot tenant.
- [ ] Observe one supervised operating cycle: health, retries, inventory alerts,
  entitlement usage, backup and restore-verifier results.
- [ ] Document onboarding friction and automate only repeated, well-understood
  operator steps with Django/HTMX.

Acceptance gate: the pilot tenant completes its own acceptance checklist; all
isolation tests and operational checks pass; no Marta record or artifact changes
except expected platform-wide operational heartbeat/alert history.

## Phase 15 — Compatibility retirement and operational scaling

- [ ] Review access logs and callers for legacy bulk routes, `/turnkey/`,
  `TURNKEY_ALLOWED_HOSTS_FILE`, project import shims and standalone generator
  wrappers.
- [ ] Move any remaining mutating legacy bulk action onto bounded durable jobs;
  retain read compatibility until all callers are verified.
- [ ] Remove a compatibility path only in a dedicated release with tests,
  release notes and an additive/state-preserving migration where schema state is
  involved. Never delete historical migrations, tokens, Wallet paths or media.
- [ ] Define approved retention/anonymization for marketing leads, operational
  rate-limit buckets and stale heartbeats; implement no deletion before legal and
  recovery requirements are agreed.
- [ ] Measure database, worker, generation, storage and backup duration before
  changing process counts or introducing infrastructure.
- [ ] Prioritize the next POS adapter only after a signed provider contract and
  provider-neutral contract tests exist.

Acceptance gate: active traffic no longer depends on retired paths, retention is
approved and auditable, measured capacity supports the next tenant cohort, and
no new runtime stack was added without explicit approval.

## Deferred product work

The following is intentionally outside the current launch sequence:

- points/balance/transaction synchronization beyond customer identity and
  status, until conflict rules are specified with the local database remaining
  the source of truth;
- cross-tenant promotions or one card accepted by partner tenants;
- tenant-owned Apple/Google issuer accounts;
- additional POS providers;
- a physical `Klient` model/table rename;
- automated payment collection;
- PDF/sheet imposition not required by the chosen printer.

Each item needs its own plan, acceptance criteria and migration/security review.

## Release gate for every phase

Before changing the protected replica or production environment:

1. Create and verify database/runtime backups.
2. Review migration SQL/plan; apply only reviewed forward migrations.
3. Run Django checks, deployment checks, migration drift, strict extraction and
   the complete isolated test suite.
4. Build committed Tailwind/vendor assets and run Python/Node dependency audits.
5. Verify liveness/readiness, worker heartbeats, storage and the operations page.
6. Run `verify_saas_rollout --expect-marta` when Marta's protected replica is in
   scope.
7. Record outcomes and rollback/compensation steps. Never use data deletion as a
   routine rollback.

No release proceeds with an unplanned migration, failed isolation assertion,
missing backup, cross-tenant access, orphan/duplicate card, missing immutable
artifact, unresolved critical alert or external call from a migration/test.
