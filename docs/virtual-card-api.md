# Virtual card API

The virtual-card API creates a tenant-owned customer without assigning a
physical card. Apple Wallet and/or Google Wallet issuance runs in the existing
integration worker and the resulting cards are delivered only to the submitted
email address.

## Authentication

An owner generates a separate key for each backend integration at:

`/dotykacka/c/<tenant-slug>/settings/virtual-card-api`

Send the key as `Authorization: Bearer lvc_live_...`. The full value is shown
once; only its SHA-256 digest and visible prefix are stored. Never embed this
secret in browser JavaScript or a public HTML form.

## List available designs

```http
GET /api/v1/virtual-card-designs/
Authorization: Bearer lvc_live_...
```

The response contains tenant-scoped design IDs, names, colors and public image
URLs for the design background and logo.

## Issue a virtual card

```http
POST /api/v1/virtual-cards/
Authorization: Bearer lvc_live_...
Idempotency-Key: order-2026-0001
Content-Type: application/json

{
  "first_name": "Anna",
  "last_name": "Nowak",
  "email": "anna@example.com",
  "phone": "+48500100200",
  "card_design_id": 1,
  "marketing_consent": true
}
```

A new request returns `202 Accepted`; an identical idempotent replay returns
`200 OK`. Reusing the same key with different data returns `409 Conflict`.
The response contains a request ID and status URL, but deliberately contains no
Wallet pass, download URL or Google save URL.

## Request status

```http
GET /api/v1/virtual-cards/<request-id>/
Authorization: Bearer lvc_live_...
```

Possible states are `queued`, `processing`, `email_sent` and `failed`. A status
resource is visible only to the same API key that created it. Revoking a key
immediately blocks all subsequent requests authenticated with it.
