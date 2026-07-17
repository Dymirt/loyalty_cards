# Phase 4 project rename and extraction safety rails

Completed: 2026-07-17

Phase 4 changes Python/Django ownership boundaries only. It does not move a
model, rename a table, alter a row, regenerate an asset, or add a migration.

## Active project package

The active Django configuration package is now `loyalty_platform`:

- `DJANGO_SETTINGS_MODULE=loyalty_platform.settings`;
- `ROOT_URLCONF=loyalty_platform.urls`;
- `WSGI_APPLICATION=loyalty_platform.wsgi.application`;
- `ASGI_APPLICATION=loyalty_platform.asgi.application`;
- `TEST_RUNNER=loyalty_platform.test_runner.NoExternalCallsDiscoverRunner`.

The old project package remains as a bounded import compatibility shim. It
re-exports the active settings, URL patterns, ASGI/WSGI applications and test
runner; it no longer owns configuration. The Docker/Apache application root is
`/var/www/loyalty_platform`.

`LOYALTY_ALLOWED_HOSTS_FILE` is the active configuration name.
`TURNKEY_ALLOWED_HOSTS_FILE` is read only when the new setting is empty and is
scheduled for removal after one verified deployment release.

The old `/turnkey/` URL no longer renders the demonstration page. It redirects
to the namespaced `marketing` app bridge, which currently redirects to the
existing public landing page. This preserves bookmarks while transferring URL
ownership without introducing the Phase 10 marketing site early.

## Destination apps

The following Django apps are installed and intentionally model-free:

```text
core                 tenants              customers
cards                card_artwork         integrations
pos                  pos_dotykacka        communications
brevo                wallets              wallet_apple
wallet_google        billing              printing
enrollment           marketing
```

Each app has an explicit `AppConfig`, namespaced URL module, test package and
empty migration package. Any future model must be added to its final owner by
an additive migration. Existing models remain owned by the `dotykacka` app and
keep their historical migration graph and table names.

`core.architecture` declares allowed dependency directions. The architecture
test parses imports in new app production modules and rejects reverse or
provider-specific dependencies. The legacy `dotykacka` app is deliberately
exempt while behavior is moved one bounded context at a time.

## Frozen extraction contract

`core.extraction_inventory` records and checks the following non-sensitive
contract:

- all 13 `dotykacka` model labels and exact database table names;
- all 13 matching content types and 52 standard model permissions;
- migrations `0001` through `0013` with their exact historical names;
- the 12 existing `dotykacka` Django admin registrations and the global
  `delete_selected` action;
- all legacy named application URLs and management commands;
- active project settings and all installed destination apps;
- aggregate row counts only, never record values, credentials or PII.

The complete runtime report also inventories Django/contrib models, tables,
permissions, URL patterns, commands, migrations and admin classes. It is JSON
serializable for release comparison.

Run the read-only structural check anywhere after migrations:

```bash
python manage.py verify_app_extraction --strict
```

On the protected Marta replica, also check the stable first-tenant aggregates:

```bash
python manage.py verify_app_extraction --strict --expect-marta
```

The Marta mode expects 267 customers, 600 physical cards, one tenant, one
membership, one legacy batch, one design/brand revision, three connections and
267 Wallet identities. It requires at least the 261 migration-time token rows
because the token cache is append-only and can grow during normal operation.

For a machine-readable report:

```bash
python manage.py verify_app_extraction --json
```

The command uses database introspection and aggregate `COUNT` queries only. It
does not save models, run migrations, call providers, generate files, or send
messages.

## Verification results

The completed Phase 4 verification produced:

| Check | Result |
| --- | --- |
| Django system check | No issues |
| Migration consistency | No model changes detected |
| Migration plan on Marta replica | No planned operations |
| Extraction verifier on Marta replica | Passed |
| Runtime inventory | 19 models, 19 content types, 76 permissions, 114 URL patterns, 37 commands, 14 admin registrations, 2 aggregate admin-log reference groups |
| Legacy database/media preflight | 267 customers, 263 append-only tokens, 600 cards, 0 duplicate/invalid/out-of-range codes, 0 missing assets |
| Design/Wallet backfill | 1 design, 1 brand revision, 1 linked batch, 267 Wallet identities, 0 tenant mismatches |
| Fresh-database regression suite | 89 tests passed |
| Rebuilt Docker/Apache deployment | Healthy at `/var/www/loyalty_platform` |
| HTTP checks | `/` = 200, `/turnkey/` → `/marketing/` → `/` |

The web container was rebuilt without recreating the MariaDB service or volume.
Startup reported no migrations to apply.

## Release and rollback

Before deployment, take the normal database/media backups even though this
phase has no schema or data operation. Deploy application/configuration files,
set `LOYALTY_ALLOWED_HOSTS_FILE` if the path is overridden, then run:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py verify_app_extraction --strict --expect-marta
python manage.py test
```

Rollback is application-only: restore the prior code/container configuration.
There is no Phase 4 schema or data migration to reverse. Do not reverse the
existing tenant/design migrations and do not remove the database/media volume.
