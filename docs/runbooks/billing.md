# Billing and commercial-data runbook

1. A platform operator creates a plan draft, entitlement policy and price-book
   tiers. Money is decimal plus ISO currency; tax and shipping must be explicit.
2. Review all fields before publishing. Published plan versions, price-book
   versions and tiers are immutable; correct them with a later version.
3. Assign one non-overlapping active subscription to the tenant and open the
   applicable billing period. Never infer historical Marta cards as billable
   usage.
4. Tenant quote calculation resolves allowance, eligible pack, tier, shipping
   and tax in that order. Acceptance freezes the calculation.
5. A later publication must not alter an accepted quote, consumed pack amount or
   print request.
6. The public pricing page reads only active, published versions. Drafts,
   subscriptions, tenant packs and internal quotes never appear publicly.
7. No payment processor or automated invoice is active. Record no payment as
   collected unless a separately approved accounting workflow exists.

