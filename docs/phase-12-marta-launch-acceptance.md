# Phase 12 — Marta production launch acceptance

Date: 2026-07-19

Production: `https://club.mbstudio.online`

Status: technical audit partially passed. Launch acceptance remains blocked by
the expired Apple Wallet certificate, missing evidence of an encrypted off-host
backup generation, the controlled enrollment/quote checks and Marta's human
approval.

No production customer, card, credential or media record was deleted,
overwritten or reconciled during this audit.

## Production and recovery evidence

- The audited deployment initially matched `main` at
  `2e26a1d83d7a2fff103c96188370b9901ee324f7`.
- HTTPS liveness and readiness returned HTTP 200 with redacted bodies.
- Django runs with debug disabled, HTTPS redirect, secure session/CSRF cookies,
  trusted proxy scheme handling, the production host/CSRF origin and one-year
  HSTS with subdomains and preload enabled.
- TLS covers `*.mbstudio.online` and was valid through 2026-09-23 at audit time.
- Apache and the integration, print and monitor workers were active. Apache's
  configuration test passed. Storage had approximately 8.6 GB free.
- Full backup manifest:
  `phase12-launch-acceptance-20260719-143821-495369.manifest.json`.
  The checksummed database archive and 3,625-member runtime archive passed
  `verify_platform_backup` with format version 1.
- No scheduled backup timer was installed on the host. The Phase 12 repair makes
  deployment install and enable `loyalty-backup.timer` against the active
  release. Its calendar was validated for 02:30 Europe/Warsaw.
- The repository and host do not provide evidence of a copied, encrypted
  off-host generation. This remains an operator action; the audit did not copy
  production data to an unapproved destination.

## Redacted provider results

| Check | Result |
| --- | --- |
| Brevo — Marta | passed; one active tenant connection, zero failures |
| Dotykačka Connector | passed; platform credentials generated the expected HMAC-SHA256 signature |
| Dotykačka — Marta | passed; encrypted tenant Refresh Token exchanged for Cloud ID `350830718` |
| Google Wallet | passed; central issuer `3388000000022973962` was authenticated and readable |
| SMTP | passed; login succeeded and no test message was sent |
| Apple Wallet | failed; Pass Type certificate expired 2026-06-25 15:52 UTC |

The Brevo API key remains encrypted on Marta's tenant connection. No key, token
or credential value appears in this evidence.

## Data and application findings

- The historical floor remains 267 customers/cards assigned. The production
  audit observed 269 customers, 269 assigned cards, 331 available cards, 269
  Wallet identities and 264 historical access-token rows.
- The two additional customer/card/Wallet records are valid aggregate growth,
  not baseline loss. The previous acceptance commands incorrectly required the
  launch-day counts to remain exactly 267/333/263. They now enforce historical
  minimums, one-to-one customer/card/Wallet relations, required encrypted
  connections and zero cross-tenant ownership mismatches.
- The public Polish home page and Marta registration route loaded over HTTPS.
- Mobile inspection at 390 px exposed a broken raw master-artwork background.
  Registration now uses the bounded public web background, while future design
  publications create a new immutable maximum-1920-pixel JPEG derivative and
  leave the master image unchanged.
- No migrations are introduced by these repairs.

## Remaining acceptance actions

1. Renew the Apple Pass Type ID certificate for
   `pass.club.mbstudio.online`, install it with its matching private key and
   rerun the Apple system test.
2. Copy one verified generation to an approved encrypted off-host destination
   and record only its safe reference/checksum evidence.
3. Marta confirms legal/brand/contact data, tenant-only portal access and the
   card proof on desktop and mobile.
4. Use an explicitly approved unused card and test contact data for one
   controlled enrollment. Confirm POS, Brevo, Wallet, SMTP and redacted
   follow-up state without using a real customer's data.
5. Review one approved quote and print-request preview. Do not record production
   or delivery without separate authorization.
6. Record Marta's approver and acceptance date without credentials or customer
   data. Until then, additional paying tenants remain disabled.
