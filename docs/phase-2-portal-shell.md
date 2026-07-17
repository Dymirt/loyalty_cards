# Phase 2 portal shell

Phase 2 adds an accessible server-rendered portal without changing the database
schema or adding a JavaScript application framework.

## Runtime and build boundary

Django, HTMX, and ordinary HTML forms remain the runtime architecture. Node is
used only on a development/build machine to compile and vendor static files:

```bash
npm ci
npm run build
python manage.py collectstatic --noinput
```

The resulting files are committed under `static/`, so the production Docker
image and Apache/mod_wsgi runtime do not require Node or npm.

Pinned dependencies:

| Asset | Version | Runtime purpose |
| --- | --- | --- |
| Tailwind CSS / CLI | 4.3.2 | Build `static/css/portal.v1.css` from `assets/css/portal.css` |
| HTMX | 2.0.10 | Progressive enhancement of tenant integration forms |
| ZXing library | 0.21.3 | Optional in-browser camera barcode decoding |

ZXing 0.21.3 is intentionally pinned instead of the newer package line because
it supports the project's available Node 22 build environment. The generated
browser bundle remains local and versioned.

## Portal structure

- `templates/base.html` provides the page shell, skip link, responsive header,
  authenticated navigation, messages, footer, local Tailwind CSS, and local
  HTMX script.
- `/accounts/login/` is the client-facing Django authentication page; logout is
  POST-only.
- `/dotykacka/c/<tenant-slug>/portal` is available to active tenant members and
  platform superusers.
- Integration settings remain owner/platform-only and include an explicit
  tenant settings navigation.
- `/dotykacka/platform/print-center` is a separate superuser-only platform shell
  showing tenant inventory aggregates. Print-request workflow remains Phase 4.
- Public landing and registration pages use the tenant's existing logo,
  background, name, and text.

## HTMX fallback contract

Integration forms contain normal `method="post"`, action resolution, CSRF
tokens, server-side validation, and Django redirect/messages behavior. HTMX adds
`hx-post`, `hx-target`, `hx-select`, a disabled-submit state, and a progress
indicator. If HTMX fails to load or JavaScript is disabled, submitting the same
form performs a full-page POST and produces the same database result.

No registration, bulk action, login, logout, or navigation behavior depends on
HTMX. The server always returns HTML, not a client-side JSON application state.

## JavaScript boundary

`static/js/card-scanner.v1.js` is the only custom JavaScript on active loyalty
screens. Camera access and barcode decoding require browser APIs and cannot be
implemented with HTMX. The button is hidden until the local ZXing bundle and
camera API are available; users can always enter a code manually. The scanner:

- requests only video, never microphone/location;
- stops video tracks after a result, close action, or page exit;
- does not send frames or decoded values to a third party;
- does not prevent or delay ordinary form submission.

The old demonstration page and its legacy jQuery files are preserved for
recovery compatibility at `/turnkey/`, but no active loyalty route references
them. Bootstrap, jQuery, `@latest`, and external UI CDNs were removed from every
active loyalty template.

## Verification

- 72 Django tests pass on an isolated migrated database.
- Django system check passes.
- `makemigrations --check --dry-run` reports no changes.
- `npm install` audit reported no known vulnerabilities in the pinned build set.
- Compiled CSS, HTMX, ZXing, landing, registration, login, tenant portal, role
  denials, and platform print-center behavior have automated coverage.
- Local HTTP checks returned 200 for landing, registration, compiled CSS, and
  HTMX; the anonymous tenant portal correctly redirected to login.
- Desktop landing and 390×844 mobile registration were visually inspected in
  the in-app browser with no console errors. Camera permission was not requested.
