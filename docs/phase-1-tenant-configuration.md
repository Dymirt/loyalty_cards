# Phase 1 tenant configuration boundary

Phase 1 separates SaaS-platform configuration from settings that belong to one
client. The application must be migrated before tenant-aware code is served.

## Stored per tenant in MariaDB

The following values are editable by an authorized tenant owner or platform
superuser at `/dotykacka/c/<tenant-slug>/settings/integrations`:

| Provider | Non-secret configuration | Encrypted credentials |
| --- | --- | --- |
| Dotykačka | cloud ID, discount-group ID, enabled state | authorization token |
| Brevo | list ID, default phone country code, enabled state | API key |
| Google Wallet | issuer ID, class suffix, enabled state | none; signing remains platform-owned |

Tenant identity, card prefix, locale/timezone, contact details, logo/background
paths, registration consent copy, and email branding also live in tenant-owned
database rows. Integration updates write a redacted `AuditEvent`; secret values
are never included in HTML, Django admin, messages, or audit metadata.

`IntegrationConnection.credentials_encrypted` uses versioned Fernet encryption.
`TENANT_SECRETS_ENCRYPTION_KEYS` is a comma-separated key ring: the first key
encrypts new values and later keys decrypt older values during rotation. The key
ring must remain outside the database and backups. Do not remove an old key
until all values have been re-encrypted with the new primary key.

## Kept in the environment

- Django secret/security, hosts, cookies, and public application origins;
- database connection and SMTP transport credentials;
- `TENANT_SECRETS_ENCRYPTION_KEYS`;
- provider timeouts such as `DOTYKACKA_HTTP_TIMEOUT`;
- Google service-account file/email and allowed Wallet origins;
- Apple Wallet signing identifiers, certificate/key material, and template
  location used by the centralized platform issuer;
- runtime filesystem paths and deployment-only settings.

These values operate the SaaS platform or shared signing/transport boundary and
are not editable by a tenant.

## Marta one-time import

Migration `0010_backfill_marta_tenant` reads the legacy client variables only
to initialize the first tenant:

- `DOTYKACKA_AUTHORIZATION_TOKEN`
- `DOTYKACKA_CLOUD_ID`
- `DOTYKACKA_DISCOUNT_GROUP_ID`
- `BREVO_API_KEY`
- `BREVO_LIST_ID`
- `DEFAULT_PHONE_COUNTRY_CODE`
- `GOOGLE_WALLET_ISSUER_ID`
- `GOOGLE_WALLET_CLASS_SUFFIX`

The migration makes no external calls. It encrypts secrets before writing them,
then tenant-aware runtime code stops reading these legacy variables. Keep them
available until migration and aggregate verification both succeed; remove their
values from the deployment environment afterward through the normal secret
management process.

## Required deployment order

1. Run the Phase 0 read-only preflight and take separate verified database and
   media backups.
2. Set a dedicated `TENANT_SECRETS_ENCRYPTION_KEYS` value, or retain the current
   `DJANGO_SECRET_KEY` until credentials have been re-encrypted with a dedicated
   key. Never rotate both at the same time.
3. Apply migrations `0008` through `0011`.
4. Run `python manage.py verify_marta_backfill` and confirm the expected
   non-sensitive aggregates: one membership, 267 customers, 261 tokens, 600
   physical cards, 267 assigned and 333 available.
5. Run `python manage.py check` and the Phase 0 inventory preflight again.
6. Verify the settings page reports configured secrets without displaying their
   values, then clear the legacy client variables from the environment.

The data migration has a no-op reverse. Rollback means deploying compatible
application code; never reverse or delete the tenant records.
