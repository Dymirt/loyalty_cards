# Phase 8 centralized print request, production, and fulfillment

Completed on 18 July 2026. This phase adds an end-to-end, tenant-requested and platform-operated physical-card workflow without changing or inferring the print/delivery state of any existing Marta card.

## Result

- A tenant owner selects a published design and an accepted immutable quote, explicitly accepts the frozen proof checksum, supplies a delivery address, and submits one idempotent print request.
- A platform superuser reviews, approves or rejects the request. Approval alone allocates nothing.
- Allocation locks the tenant inventory boundary, assigns one contiguous never-reused card-number range, creates the card batch/run trace, consumes the accepted quote exactly once, and enqueues a database-backed production job.
- The separately supervised `run_print_worker` command generates each front, back and barcode through the shared `card_artwork` service. It validates dimensions, DPI, byte size and SHA-256 before publishing an immutable ZIP.
- The ZIP contains deterministic paths, the per-card files and a JSON manifest that freezes the tenant, request, quote, design, layout, crop-plan and checksum trace. It is stored under `PRINT_PACKAGE_ROOT`, outside public `MEDIA_ROOT`.
- Only a superuser can download a package or record printing, printed, packed, dispatched and delivered events. Downloads are audited.
- Corrections append a compensating event with a reason. Production and fulfillment history cannot be deleted or rewritten through models or Django admin.
- A dry-run-only legacy report can select an exact Marta batch/range. A second action requires the exact preview count and only appends printed/delivered events; it never modifies card assignment, artwork, usage or commercial values.

Both tenant and operator forms work as ordinary Django requests. HTMX is used only for proof/report fragments and worker-status polling; there is no new JavaScript workflow or runtime technology.

## Additive schema

Two forward migrations were applied:

- `billing.0002_printquoteconsumption` creates the append-only one-to-one bridge between an accepted quote and its single physical-production usage event.
- `printing.0001_initial` creates `PrintRequest`, `PrintRequestEvent`, `PrintRun`, `PrintRunCard`, `PrintJob`, `PrintPackage`, and `FulfillmentEvent`.

All relationships that protect production history use `PROTECT`. Request inputs and run snapshots are immutable after submission/allocation. Status changes pass through controlled service transitions and append a request event. Package manifests and fulfillment records are append-only. The migrations contain schema operations only and call no provider.

## Production profile

The current safe profile is `per-card-jpeg-zip-v1`. It uses the exact published design width, height, DPI and bleed values and the existing Pillow renderer, then packages individually validated front/back JPEGs and barcode PNGs. It deliberately does not guess a printer sheet size, imposition grid, duplex rotation, crop-mark convention, ICC profile or PDF format.

Before adding sheet/PDF output, obtain the production printer's finished size, bleed and safe area, DPI, color profile, sheet/imposition, crop marks, duplex orientation, file type and naming convention. That later profile can be added beside this immutable profile without changing prior runs.

## Authorization and recovery

- Tenant submission requires the existing billing-management role for that tenant; object querysets and service checks are tenant-scoped.
- Queue review, allocation, package download, fulfillment, corrections and legacy reconciliation require a platform superuser.
- Production packages are never served by the Apache `/media/` alias; the authenticated download view validates size and checksum before streaming them. Django's deployment check rejects a package root nested under `MEDIA_ROOT` or `STATIC_ROOT`.
- Duplicate request, job, usage and fulfillment keys converge on existing records.
- A cancelled allocated run marks its unused allocated cards `VOID`; numbers are never returned to inventory.
- A transient worker failure is retried from the durable database job. A terminal failure keeps all trace records and can be explicitly retried; it does not delete files or reallocate codes.
- Prefer a roll-forward code fix. Do not reverse either migration after print records exist, because reversal would drop operational history tables.

Run the production worker as a separate supervised process:

```bash
python manage.py run_print_worker
```

Use `python manage.py run_print_worker --once` for a bounded worker check. Docker Compose now includes the independent `print_worker` service.

## Verification evidence

Pre-upgrade backups:

- database: `local-data/backups/pre-phase8-20260718-013500.sql.gz` — SHA-256 `7c08b87e04d901341cde7a39f794e5dcc3b821b7f9ae9732f79571657bfc8db7`;
- runtime media: `local-data/backups/pre-phase8-media-20260718-013500.tar.gz` — SHA-256 `b7f75347b34592a0a50b1348b1dbc19fb8472abce298cd28d3ba2f9892611ef6`.

Post-upgrade Marta invariants:

- 267 customers;
- 600 physical cards: 267 assigned and 333 available;
- 263 historical access-token records;
- one active tenant membership;
- three integration connections;
- zero print quote consumptions, requests, runs, packages, fulfillment events and print jobs immediately after migration.

The isolated suite passes 179 tests; two MariaDB row-lock concurrency cases are skipped only when the suite runs on SQLite. Coverage includes duplicate submission, frozen snapshots, quote/pack consumption, contiguous allocation, MariaDB concurrency, renderer reuse, manifest/file checksums, crop trace, protected storage checks, platform-only audited downloads/actions, terminal worker failure, HTMX fallbacks, controlled fulfillment/corrections, cancellation/VOID behavior, and no-change legacy preview/reconciliation boundaries.

Final checks also pass:

```text
manage.py check: no issues
makemigrations --check --dry-run: no changes
verify_app_extraction --strict --expect-marta: passed
46 models / 46 content types / 184 permissions
308 URL patterns / 39 commands / 41 admin registrations
docker compose config --quiet: passed
print_worker: running
```
