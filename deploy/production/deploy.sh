#!/bin/bash
set -Eeuo pipefail

umask 027

APP_ROOT=/var/www/loyalty_platform
RELEASES=$APP_ROOT/releases
SHARED=$APP_ROOT/shared
CURRENT=$APP_ROOT/current
STATE=/var/lib/loyalty-deploy
BACKUPS=/var/backups/loyalty-platform
DEPLOY_USER=loyalty-deploy
WORKER_UNITS=(
    loyalty-integration-worker.service
    loyalty-print-worker.service
    loyalty-monitor.service
)

log() {
    printf '[loyalty-deploy] %s\n' "$*"
}

fail() {
    log "ERROR: $*" >&2
    exit 1
}

if [[ $EUID -ne 0 ]]; then
    fail "deployment must run through sudo"
fi
if [[ $# -ne 2 ]]; then
    fail "usage: loyalty-deploy COMMIT_SHA ARCHIVE"
fi

SHA=$1
ARCHIVE=$(realpath "$2")
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || fail "commit SHA is invalid"
[[ "$ARCHIVE" == "/home/$DEPLOY_USER/incoming/$SHA.tar.gz" ]] || fail "archive path is invalid"
[[ -f "$ARCHIVE" ]] || fail "release archive is missing"
[[ $(stat -c %U "$ARCHIVE") == "$DEPLOY_USER" ]] || fail "release archive owner is invalid"

exec 9>/run/lock/loyalty-deploy.lock
flock -n 9 || fail "another production deployment is already running"

RELEASE=$RELEASES/$SHA
PARTIAL=$RELEASES/.$SHA.partial
[[ ! -e "$RELEASE" ]] || fail "release already exists: $SHA"
[[ -r "$SHARED/.env" ]] || fail "protected production environment is not provisioned"

available_bytes=$(df --output=avail -B1 "$APP_ROOT" | tail -1 | tr -d ' ')
[[ "$available_bytes" =~ ^[0-9]+$ ]] || fail "could not determine free disk space"
(( available_bytes >= 800000000 )) || fail "less than 800 MB is free; deployment stopped before extraction"

archive_listing=$(mktemp)
workers_stopped=false
switched=false
workers_to_restart=()
cleanup() {
    status=$?
    rm -f "$archive_listing"
    if (( status != 0 )) && [[ "$switched" == true ]]; then
        rollback_code 2>/dev/null || true
    fi
    if (( status != 0 )) && [[ -n "${PARTIAL:-}" && -d "$PARTIAL" ]]; then
        rm -rf -- "$PARTIAL"
    fi
    if (( status != 0 )) && [[ "$workers_stopped" == true && "$switched" == false ]]; then
        if (( ${#workers_to_restart[@]} )); then
            systemctl restart "${workers_to_restart[@]}" 2>/dev/null || true
        fi
    fi
}
trap cleanup EXIT
tar -tzf "$ARCHIVE" > "$archive_listing"
while IFS= read -r member; do
    case "$member" in
        /*|../*|*/../*|*/..)
            fail "archive contains an unsafe path"
            ;;
    esac
done < "$archive_listing"

if [[ -e "$PARTIAL" ]]; then
    rm -rf -- "$PARTIAL"
fi
install -d -m 0750 -o "$DEPLOY_USER" -g www-data "$PARTIAL"
tar -xzf "$ARCHIVE" --no-same-owner --no-same-permissions -C "$PARTIAL"
chown -R "$DEPLOY_USER:www-data" "$PARTIAL"
chmod -R u=rwX,g=rX,o= "$PARTIAL"
ln -s "$SHARED/.env" "$PARTIAL/.env"
install -d -m 0770 -o www-data -g www-data "$PARTIAL/staticfiles"

log "creating the Python 3.11 environment for $SHA"
runuser -u "$DEPLOY_USER" -- python3 -m venv "$PARTIAL/.venv"
runuser -u "$DEPLOY_USER" -- "$PARTIAL/.venv/bin/python" -m pip install \
    --disable-pip-version-check --no-input --upgrade pip setuptools wheel
runuser -u "$DEPLOY_USER" -- "$PARTIAL/.venv/bin/python" -m pip install \
    --disable-pip-version-check --no-input -r "$PARTIAL/requirements-production.txt"
runuser -u "$DEPLOY_USER" -- "$PARTIAL/.venv/bin/python" -m pip check
chgrp -R www-data "$PARTIAL/.venv"
chmod -R g+rX,o= "$PARTIAL/.venv"

run_manage() {
    (
        cd "$PARTIAL"
        runuser -u www-data -- "$PARTIAL/.venv/bin/python" manage.py "$@"
    )
}

log "running read-only Django and migration preflight checks"
run_manage check
run_manage check --deploy --fail-level WARNING
run_manage makemigrations --check --dry-run
run_manage migrate --plan

preflight_json=$(run_manage preflight_legacy_inventory --json)
printf '%s\n' "$preflight_json" > "$STATE/preflight-$SHA.json"
chmod 0600 "$STATE/preflight-$SHA.json"

had_current=false
previous_release=
if [[ -L "$CURRENT" ]]; then
    had_current=true
    previous_release=$(readlink -f "$CURRENT")
fi

log "stopping background workers for the migration window"
for unit in "${WORKER_UNITS[@]}"; do
    if systemctl is-active --quiet "$unit" 2>/dev/null; then
        workers_to_restart+=("$unit")
    fi
done
systemctl stop "${WORKER_UNITS[@]}" 2>/dev/null || true
workers_stopped=true

if [[ ! -f "$STATE/first-platform-backup-complete" ]]; then
    log "creating and verifying the first full database/runtime backup"
    backup_json=$(run_manage create_platform_backup --label pre-cicd-first)
    printf '%s\n' "$backup_json"
    backup_manifest=$(
        printf '%s\n' "$backup_json" | python3 -c \
            'import json,sys; print(json.load(sys.stdin)["manifest"])'
    )
    run_manage verify_platform_backup "$backup_manifest"
    touch "$STATE/first-platform-backup-complete"
    chmod 0600 "$STATE/first-platform-backup-complete"
else
    log "creating a transaction-consistent database backup"
    set -a
    # Protected bootstrap output uses shell-safe quoted values.
    # shellcheck disable=SC1091
    source "$SHARED/.env"
    set +a
    : "${DB_NAME:?missing DB_NAME}"
    : "${DB_USER:?missing DB_USER}"
    : "${DB_PASSWORD:?missing DB_PASSWORD}"
    stamp=$(date -u +%Y%m%d-%H%M%S)
    database_backup="$BACKUPS/pre-deploy-$stamp-$SHA.sql.gz"
    MYSQL_PWD=$DB_PASSWORD mariadb-dump \
        --single-transaction --routines --triggers --events \
        --default-character-set=utf8mb4 \
        --host "${DB_HOST:-localhost}" --port "${DB_PORT:-3306}" \
        --user "$DB_USER" "$DB_NAME" | gzip -9 > "$database_backup.partial"
    gzip -t "$database_backup.partial"
    mv "$database_backup.partial" "$database_backup"
    chmod 0600 "$database_backup"
    sha256sum "$database_backup" > "$database_backup.sha256"
    chmod 0600 "$database_backup.sha256"
fi

log "applying forward migrations exactly once"
run_manage migrate --noinput
run_manage migrate --plan
run_manage verify_app_extraction --strict

read -r expected_customers expected_tokens expected_users expected_assigned expected_available < <(
    python3 - "$STATE/preflight-$SHA.json" <<'PY'
import json
import sys

result = json.load(open(sys.argv[1], encoding="utf-8"))
print(
    result["customer_count"],
    result["token_count"],
    result["user_count"],
    result["assigned_card_count"],
    result["available_card_count"],
)
PY
)
run_manage verify_marta_backfill \
    --expect-memberships "$expected_users" \
    --expect-customers "$expected_customers" \
    --expect-tokens "$expected_tokens" \
    --expect-cards 600 \
    --expect-assigned "$expected_assigned" \
    --expect-available "$expected_available"
run_manage shell -c '
from dotykacka.models import IntegrationConnection
required = {
    IntegrationConnection.Provider.DOTYKACKA: "refresh_token",
    IntegrationConnection.Provider.BREVO: "api_key",
}
for provider, secret_name in required.items():
    connection = IntegrationConnection.objects.get(provider=provider)
    if not connection.has_secret(secret_name):
        raise RuntimeError(f"required migrated credential is missing: {provider}")
print("migrated tenant credentials=ok")
'
run_manage verify_saas_rollout
run_manage collectstatic --noinput --verbosity 0
run_manage check

mv "$PARTIAL" "$RELEASE"
PARTIAL=

apache_backup=$STATE/apache-before-$SHA.conf
cp -a /etc/apache2/sites-available/django.conf "$apache_backup"
chmod 0600 "$apache_backup"

rollback_code() {
    log "health verification failed; restoring the previous code and Apache configuration"
    systemctl stop "${WORKER_UNITS[@]}" 2>/dev/null || true
    if [[ "$had_current" == true && -n "$previous_release" ]]; then
        rollback_link=$APP_ROOT/.current-rollback
        ln -sfn "$previous_release" "$rollback_link"
        mv -Tf "$rollback_link" "$CURRENT"
    else
        [[ ! -L "$CURRENT" ]] || unlink "$CURRENT"
    fi
    install -m 0644 -o root -g root "$apache_backup" /etc/apache2/sites-available/django.conf
    apache2ctl configtest
    systemctl restart apache2
    if [[ "$had_current" == true ]]; then
        systemctl restart "${WORKER_UNITS[@]}" 2>/dev/null || true
    else
        systemctl disable "${WORKER_UNITS[@]}" 2>/dev/null || true
    fi
    switched=false
    workers_stopped=false
}

new_link=$APP_ROOT/.current-$SHA
ln -sfn "$RELEASE" "$new_link"
mv -Tf "$new_link" "$CURRENT"
switched=true

install -m 0644 -o root -g root "$RELEASE/deploy/production/apache.conf" \
    /etc/apache2/sites-available/django.conf
a2enmod headers >/dev/null
for unit in "${WORKER_UNITS[@]}"; do
    install -m 0644 -o root -g root "$RELEASE/deploy/production/$unit" "/etc/systemd/system/$unit"
done

workers_stopped=false
systemctl daemon-reload

if ! apache2ctl configtest; then
    rollback_code
    fail "Apache rejected the new release configuration"
fi
if ! systemctl restart apache2; then
    rollback_code
    fail "Apache could not start the new release"
fi
if ! systemctl enable --now "${WORKER_UNITS[@]}"; then
    rollback_code
    fail "one or more background workers could not start"
fi

wait_for_health() {
    local endpoint=$1
    local attempts=$2
    local delay=$3
    local attempt
    for ((attempt = 1; attempt <= attempts; attempt++)); do
        if curl --fail --silent --show-error --max-time 5 \
            -H 'Host: club.mbstudio.online' \
            -H 'X-Forwarded-Proto: https' \
            "http://127.0.0.1$endpoint" >/dev/null; then
            return 0
        fi
        sleep "$delay"
    done
    return 1
}

if ! wait_for_health /health/live 15 4; then
    rollback_code
    fail "production liveness did not recover"
fi
if ! wait_for_health /health/ready 30 5; then
    rollback_code
    fail "production readiness did not recover"
fi

for unit in "${WORKER_UNITS[@]}"; do
    systemctl is-active --quiet "$unit" || {
        rollback_code
        fail "$unit is not active"
    }
done

printf '%s\n' "$SHA" > "$STATE/current-sha"
if [[ -n "$previous_release" ]]; then
    basename "$previous_release" > "$STATE/previous-sha"
fi
chmod 0600 "$STATE/current-sha" "$STATE/previous-sha" 2>/dev/null || true

for old_release in "$RELEASES"/[0-9a-f]*; do
    [[ -d "$old_release" ]] || continue
    [[ $(basename "$old_release") =~ ^[0-9a-f]{40}$ ]] || continue
    if [[ "$old_release" != "$RELEASE" && "$old_release" != "$previous_release" ]]; then
        rm -rf -- "$old_release"
    fi
done
rm -f -- "$ARCHIVE"

log "deployment succeeded: $SHA"
