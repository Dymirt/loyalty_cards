# Loyalty Studio SaaS Rollout Plan

Status: Phase 12 production audit active; Apple/off-host/human approval pending

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

Until the Phase 12 gate closes, the immediate goal remains a traceable first
production cycle with valid provider connections, approved commercial data,
verified backups, central printing and signed tenant acceptance. Public sales
communication may improve in parallel, but it must not activate another tenant,
invent prices or widen the production rollout.

## Current baseline

- Phases 0–11 are implemented and the current MariaDB suite passes all 242
  automated tests; the earlier SQLite baseline has three expected
  database-specific skips.
- The active public, tenant and platform interfaces use Polish; native Django
  locale middleware and translation catalogs are the extension point for future
  languages. No second language is exposed before its catalog is complete.
- Marta Banaszek Atelier-Café retains the protected 267-customer historical
  baseline. The production audit observed 269 customers and 600 physical cards:
  269 assigned and 331 available. Existing business and media data remain intact.
- The platform, integration, print and monitor processes are healthy; backup and
  restore drills pass.
- No plan, price book, payment provider or historical fulfillment event has been
  invented for Marta.
- Additional paying tenants remain disabled.
- The public Polish sales journey is benefit-led and separates prospective
  tenants from existing cardholders. It uses only verifiable product
  capabilities, one clear consultation path and no invented results, prices or
  testimonials.

## Launch blockers

1. Marta has not completed the human acceptance checklist.
2. Marta's Brevo connection passed its explicit production test on 2026-07-19;
   the prior redacted `brevo_unauthorized` result is resolved without moving the
   tenant key to `.env`.
3. Google Wallet, SMTP, Dotykačka Connector and Marta's Dotykačka cloud passed
   on 2026-07-19. Apple Wallet remains blocked by the Pass Type certificate that
   expired on 2026-06-25 and must be renewed before acceptance.
4. The real printer specification and one supervised production proof/package
   have not been approved.
5. Plan limits, prices, tax, shipping, invoicing/payment ownership and legal
   publication inputs are not yet approved.
6. Marta's historical `MB-1..600` printed/delivered ranges and references remain
   unknown, so no reconciliation event may be recorded yet.

## Phase 12 — Marta launch acceptance

- [x] Create and verify a current database/runtime backup.
- [ ] Confirm a recent encrypted off-host generation exists.
- [x] Verify production host, HTTPS, HSTS, secure-cookie, trusted-proxy, CSRF,
  storage and supervisor settings using the deployment gate in `README.md`.
- [ ] Run the platform system checks for Apple Wallet, Google Wallet, SMTP and
  Dotykačka; all pass except the expired Apple certificate. Expose no secret or
  token values in evidence.
- [x] Run the explicit Brevo connection test. If it fails, replace only Marta's
  encrypted tenant API key and retest; never move the key back to `.env`.
- [ ] Marta verifies brand/legal/contact data, tenant isolation and portal access.
- [ ] Perform one controlled enrollment with an approved unused card and test
  contact details; verify POS, Brevo, Wallet, email and redacted follow-up state.
- [ ] Review one approved quote and print-request preview without recording
  production or delivery unless separately authorized.
- [ ] Record acceptance date, approver, results and safe references without
  credentials or customer data.

Technical evidence and the remaining blockers are recorded in
`docs/phase-12-marta-launch-acceptance.md`.

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

## Phase 16 — Repeatable tenant acquisition and faster onboarding

- [x] Replace technical public copy with Polish benefit-led pages for the home,
  benefits, connections, offer and contact journey.
- [x] Give prospective tenants one consistent call to action and keep the
  cardholder registration area visibly separate from the business offer.
- [x] Explain the value for the customer, front-line team and business owner
  without unapproved performance claims, testimonials or prices.
- [ ] Publish focused pages for the first approved business segments, starting
  with cafés/restaurants and appointment-based services. Each page must use a
  real segment need and an approved offer, not duplicated keyword copy.
- [ ] Add a guided programme preview where a prospect can choose a business
  type, colours and card format, then request the resulting start proposal.
- [ ] Prepare approved launch kits with ready-to-customise programme wording,
  staff instructions, counter materials and registration QR artwork for each
  target segment.
- [ ] Give every qualified lead a visible owner, next action and follow-up date;
  retain the original enquiry and every contact outcome as history.
- [ ] Add a short readiness questionnaire covering locations, expected members,
  first print run, current POS, desired Wallet formats and communication needs,
  so the first conversation starts with a useful brief.
- [ ] Create a guided tenant launch checklist that shows brand approval,
  connection readiness, card proof, staff preparation and launch status in one
  place.
- [ ] Offer a safe demonstration programme using synthetic people and cards so
  prospects can experience the owner and customer journeys without seeing a
  real tenant's data.
- [ ] Publish an Atelier-Café case study only after Marta approves the name,
  content and any figures. Record the measurement period and never imply
  causation that the evidence does not support.
- [ ] Add referral and partner attribution only with clear consent and published
  privacy terms; do not add behavioural advertising or hidden visitor tracking.
- [ ] After commercial approval, present simple start packages by outcome
  (digital start, physical-and-digital launch, multi-location) while keeping the
  signed plan and print calculation authoritative.
- [ ] Measure the sales journey using privacy-approved aggregate events:
  offer viewed, contact started, qualified lead, proposal sent, tenant accepted
  and time to launch. Use the results to remove onboarding friction rather than
  invent marketing claims.

Acceptance gate: a prospect can understand the offer, identify a suitable start
path and submit a useful brief on mobile without technical knowledge; every
public claim and case-study figure has an owner and approval; lead follow-up is
traceable; a second tenant can move from enquiry to signed acceptance using the
same documented journey without exposing another firm's data.

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
