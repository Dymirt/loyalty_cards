# Production CI/CD runbook

## Release policy

Production deployment is code-only and forward-only. A successful push to
`main` starts `Loyalty platform CI`. Deployment starts only after that exact
push passes both the SQLite/build/audit job and the MariaDB 10.11 integration
job. Pull-request workflows and fork branches cannot access deployment secrets
or start a release.

The production job packages `git archive` output for the tested commit. Git
metadata, `.env`, customer media, Wallet keys, database files, logs, local
backups and every ignored file are therefore absent from the artifact.

## Server layout

```text
/var/www/turnkey_project/              preserved legacy tree and live media
/var/www/loyalty_platform/
├── current -> releases/<commit-sha>/  active code and release virtualenv
├── releases/<commit-sha>/             versioned source/static/venv
└── shared/
    ├── .env                           root:www-data 0640; never uploaded by CI
    ├── secrets/                       protected Google Wallet credentials
    ├── mypass_template/               protected Apple Wallet signing files
    └── print-packages/                protected generated print packages
/var/backups/loyalty-platform/         verified pre-release backups
/var/lib/loyalty-deploy/               release state and aggregate preflight
```

The existing MariaDB database and `/var/www/turnkey_project/media` remain in
place. The legacy source tree is not deleted and is available for the first
code rollback. Apache no longer exposes a broad `/media/` alias after the
platform cutover; protected media is served through authorized Django views.
Cloudflare Tunnel terminates public TLS and forwards the original scheme in
`X-Forwarded-Proto`; Django trusts that header and still enforces HTTPS. Internal
release checks use HTTP plus `X-Forwarded-Proto: https` to exercise the same
origin path and detect redirect-loop configuration errors.

## One-time bootstrap

Run bootstrap before enabling the GitHub deployment variable. It prepares a
dedicated `loyalty-deploy` SSH account, a narrowly scoped passwordless sudo
command, protected shared files, release directories and the operator rollback
command. It does not change Apache or restart the live legacy application.

From an operator machine, create a dedicated key that is used only by GitHub
Actions:

```bash
ssh-keygen -t ed25519 -a 100 -N '' \
  -C 'github-actions loyalty production' \
  -f /tmp/loyalty-github-actions
```

Copy the tracked bootstrap directory and the public key to the server, then run
as root with the protected environment export made from the legacy settings:

```bash
rsync -a deploy/production/ loyalty-app:/tmp/loyalty-production-bootstrap/
scp /tmp/loyalty-github-actions.pub loyalty-app:/tmp/loyalty-github-actions.pub
ssh loyalty-app \
  '/tmp/loyalty-production-bootstrap/bootstrap.sh /tmp/loyalty-local.env /tmp/loyalty-github-actions.pub'
```

The bootstrap converts the legacy export to production paths and HTTPS options,
preserves all existing provider/SMTP/database keys, and creates one new Fernet
key for encrypted per-tenant credentials. Secret values are never printed.

## GitHub production configuration

Create a GitHub environment named `production`, then configure these repository
values:

| Type | Name | Value |
| --- | --- | --- |
| Variable | `PRODUCTION_DEPLOY_ENABLED` | `true` only after bootstrap and review |
| Variable | `PRODUCTION_DEPLOY_HOST` | `ssh.loyalty.mbstudio.online` |
| Variable | `PRODUCTION_DEPLOY_PORT` | `9022` |
| Variable | `PRODUCTION_DEPLOY_USER` | `loyalty-deploy` |
| Secret | `PRODUCTION_DEPLOY_SSH_KEY` | contents of the dedicated private key |
| Secret | `PRODUCTION_KNOWN_HOSTS` | pinned `ssh-keyscan -p 9022` output |

Do not place Django, database, SMTP, Dotykačka, Brevo, Google Wallet or Apple
Wallet secrets in GitHub. Delete the temporary private key from the operator
machine after GitHub stores it, and retain only the public key where needed for
audit.

## What happens during deployment

1. The server validates the 40-character commit SHA, archive owner/path,
   archive traversal safety, deployment lock and at least 800 MB free space.
2. It creates a release-specific Python 3.11 virtualenv and installs the pinned
   production dependencies as the unprivileged deployment user.
3. Django checks, strict architecture verification, migration drift/plan and a
   read-only legacy inventory preflight run before any data mutation.
4. Workers stop. The first platform deployment creates and verifies a full
   database/runtime backup; later deployments create transaction-consistent,
   checksummed database backups without duplicating live media.
5. Forward migrations run exactly once. Customer, token, user, card and asset
   aggregates captured before migration must match after migration, and migrated
   Dotykačka/Brevo credentials must be decryptable without being displayed.
6. Static assets are collected, the `current` symlink switches atomically,
   Apache restarts and the integration, print and monitor workers start under
   systemd.
7. Internal liveness/readiness and external public health checks must pass.

Only the active and immediately previous versioned releases are retained. The
legacy tree, database, customer media, Wallet files and backups are never
deleted by the deployment cleanup.

## Failure and rollback

Any Apache, worker, liveness or readiness failure after the code switch restores
the previous code pointer and Apache configuration automatically. Database
migrations are not reversed; migrations must remain additive and compatible
with the previous release.

For an operator-approved manual code rollback:

```bash
ssh loyalty-app sudo /usr/local/sbin/loyalty-rollback
```

The command switches to the recorded previous release, reloads Apache/workers,
checks liveness, and restores the original release if rollback health fails. A
database restore is an incident operation, not a normal release rollback.

## Operational checks

```bash
ssh loyalty-app 'cat /var/lib/loyalty-deploy/current-sha'
ssh loyalty-app 'systemctl --no-pager --full status apache2 loyalty-integration-worker loyalty-print-worker loyalty-monitor'
curl --fail https://club.mbstudio.online/health/live
curl --fail https://club.mbstudio.online/health/ready
```

Move verified backups to encrypted off-host storage and monitor free space. The
deployment deliberately fails before extraction when capacity is low and never
deletes backup generations automatically.
