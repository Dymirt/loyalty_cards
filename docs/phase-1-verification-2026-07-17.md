# Phase 1 local-replica verification — 2026-07-17

This report contains aggregate/non-sensitive verification only. No credential,
access-token value, customer identity, email, telephone number, or signed Wallet
URL was printed.

## Backups taken before migration

| Backup | Size | SHA-256 |
| --- | ---: | --- |
| `local-data/backups/pre-phase1-20260717-175348.sql.gz` | 175 KB | `71637585665e40322a255def368b373cbb119b450abc571e4b9a4472c282d37c` |
| `local-data/backups/pre-phase1-media-20260717-175348.tar.gz` | 533 MB | `6472976edd4966006d7fa494b0981fe74339ac0ec103736e58585b64e1b8fbae` |
| `local-data/backups/post-phase1-20260717-180307.sql.gz` | 199 KB | `8c61c9314568424dcef6f87de65f1717c790e1343c03a94698e56dad5af33b3e` |

All gzip streams passed an integrity check. The post-migration database backup
contains the completed backfill and encrypted tenant configuration.
`local-data/` is ignored and the backup files are not part of the repository.

## Pre- and post-migration legacy inventory

The read-only preflight returned the same values before and after migration:

| Check | Result |
| --- | ---: |
| Customers | 267 |
| Cached Dotykačka tokens | 261 |
| Application users | 1 |
| Card inventory | 600 |
| Assigned / available | 267 / 333 |
| Duplicate code groups | 0 |
| Invalid codes | 0 |
| Out-of-range codes | 0 |
| Missing legacy assets | 0 |

## Applied migration set

- `0008_alter_klient_klient_id_unique`
- `0009_tenant_foundation`
- `0010_backfill_marta_tenant`
- `0011_require_tenant_ownership`

All four migrations completed successfully and are recorded as applied.

## Marta backfill verification

| Check | Result |
| --- | ---: |
| Marta tenant | 1 |
| Owner memberships | 1 |
| Marta customers | 267 |
| Marta cached tokens | 261 |
| Integration providers | Brevo, Dotykačka, Google Wallet |
| Physical cards | 600 |
| Assigned / available | 267 / 333 |
| Dotykačka secret configured | yes |
| Brevo secret configured | yes |
| Existing non-empty Wallet references | 267 |
| Null customer tenant relationships | 0 |
| Null token connection relationships | 0 |
| Customer/token/card rows owned by another tenant | 0 |
| Assigned/available relationship mismatches | 0 |
| Invalid encrypted-secret format | 0 |

## Application verification

- `python manage.py check`: passed against the migrated MariaDB replica.
- `python manage.py makemigrations --check --dry-run`: no changes detected.
- Full isolated Django suite: 64 tests passed; unmocked external HTTP and SMTP
  calls were blocked.
- Legacy registration route: HTTP 200.
- Explicit Marta tenant registration route: HTTP 200.
- Integration settings while anonymous: HTTP 302 to authentication.

The local web container was restarted after migration so Apache/mod_wsgi loaded
the new URL map. The MariaDB container and its volume were not restarted,
removed, or replaced.
