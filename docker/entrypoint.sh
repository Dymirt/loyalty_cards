#!/bin/sh
set -eu

cd /var/www/loyalty_platform

mkdir -p \
    media/logs \
    media/output_passes \
    staticfiles \
    var/logs

# These bind-mounted runtime directories must be writable by Apache's
# www-data worker in the local development container.
chmod 0777 media/logs media/output_passes var/logs

# Copy private Wallet credentials out of read-only host mounts into a
# container-only runtime directory readable by the Apache worker.
install -d -m 0700 -o www-data -g www-data /run/loyalty-secrets
install -m 0600 -o www-data -g www-data \
    /source-secrets/google-wallet-service-account.json \
    /run/loyalty-secrets/google-wallet-service-account.json
install -d -m 0700 -o www-data -g www-data \
    /run/loyalty-secrets/mypass_template
find /source-mypass-template -maxdepth 1 -type f -exec \
    install -m 0600 -o www-data -g www-data {} \
    /run/loyalty-secrets/mypass_template/ \;

python manage.py migrate --noinput
python manage.py collectstatic --noinput --verbosity 0
python manage.py check

exec "$@"
