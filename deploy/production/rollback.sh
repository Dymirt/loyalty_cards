#!/bin/bash
set -Eeuo pipefail

umask 027

APP_ROOT=/var/www/loyalty_platform
CURRENT=$APP_ROOT/current
STATE=/var/lib/loyalty-deploy
WORKER_UNITS=(
    loyalty-integration-worker.service
    loyalty-print-worker.service
    loyalty-monitor.service
)

fail() {
    printf '[loyalty-rollback] ERROR: %s\n' "$*" >&2
    exit 1
}

[[ $EUID -eq 0 ]] || fail "rollback must run as root"
[[ -L "$CURRENT" ]] || fail "there is no active platform release"
[[ -f "$STATE/previous-sha" ]] || fail "there is no recorded previous release"

previous_sha=$(tr -d '\r\n' < "$STATE/previous-sha")
[[ "$previous_sha" =~ ^[0-9a-f]{40}$ ]] || fail "the recorded previous SHA is invalid"
previous_release=$APP_ROOT/releases/$previous_sha
[[ -d "$previous_release" ]] || fail "the previous release directory is missing"

current_release=$(readlink -f "$CURRENT")
current_sha=$(basename "$current_release")
[[ "$current_sha" =~ ^[0-9a-f]{40}$ ]] || fail "the active release SHA is invalid"

exec 9>/run/lock/loyalty-deploy.lock
flock -n 9 || fail "a deployment or rollback is already running"

restore_release() {
    local release=$1
    local link=$APP_ROOT/.current-rollback
    ln -sfn "$release" "$link"
    mv -Tf "$link" "$CURRENT"
    install -m 0644 -o root -g root "$release/deploy/production/apache.conf" \
        /etc/apache2/sites-available/django.conf
    for unit in "${WORKER_UNITS[@]}"; do
        install -m 0644 -o root -g root "$release/deploy/production/$unit" \
            "/etc/systemd/system/$unit"
    done
    systemctl daemon-reload
    apache2ctl configtest
    systemctl restart apache2
    systemctl restart "${WORKER_UNITS[@]}"
}

systemctl stop "${WORKER_UNITS[@]}" 2>/dev/null || true
if ! restore_release "$previous_release"; then
    restore_release "$current_release" || true
    fail "the previous release could not be started; the original code was restored"
fi

healthy=false
for _ in {1..15}; do
    if curl --fail --silent --show-error --max-time 5 \
        -H 'Host: club.mbstudio.online' \
        -H 'X-Forwarded-Proto: https' \
        http://127.0.0.1/health/live >/dev/null; then
        healthy=true
        break
    fi
    sleep 4
done
if [[ "$healthy" != true ]]; then
    restore_release "$current_release" || true
    fail "the previous release failed its liveness check; the original code was restored"
fi

printf '%s\n' "$previous_sha" > "$STATE/current-sha"
printf '%s\n' "$current_sha" > "$STATE/previous-sha"
chmod 0600 "$STATE/current-sha" "$STATE/previous-sha"
printf '[loyalty-rollback] active release is now %s; database migrations were not reversed\n' \
    "$previous_sha"
