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

The response contains the four newest tenant-scoped designs. Each item includes
an `id`, name, colors and `preview_url`. Send the selected `id` as
`card_design_id`; the choice is stored permanently on the issued Wallet pass.

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
The response contains both `request_id` and the already-created `card_id`, plus
the status URL. It deliberately contains no Wallet pass, download URL or Google
save URL; those are delivered only to the customer's email address.

```json
{
  "request_id": "b2b21475-5077-4cf9-87e2-c46118a39e98",
  "state": "processing",
  "card_id": "MB-V-63C7494B8EBF4D1A",
  "card_created": true,
  "card": {
    "id": "MB-V-63C7494B8EBF4D1A",
    "created": true,
    "wallet_pass_id": "19e2f1bc-3f24-4fb7-a5c6-2c94366f661e",
    "design_id": 12
  },
  "delivery": {
    "apple_wallet": {
      "status": "succeeded",
      "ready": true,
      "identifier": "19e2f1bc-3f24-4fb7-a5c6-2c94366f661e",
      "last_error_code": ""
    },
    "google_wallet": {
      "status": "pending",
      "ready": false,
      "identifier": null,
      "last_error_code": ""
    },
    "email": {
      "status": "pending",
      "ready": false,
      "identifier": null,
      "last_error_code": ""
    }
  },
  "status_url": "https://club.mbstudio.online/api/v1/virtual-cards/b2b21475-5077-4cf9-87e2-c46118a39e98/"
}
```

## Request status

```http
GET /api/v1/virtual-cards/<request-id>/
Authorization: Bearer lvc_live_...
```

Possible states are `queued`, `processing`, `email_sent` and `failed`. The
`delivery` object separately reports `apple_wallet`, `google_wallet` and
`email`, with `status`, `ready`, `identifier` and `last_error_code` fields. A
status resource is visible only to the same API key that created it. Poll this
endpoint until `state` is `email_sent` or `failed`. Revoking a key immediately
blocks all subsequent requests authenticated with it.

The Apple pass is sent as a `.pkpass` attachment and as an expiring signed
"Add to Apple Wallet" link in the email. The signed link is never returned by
the API.
