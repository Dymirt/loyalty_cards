# Platform operator runbook

## Start of shift

1. Open `/dotykacka/platform/operations` as a platform superuser.
2. Confirm database, media, print storage, integration worker, print worker and
   operations monitor are green.
3. Review open critical alerts before warnings. Do not place secrets, customer
   data or provider responses in the alert note.
4. Open `/dotykacka/platform/system-connections` only when a redacted provider
   configuration or authentication check is needed. These tests must never be
   shown to tenant users.
5. Review the centralized print queue and failed enrollment follow-ups.

## Alert response

- Acknowledge an alert with a short safe description of the investigation.
- Use the owning screen to retry a provider job or print job. Never change a job
  status directly in SQL.
- Resolve the alert only after the source record is healthy or an approved
  compensating action exists. Resolution appends an event and retains history.
- Provider-authentication alerts require reconnecting the affected tenant or
  rotating a platform secret through the documented credential owner. Never
  paste a token into an alert, ticket or log.
- A stale-worker alert requires checking the supervisor/container and recent
  redacted logs. Restart only the affected process; do not rerun migrations from
  the worker.

## Deployment gate

1. Create and verify database/runtime backups.
2. Run `check`, `check --deploy`, migration drift/plan, the strict extraction
   verifier, the full test suite and the Tailwind build.
3. Apply migrations from the web deployment exactly once. Workers start only
   after the web liveness health check succeeds.
4. Run `python manage.py verify_saas_rollout --expect-marta` on the protected
   first-tenant replica.
5. Inspect `/health/ready` and the operations console. Public health output is
   deliberately redacted; operator detail is superuser-only.

## Marketing-lead retention

Run `python manage.py report_marketing_retention`. It reports only a cutoff and
count and performs no mutation. Any deletion or anonymization requires a
separately approved legal retention decision, a backup, an auditable migration
or command, and verification that required consent evidence remains available.

