# Phase 11 — Production hardening and SaaS rollout evidence

Date: 2026-07-18

Status: technical implementation and automated rollout gate passed. Marta's
human first-tenant acceptance remains pending, so additional paying tenants are
not enabled.

## Delivered controls

- `operations` owns database-backed rate-limit windows, worker heartbeats,
  operational alerts and append-only alert events through additive migration
  `0001_initial`.
- The platform adds request IDs, a self-only CSP, Permissions Policy,
  anti-framing/nosniff/referrer/COOP headers, secure cookie/HSTS configuration,
  upload/request bounds and redacted structured logs.
- Apache serves collected static files but no broad media alias. Django exposes
  only exact public tenant-brand images; bounded operational media requires a
  superuser and private/no-store responses.
- Contact, enrollment and Dotykačka-connect endpoints use database-backed
  per-window limits with HMAC-hashed client identities. A timestamped HMAC
  verifier is available for future webhook endpoints; no route is described as
  a webhook until a provider-specific endpoint is actually enabled.
- Forwarded client addresses are ignored by default. They affect rate-limit
  identity only when the immediate peer belongs to an explicitly configured
  trusted-proxy network; HTTPS proxy-header trust is also opt-in.
- `/health/live` and `/health/ready` expose only generic state. The superuser
  operations page adds database/storage/provider detail, three worker
  heartbeats and auditable alert acknowledgement/resolution.
- The monitor detects failed integration/print work, failed print requests, low
  inventory/pack balance, nearing entitlements, repeated provider-auth failures
  and stale workers. It never retries a business operation or edits its domain
  status directly.
- CI treats deployment warnings, migration drift, architecture violations,
  tests, stale compiled assets and dependency advisories as failures.
- Backup/monitor systemd definitions and operator, tenant, billing,
  fulfillment, restore and Marta-acceptance runbooks are included.

## Data-safety evidence

The pre-migration backup was created before `operations.0001_initial` and kept
with mode `0600`:

| Artifact | SHA-256 | Size |
| --- | --- | ---: |
| `pre-phase11-20260718-032454.sql.gz` | `14ca728c28631613e29b383416ce507e9eb942d793910e488a7ee5bcf8c04d90` | 329,032 bytes |
| `pre-phase11-runtime-20260718-032454.tar.gz` | `b57d9eefeef2658732572a418017e9a04c4e88ee8698efbf054f462d7760e986` | 558,897,291 bytes |

`gzip -t`, `tar -tzf` and checksum verification passed. The reviewed MariaDB
migration SQL only created the four `operations_*` tables, their indexes,
constraints and foreign keys. It did not alter or drop an existing table.

The backup was restored into the explicitly authorized disposable database
`test_django` and a new temporary runtime directory. On that restored copy:

1. `check` passed;
2. the plan showed only `operations.0001_initial` pending;
3. the additive migration applied and the plan became empty;
4. strict extraction and Marta rollout verification passed;
5. restored media and print storage passed write/read probes;
6. the disposable database and exact temporary restore directory were removed
   after evidence was captured.

A post-deployment command-generated backup also passed manifest, SHA-256,
gzip/tar and `0600` permission verification:

| Artifact | SHA-256 | Size |
| --- | --- | ---: |
| `phase11-postdeploy-20260718-015810-432831.sql.gz` | `8c1ddbc38332e8c006ec3767a81f0447f05b91633a60d89ed388b231c67534fa` | 330,771 bytes |
| `phase11-postdeploy-20260718-015810-432831-runtime.tar.gz` | `3d476cc779f5154736c23abb126f1ac18c46bee9ccaae5f3f136da0f32d0cdc8` | 558,364,331 bytes / 3,626 members |

The smoke run initially exposed that passing a `gzip.GzipFile` directly as a
subprocess stdout target bypassed compression through its raw file descriptor.
The command now streams MariaDB stdout through Python's gzip writer, builds all
artifacts as mode-`0600` partial files, verifies them and publishes the complete
set without overwriting an existing name. A regression test covers the MariaDB
stream. The two invalid smoke artifacts were permanently removed and are not
accepted as backups.

## Automated release results

| Gate | Result |
| --- | --- |
| `manage.py check` | passed |
| `check --deploy --fail-level WARNING` with production security settings | passed |
| `makemigrations --check --dry-run` | no changes |
| `migrate --plan` after deployment | no operations |
| strict extraction verifier | 57 models, 57 content types, 228 permissions, 395 URL patterns, 46 commands, 52 admin registrations; passed |
| Fresh SQLite suite | 219 passed, 3 expected database-specific skips |
| Fresh MariaDB `test_django` suite | 219 passed, no skips |
| Python production dependency audit | no known vulnerabilities |
| Node dependency audit | 0 vulnerabilities |
| Tailwind/vendor build | passed; committed assets rebuilt |
| Apache configuration | syntax OK |
| Compose health | database, web, integration worker, print worker and monitor healthy |
| Live `/health/live` and `/health/ready` | HTTP 200 with redacted body and security headers |

Dependencies were upgraded within the existing stack to Django 5.2.16,
PyJWT 2.13.0, cryptography 49.0.0, Pillow 12.3.0 and Requests 2.34.2. Unused
legacy `applepassgenerator`, `M2Crypto` and `wallet` packages were removed from
the deployment lock because the active Apple implementation already signs via
the project service and OpenSSL. Apache runs this site's isolated daemon group
in its main Python interpreter so cryptography's PyO3 extension is compatible
with mod_wsgi.

## Marta invariant and rollout state

The read-only rollout command reported:

- 267 customers;
- 600 cards: 267 assigned and 333 available;
- 263 historical access tokens;
- one tenant membership, three tenant integrations and 267 Wallet identities;
- zero enrollments, print requests and marketing leads.

No commercial plan or price was invented. The operations monitor added only
operational heartbeat/alert history; its startup stale-worker alert resolved
automatically when all workers became healthy.

One active Marta connection still carries the previously stored redacted status
`brevo_unauthorized`. Phase 11 did not make an unsolicited provider call or
clear that evidence. The operator must run the explicit Brevo system test and,
if it still fails, replace the tenant-owned database key before acceptance.

The remaining gate is intentionally human. Marta must complete and sign
`docs/runbooks/marta-acceptance.md` before another paying tenant is enabled.
