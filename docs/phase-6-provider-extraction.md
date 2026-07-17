# Phase 6 provider extraction and durable jobs

Completed on 17 July 2026. This phase extracts integration behavior while retaining every historical `dotykacka` model, table, credential envelope, token row, Wallet identity and media path.

## Result

- `integrations` owns encryption behavior, `IntegrationJob`, provider registration, owner-only settings orchestration and `run_integration_worker`.
- `pos` defines the POS customer contract. `pos_dotykacka` owns Connector v2, callback state, encrypted cloud token caching, 401 refresh, bounded pagination and customer reconciliation.
- `communications` defines contact/email behavior. `brevo` owns consent-gated contact upsert/list membership and rate-limit handling. It never sends `forceMerge` or blacklist-reset fields.
- `wallets` owns stable legacy `WalletPass` identity orchestration. `wallet_apple` owns package/signing/artifact behavior; `wallet_google` owns class/object REST upsert and signed save links.
- `dotykacka.api_utils`, `dotykacka.brevo`, Wallet modules and the historical URL namespace remain compatibility adapters.
- Public enrollment creates idempotent provider jobs after its local atomic customer/card/consent operation returns. No daemon thread remains.
- Docker Compose supervises the database worker separately from Apache. Stale running claims are recoverable after five minutes and retries are bounded.

## Additive schema

Only these migrations were applied:

- `integrations.0001_initial` creates `integrations_integrationjob`.
- `pos_dotykacka.0001_initial` creates `pos_dotykacka_dotykackaconnectstate` and `pos_dotykacka_dotykackaaccesstoken`.

The original Phase 6 provider migrations contain `CreateModel` operations only
and call no provider. Later data migration `dotykacka.0014` performs no external
call; it only promotes an already-encrypted legacy Marta authorization value to
the canonical tenant Refresh Token key while preserving the original key.

Connector state stores SHA-256 digests of the random state and browser session key, plus tenant, initiating user and 15-minute expiry. Raw state exists only in the browser POST. New access tokens are Fernet-encrypted and scoped to tenant, connection and cloud with explicit expiry/invalidation. Historical `dotykacka_accesstoken` rows remain unchanged.

## Credential ownership

Tenant database connection:

- Dotykačka Cloud ID, discount group, enabled/status fields and the encrypted Connector callback Refresh Token;
- Brevo API key, list ID and default phone country code;
- Google Wallet enabled state only; historical issuer/class JSON is retained but ignored.

Platform environment/protected files:

- Dotykačka Connector client ID/client secret and API/Connector endpoints;
- Apple Pass Type/Team identifiers and signing files;
- Google service-account JSON, central issuer ID, origins and Wallet API endpoint;
- Django/database/email/encryption/transport settings.

Connector callbacks merge the new Refresh Token into existing credentials. Migration `dotykacka.0014` promotes historical Dotykačka authorization values to the canonical tenant `refresh_token` key while preserving the legacy key; it does not change Wallet or other provider values.

The Dotykačka tenant page never renders or accepts a raw Refresh Token and does
not expose technical test history. An authorized tenant owner starts Connector
v2 from that page and authenticates directly with Dotykačka. The callback stores
the returned Cloud ID and encrypted Refresh Token. Cloud ID is read-only and a
callback selecting another cloud is rejected until the tenant explicitly
disconnects. Disconnect disables the integration, removes the active Refresh
Token and Cloud ID, invalidates cached Access Tokens and pending Connector
states, and preserves historical authorization data and audit history.

## Provider behavior

Dotykačka follows Connector v2: the browser submits a form POST with `client_id`, Unix timestamp, HMAC-SHA256 signature, `scope=*`, redirect URI and random state. The callback accepts `token`, `cloudid` and matching state only for the initiating user/session/tenant. Access-token requests use that tenant's encrypted Refresh Token as `Authorization: User <refresh-token>` together with JSON `_cloudId`. A cached access token has a safety skew; one authorized 401 invalidates it, refreshes once and retries once.

Brevo sends the tenant API key in `api-key`. Contact upsert uses stable `ext_id`, normalized SMS, declared attributes, tenant list IDs and `updateEnabled=true`. Marketing consent is checked from append-only `ConsentRecord` evidence before network access. Duplicate reconciliation adds the configured list without force-merging contacts or changing blocklist fields. `x-sib-ratelimit-reset`, 429, timeout and 5xx responses become resumable job failures.

Apple builds a fresh immutable artifact path for each run while retaining the same `apple_serial`. Google retains one `google_object_id`, upserts its tenant class/object through REST and creates save links for that same object. Apple/Google signing credentials remain platform-owned.

Every Google Wallet object uses the platform issuer from
`GOOGLE_WALLET_ISSUER_ID`. The distinct class suffix is derived internally from
the tenant's unique card prefix, so tenant branding remains isolated without
exposing Google identifiers in the client portal. Historical tenant
`issuer_id`/`class_suffix` JSON remains unchanged for rollback safety.

## Operations

Run the worker under a supervisor:

```bash
python manage.py run_integration_worker
```

Useful bounded diagnostics:

```bash
python manage.py run_integration_worker --once
python manage.py run_integration_worker --max-jobs 20
python manage.py verify_app_extraction --strict
python manage.py verify_marta_backfill
```

Tenant owners use `/dotykacka/c/<slug>/settings/integrations` for business
configuration and the Dotykačka authorization lifecycle. The owner starts the
provider login there; the callback stores the encrypted tenant Refresh Token
and Cloud ID. Cloud ID is read-only and a different callback cloud is rejected
until the owner explicitly disconnects. Disconnect disables the connection,
clears the active Refresh Token and Cloud ID, and invalidates active access and
pending Connector state without deleting audit history. Save and permitted
provider-test forms work without JavaScript; HTMX replaces only the
settings/status fragment when available. Platform Connector credentials and
redacted technical tests remain restricted to platform-superuser endpoints.

Platform superusers use `/dotykacka/platform/system-connections` for redacted
checks of Google Wallet, Apple Wallet, SMTP, Dotykačka Connector, active tenant
Dotykačka authorizations and active tenant Brevo keys. Google performs a
read-only issuer API request, SMTP opens and closes a connection without
sending, and the Connector test only validates platform signing readiness.

## Verification evidence

Pre-upgrade backup:

- database: `local-data/backups/pre-phase6-20260717-223435.sql.gz` — SHA-256 `7b7512ba0a3646082e634682bebec2967ec2ba953dfb3e9649ca3a312f48016e`;
- media: `local-data/backups/pre-phase6-media-20260717-223435.tar.gz` — SHA-256 `ade772b06cecde85d034830e0eb312b80c675329f593eabb749ee5a3af7fcf7d`.

Post-upgrade Marta invariants:

- 267 customers;
- 600 physical cards: 267 assigned, 333 available;
- 263 historical access tokens;
- 267 Wallet identities;
- three tenant integration connections with the existing Dotykačka/Brevo secrets still configured;
- zero new jobs, Connector states or encrypted access-token rows immediately after migration;
- no pending migrations.

The current isolated SQLite suite passes 163 tests with one database-locking
case skipped on SQLite. The strict Marta extraction verifier reports 38 models,
38 content types, 152 permissions, 246 URL patterns, 38 commands, 33 admin
registrations and three historical admin-log reference groups. Django checks,
migration drift, architecture boundaries, Compose configuration, local
registration/login HTTP responses and the supervised worker process all pass.

## Recovery rule

Prefer a roll-forward code fix. Do not reverse these migrations after they have accepted jobs/tokens/states because reversal drops their tables. If the upgrade must be abandoned before any Phase 6 state is created, stop the worker/web processes and restore the verified SQL/media backups through the documented Phase 0 recovery procedure. Never edit or delete Marta rows manually.

## Official contracts reviewed

- [Dotykačka Connector v2 and access tokens](https://docs.api.dotypos.com/authorization/)
- [Dotykačka customer API](https://docs.api.dotypos.com/entity/customer/)
- [Brevo API-key authentication](https://developers.brevo.com/docs/api-key-authentication)
- [Brevo create/upsert contact](https://developers.brevo.com/reference/create-contact)
- [Brevo rate-limit headers](https://developers.brevo.com/docs/limit-headers)
- [Apple Wallet pass source](https://developer.apple.com/documentation/walletpasses/creating-the-source-for-a-pass)
- [Apple Wallet pass build/sign/package](https://developer.apple.com/documentation/walletpasses/building-a-pass)
- [Google Wallet classes and objects](https://developers.google.com/wallet/generic/overview/how-classes-objects-work)
- [Google Wallet read-only loyalty class list](https://developers.google.com/wallet/reference/rest/v1/loyaltyclass/list)
- [Google Wallet REST service-account authentication](https://developers.google.com/wallet/retail/loyalty-cards/getting-started/auth/rest)
- [Google Wallet loyalty JWT](https://developers.google.com/wallet/retail/loyalty-cards/use-cases/jwt)
