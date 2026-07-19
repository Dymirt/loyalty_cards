# Backup and restore runbook

## Scheduled backup

`deploy/systemd/loyalty-backup.timer` runs the existing Django/Python stack
nightly. Configure `BACKUP_ROOT` to a restricted path outside static and media,
then enable the timer:

```bash
sudo systemctl enable --now loyalty-backup.timer
sudo systemctl list-timers loyalty-backup.timer
```

The command creates a transaction-consistent database dump, runtime/media tar
archive and JSON manifest. It verifies gzip/tar readability and records
SHA-256 and byte size before returning success:

```bash
python manage.py create_platform_backup --label scheduled
python manage.py verify_platform_backup /protected/path/scheduled-TIMESTAMP.manifest.json
```

The timer reports archives older than 35 days but deliberately does not delete
them. Retention and off-host movement require operator review. Copy at least one
verified generation to encrypted storage outside the application host.

## Disposable restore drill

1. Stop using the chosen disposable database and confirm its exact name. Never
   target the production database or broad filesystem paths.
2. Create an empty MariaDB database with the same charset/collation and a
   least-privileged test user.
3. Decompress the SQL backup into that database.
4. Extract the runtime archive into a new temporary directory, never over the
   active `MEDIA_ROOT` or print-package root.
5. Point a one-off Django process at the restored database and temporary runtime
   roots. Run `check`, `migrate --plan`, `verify_app_extraction --strict`, and
   `verify_saas_rollout --expect-marta` when the backup is the Marta replica.
6. Record counts, checksums, command output and elapsed time in the release
   evidence.
7. Destroy only the explicitly named disposable database and temporary runtime
   directory after the evidence is retained.

Restoring a backup over live data is an incident operation that can lose newer
registrations and fulfillment events. It requires explicit approval and is not
a normal application rollback.
