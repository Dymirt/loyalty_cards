#!/bin/bash
set -Eeuo pipefail

umask 027

if [[ $EUID -ne 0 ]]; then
    echo "bootstrap must run as root" >&2
    exit 1
fi
if [[ $# -ne 2 ]]; then
    echo "usage: bootstrap.sh LEGACY_ENV_EXPORT DEPLOY_PUBLIC_KEY" >&2
    exit 1
fi

LEGACY_ENV_EXPORT=$(realpath "$1")
DEPLOY_PUBLIC_KEY=$(realpath "$2")
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
APP_ROOT=/var/www/loyalty_platform
SHARED="$APP_ROOT/shared"
DEPLOY_USER=loyalty-deploy
DEPLOY_HOME=/home/$DEPLOY_USER

for required in "$LEGACY_ENV_EXPORT" "$DEPLOY_PUBLIC_KEY"; do
    [[ -f "$required" ]] || { echo "missing required file: $required" >&2; exit 1; }
done

if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
    useradd --system --create-home --home-dir "$DEPLOY_HOME" --shell /bin/bash "$DEPLOY_USER"
fi
usermod -a -G www-data "$DEPLOY_USER"

install -d -m 0755 -o root -g root "$APP_ROOT"
install -d -m 2770 -o "$DEPLOY_USER" -g www-data "$APP_ROOT/releases"
install -d -m 0750 -o root -g www-data "$SHARED"
install -d -m 0770 -o www-data -g www-data "$SHARED/print-packages"
install -d -m 0700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$DEPLOY_HOME/incoming"
install -d -m 0700 -o root -g root /var/lib/loyalty-deploy
install -d -m 0700 -o www-data -g www-data /var/backups/loyalty-platform

environment_source=$LEGACY_ENV_EXPORT
if [[ -f "$SHARED/.env" ]]; then
    environment_source=$SHARED/.env
fi
install -m 0600 -o root -g root "$environment_source" "$SHARED/.env.next"
python3 "$SCRIPT_DIR/configure_production_env.py" "$SHARED/.env.next"
chown root:www-data "$SHARED/.env.next"
chmod 0640 "$SHARED/.env.next"
mv -f "$SHARED/.env.next" "$SHARED/.env"

install -d -m 0750 -o root -g www-data "$SHARED/secrets"
install -m 0640 -o root -g www-data \
    /var/www/turnkey_project/dotykacka/google_wallet/upbeat-button-473611-h9-e57fb2fd56ee.json \
    "$SHARED/secrets/google-wallet-service-account.json"

install -d -m 0750 -o root -g www-data "$SHARED/mypass_template"
while IFS= read -r -d '' wallet_file; do
    install -m 0640 -o root -g www-data "$wallet_file" "$SHARED/mypass_template/"
done < <(find /var/www/turnkey_project/mypass_template -maxdepth 1 -type f -print0)

public_key=$(tr -d '\r\n' < "$DEPLOY_PUBLIC_KEY")
[[ "$public_key" == ssh-ed25519\ * ]] || {
    echo "deployment public key must be an ssh-ed25519 key" >&2
    exit 1
}
install -d -m 0700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$DEPLOY_HOME/.ssh"
printf 'no-agent-forwarding,no-port-forwarding,no-X11-forwarding,no-pty %s\n' "$public_key" \
    > "$DEPLOY_HOME/.ssh/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "$DEPLOY_HOME/.ssh/authorized_keys"
chmod 0600 "$DEPLOY_HOME/.ssh/authorized_keys"

install -m 0755 -o root -g root "$SCRIPT_DIR/deploy.sh" /usr/local/sbin/loyalty-deploy
install -m 0755 -o root -g root "$SCRIPT_DIR/rollback.sh" /usr/local/sbin/loyalty-rollback
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/loyalty-deploy\n' "$DEPLOY_USER" \
    > /etc/sudoers.d/loyalty-deploy
chmod 0440 /etc/sudoers.d/loyalty-deploy
visudo -cf /etc/sudoers.d/loyalty-deploy >/dev/null

echo "bootstrap complete; the legacy application was not restarted or modified"
