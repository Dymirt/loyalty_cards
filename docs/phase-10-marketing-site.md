# Phase 10 — marketing and published pricing site

Completed and verified on 2026-07-18.

## Delivered surface

The root URL is now the public Loyalty Studio marketing site. It is rendered by
the `marketing` Django app with the existing Django templates and compiled
Tailwind CSS:

| Path | Purpose |
| --- | --- |
| `/` | Product overview and published-plan summary |
| `/funkcje/` | Product and operating workflow |
| `/integracje/` | Supported POS, Wallet and communication capabilities |
| `/cennik/` | Active published plans and public production pricing |
| `/kontakt/` | Consent-gated lead form |
| `/kontakt/dziekujemy/` | Ordinary-POST confirmation page |
| `/polityka-prywatnosci/` | Versioned public privacy notice |
| `/regulamin/` | Versioned public terms |
| `/turnkey/`, `/marketing/` | Permanent compatibility redirects to `/` |

The authenticated tenant portal, enrollment routes and platform administration
remain separate. The historical `turnkey_app` source stays in the repository,
but it is not installed and the active URL configuration does not import it.

## Public catalog boundary

`billing.public_catalog` exposes immutable, read-only data-transfer objects. It
selects only active plans and price books and, for each one, only the newest
published version. A newer draft does not hide or replace the last published
version. Tenant subscriptions, card packs, quotes, customers, integrations and
other tenant-owned records are never queried by the marketing views.

The replica currently contains no plan, plan-version, price-book or
price-book-version rows. The site therefore shows the truthful “Cennik w
przygotowaniu” state. No example commercial values were inserted. Actual
amounts will appear only after a platform operator publishes approved billing
versions.

## Contact evidence and fallback behavior

`MarketingLead` is a new additive, append-only record. It stores normalized
contact fields, a caller-provided UUID idempotency key, the exact privacy-policy
version, a SHA-256 consent-text hash and a content hash. Reusing the UUID with
the same content returns the existing record; reusing it with different content
is rejected. Updates and deletes are blocked in the model and the Django admin
is read-only.

The form works as an ordinary Django POST/redirect/GET flow. When HTMX is
available it swaps only the form region. A honeypot rejects bot submissions,
CSRF remains enabled and no external email or provider call occurs while the
lead is recorded. The platform operator can review the append-only leads in
Django admin until a separately approved notification/retention workflow is
introduced.

## Configuration

The public legal identity and version markers are platform configuration:

```text
MARKETING_LEGAL_NAME
MARKETING_LEGAL_ADDRESS
MARKETING_CONTACT_EMAIL
MARKETING_PRIVACY_VERSION
MARKETING_TERMS_VERSION
```

Startup checks require a legal name, valid contact email and non-empty privacy
and terms versions. The address is optional until the operator supplies it.
No credential is exposed to the marketing templates.

## Migration and data safety

Migration `marketing.0001_initial` only creates `marketing_leads`; it does not
read or update legacy records and it performs no external call. Before applying
it, the replica was backed up and both archives were validated:

| Backup | SHA-256 |
| --- | --- |
| `local-data/backups/pre-phase10-20260718-024917.sql.gz` | `64afe0b6deff013c6b50e280264cb538950a63db0aa95373eb15aa1bc9fd22de` |
| `local-data/backups/pre-phase10-runtime-20260718-024917.tar.gz` | `576f2d1da48cb90d50c6b14cbac56c313a3a5dd6d56164de2da859b8eaceb474` |

Recovery is forward-only: deploy compatible earlier code if needed, retain the
new empty/additive table, and correct behavior with another reviewed migration.
Do not reverse or drop the table on the protected replica.

Post-migration Marta invariants remained unchanged: 267 customers, 600 cards
(267 assigned and 333 available), 263 historical token rows, one membership,
three tenant integrations and 267 Wallet identities. There are zero enrollment
records, print requests and marketing leads on the replica. There are also zero
published commercial records, so the empty public catalog is expected.

The strict extraction verifier passed with 53 models, 53 content types, 212
permissions, 366 URL patterns, 39 management commands, 48 admin registrations
and three admin-log model groups.

## Verification

- `python manage.py check`: passed.
- `python manage.py makemigrations --check --dry-run`: no changes.
- `python manage.py migrate --plan`: no pending migrations.
- Fresh SQLite test database: 203 tests passed, with three expected
  database-specific skips.
- Fresh authorized MariaDB `test_django`: 203 tests passed with no failures.
- `npm run build`: compiled the marketing templates into the existing Tailwind
  asset.
- Browser smoke test: homepage, pricing, contact and privacy pages rendered;
  no console errors were reported and no contact form was submitted.
- The marketing pages work without JavaScript; HTMX is progressive enhancement
  only. No frontend framework, queue, payment provider or runtime service was
  added.

