# Phase 7 subscription, entitlement, usage, and pricing foundation

Completed on 17 July 2026. This phase adds billing and entitlement records without modifying, inferring charges for, or backfilling any historical Marta membership, customer, card, token, Wallet identity, provider connection, or media record.

## Result

- `billing` owns stable plans and price books plus immutable published versions.
- A published plan version has one entitlement policy for active seats, card issuance, included physical prints, rollover, and overage behavior.
- A tenant subscription points to an exact published plan version. Its monthly/yearly billing periods are created on demand from the subscription start boundary.
- An active seat is exactly an active `TenantMembership`. A pre-save activation gate checks the tenant plan under a transaction; it never deactivates or rewrites an existing member.
- The first physical or virtual card identity assignment creates one append-only `UsageEvent` with a tenant-scoped idempotency key. Repeating the assignment returns the same event. Image proofs, artifacts and provider retries never call usage accounting.
- Existing public physical-card registration calls the billing issuance boundary inside the same database transaction as customer/card assignment. A limit rejection rolls the entire registration back.
- Physical print calculation consumes included allowance first, then eligible non-expired prepaid packs, then the exact quantity tier. Shipping and displayed tax are applied from the selected published price-book version.
- Accepting a quote reserves its proposed pack quantities. The accepted quote, lines and commercial snapshot retain the exact plan, entitlement, period, price, tier, tax and shipping inputs even after later versions are published.

## Additive schema

Only `billing.0001_initial` was applied. It creates 13 new tables:

- plan, plan version and entitlement policy;
- tenant subscription and billing period;
- append-only usage event;
- price book, price-book version and card-price tier;
- tenant card pack and append-only accepted-quote pack allocation;
- quote and append-only quote line.

All foreign keys use `PROTECT`. Money uses fixed-scale decimals plus an uppercase three-letter ISO currency. Published plan/price versions and accepted quotes reject application-level updates/deletes. Usage, quote lines and pack allocations are append-only. The migration contains schema operations only, calls no provider, and created no commercial or Marta data.

## Configuration and compatibility

No plan, price, tax rate, pack expiry, cancellation/refund term, Stripe account, payment processor, invoice, or accounting integration is assumed or seeded.

Platform operators use `/dotykacka/platform/billing` to create stable plan/price-book identities, publish immutable versions, and assign subscriptions/purchased packs. Tenant owners use `/dotykacka/c/<slug>/billing` to see their subscription and usage, calculate a physical-card quote, and explicitly accept it. Owners cannot publish or edit commercial records. Both normal Django POST and HTMX quote responses work without custom JavaScript.

Marta intentionally has no Phase 7 subscription row yet. Her tenant page labels this as the unmanaged compatibility state: registration remains operational, historical cards are not back-billed, and print quotes remain unavailable until an approved published plan is assigned.

## Deterministic calculation

For a requested physical quantity:

1. Calculate the current period’s unused included-print allowance. When published rollover is enabled, unused allowance accumulates from the subscription start.
2. Reserve eligible pack balance by earliest expiry/creation order.
3. Select the configured per-card tier using the remaining billable quantity.
4. Add configured physical shipping.
5. Show configured tax as included, exclusive, or not applicable.
6. Freeze every input and line before the owner accepts.

Phase 8 now turns an accepted quote into a print request and consumes its reservation/allowance transactionally only when the platform allocates the production run. Phase 7 never records a card as produced merely because it was quoted. See `phase-8-centralized-printing.md` for the append-only consumption bridge and production workflow.

## Verification evidence

Pre-upgrade backups:

- database: `local-data/backups/pre-phase7-20260717-225519.sql.gz` — SHA-256 `d6548b2ba1c3491965b0e82cfe316541a0bf7262ef3e61bd782e8e3b23ce63c0`;
- runtime media: `local-data/backups/pre-phase7-runtime-media-20260717-225519.tar.gz` — SHA-256 `743f1a88dc01d3facad23fe4a5819c9eff2ed292330f02d232b83a1f3fab2730`.

Post-upgrade Marta invariants:

- 267 customers;
- 600 physical cards: 267 assigned and 333 available;
- 263 historical access tokens;
- 267 Wallet identities;
- one active historical tenant membership;
- three integration connections;
- zero plans, subscriptions, periods, usage events, price books, packs, quotes, quote lines or pack allocations immediately after migration.

The fresh isolated SQLite suite passes 133 tests, with the MariaDB row-lock concurrency test skipped only on SQLite. Tests cover retry idempotency, active-seat activation, tenant-isolated seat/card limits, unmanaged compatibility, included quota, concurrent allowance reservation, one-card overage, a tier edge, an exact 100-card pack, pack reservation, frozen accepted quotes, owner/staff/platform authorization, and HTMX fallback. The strict upgraded-Marta verifier passes with 38 models, 38 content types, 152 permissions, 243 URL patterns, 38 commands and 33 admin registrations.

## Recovery rule

Prefer a roll-forward code fix. Do not reverse `billing.0001_initial` after commercial or usage rows exist because reversal drops history tables. If this upgrade must be abandoned before any billing state is created, stop the web/worker processes and restore the verified SQL and runtime-media archives using the Phase 0 procedure. Never manually delete or rewrite usage, allocations, accepted quotes, or Marta rows.
