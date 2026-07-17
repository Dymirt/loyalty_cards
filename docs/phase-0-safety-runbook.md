# Phase 0 Safety and Verification Runbook

This runbook covers the stabilization release only. It does not create tenants, import inventory rows, or change existing card/media files.

## Hard safety rules

- Never run `flush`, destructive SQL, database reset commands, or remove the MariaDB Docker volume.
- Never import a dump over the current database.
- Never run a migration before a verified database backup and a separate media backup exist.
- Never test registration with live customer details.
- Never run migrations or tests with production external effects enabled.
- Treat `.env`, POS tokens, Wallet keys/certificates, SMTP credentials, and Brevo credentials as secrets.
- Phase 0 migration `0008` adds a uniqueness constraint only. It does not update or delete a row.

## Safe test mode

The Django test runner automatically:

- uses Django’s in-memory email backend;
- blocks Requests HTTP calls;
- blocks urllib3 pool calls used by SDKs;
- blocks SMTP and SMTP-over-SSL calls.

Integration tests must mock the relevant service boundary. Test data uses reserved `example.test` addresses and synthetic names/numbers.

Run checks without using the existing MariaDB data:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/loyalty-phase0.sqlite3 \
  python manage.py test --noinput
```

The local MariaDB application account may not have permission to create Django’s `test_django` database. The SQLite command above is the supported isolated fallback and does not read or modify the MariaDB replica.

## Read-only legacy preflight

The preflight command performs aggregate database reads and file-existence checks only. It never calls an external service and never writes to the database or media.

For the verified Marta replica:

```bash
python manage.py preflight_legacy_inventory \
  --prefix MB \
  --start 1 \
  --end 600 \
  --expect-users 1 \
  --expect-customers 267 \
  --expect-tokens 261 \
  --json
```

Expected aggregates before Phase 1 are:

- 1 user;
- 267 loyalty customers;
- 261 cached legacy POS tokens;
- 600 complete card asset sets;
- 267 assigned card numbers;
- 333 available card numbers;
- zero duplicate, malformed, or out-of-range codes;
- zero missing assets.

Do not continue if the command reports `status=error`. Investigate the mismatch read-only; do not “fix” data directly.

## Backup and restore gate

Before applying `0008` or any later migration:

1. Create a timestamped, encrypted, transactionally consistent MariaDB backup using the deployment’s approved backup mechanism.
2. Create a separate immutable archive of `media/` and Wallet template/signing material, preserving permissions.
3. Record backup sizes and cryptographic checksums outside the application host.
4. Restore the database and media into a disposable staging environment.
5. Run the preflight command against the restored environment.
6. Run the full test suite and `manage.py check` there.
7. Retain the restore-test result with the deployment record.

A backup is not considered verified until the disposable restore starts successfully and produces the expected aggregate preflight result.

## Migration 0008 deployment gate

Migration `dotykacka.0008_alter_klient_klient_id_unique` closes the concurrent duplicate-registration race by adding a unique database constraint to `Klient.klient_id`.

Before applying it:

1. Run the read-only preflight and confirm zero duplicate card codes.
2. Verify the database and media backups.
3. Inspect `python manage.py migrate --plan`.
4. Apply the migration in restored staging first.
5. Run the tests and preflight again.
6. Schedule the production migration in a controlled deployment window because MariaDB may lock the table while creating the unique index.
7. Apply with `python manage.py migrate dotykacka 0008`.
8. Re-run `manage.py check`, `showmigrations`, and the aggregate preflight.

No Phase 0 command applies this migration automatically.

## Rollback policy

Do not reverse `0008` in production as a routine code rollback. The previous application code remains compatible with the unique constraint, so rollback consists of deploying the previous compatible code while leaving the additive constraint in place.

Restore a database backup only for a verified database incident, with an approved incident plan. A restore replaces current state and can lose new registrations, so it is not a normal deployment rollback.

## Remaining temporary risk

Registration follow-up work still starts from a daemon thread to preserve current response time. Phase 0 makes its steps explicit and redacts failure logs, but a process restart can still interrupt the work. The planned database-backed durable job worker must replace this launcher before the SaaS rollout. Do not mistake Phase 0 stabilization for durable delivery.
