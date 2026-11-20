# Virtual card API

The virtual-card API creates unique card identities starting at `MB-601` while
reusing the tenant's already-rendered `MB-1..600` artwork files. No front, back
or preview image is copied or rendered again. `MB-601` uses the artwork of
`MB-1`, `MB-602` uses `MB-2`, and the mapping repeats after 600 source cards.
Apple Wallet and Google Wallet receive the new unique card code and barcode,
but display the saved front artwork from the mapped source card. The resulting
Wallet cards are delivered only to the submitted email address.

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

The response contains exactly four currently available virtual identities,
ordered by card number. Each item contains its database `id`, unique
`card_code`, mapped `artwork_source_card_code`, and URLs that serve the existing
source front and back files. `preview_url` is the same image as `front_url`.

```json
{
  "results": [
    {
      "id": 742,
      "name": "MB-601",
      "card_code": "MB-601",
      "artwork_source_card_code": "MB-1",
      "preview_url": "https://club.mbstudio.online/dotykacka/c/marta-banaszek-atelier-cafe/virtual-card/cards/742/front",
      "front_url": "https://club.mbstudio.online/dotykacka/c/marta-banaszek-atelier-cafe/virtual-card/cards/742/front",
      "back_url": "https://club.mbstudio.online/dotykacka/c/marta-banaszek-atelier-cafe/virtual-card/cards/742/back"
    }
  ]
}
```

Send the chosen `card_code` when issuing the card. `card_id` is also accepted.
For compatibility, the former `card_design_id` field is temporarily accepted
as an alias for the returned numeric card `id`.

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
  "card_code": "MB-601",
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
  "card_id": "MB-601",
  "card_created": true,
  "card": {
    "id": "MB-601",
    "created": true,
    "wallet_pass_id": "19e2f1bc-3f24-4fb7-a5c6-2c94366f661e",
    "inventory_card_id": 742,
    "front_url": "https://club.mbstudio.online/dotykacka/c/marta-banaszek-atelier-cafe/virtual-card/cards/742/front",
    "back_url": "https://club.mbstudio.online/dotykacka/c/marta-banaszek-atelier-cafe/virtual-card/cards/742/back"
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
the API. Both Apple Wallet and Google Wallet use the already-saved
`*_front.jpg` file of the mapped `MB-1..600` artwork source. The new `MB-601+`
row stores no copied front or back file. Its unique code is used for the
customer identity, barcode, Apple serial association and Google object. The
source `*_back.jpg` remains available in the catalog response but is not used
as the Wallet hero/strip artwork.
