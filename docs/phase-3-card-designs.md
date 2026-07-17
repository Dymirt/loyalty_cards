# Phase 3 tenant card design and unified generators

Phase 3 replaces the duplicated standalone artwork and Wallet implementations
with tenant-aware Django services. It preserves every Marta database row and
legacy media path.

## Additive schema

Migrations `0012` and `0013` add:

- immutable `TenantBrandRevision` records;
- immutable, versioned `CardDesign` records;
- immutable `CardArtifact` metadata with a UUID key, SHA-256, byte size, and
  tenant/design/batch/card ownership;
- `WalletPass` identities with a stable Apple serial and optional stable Google
  object ID;
- a nullable `CardBatch.design` reference.

The data migration creates Marta brand/design v1 from the existing settings,
links the existing legacy batch through the new nullable field, and appends one
Wallet identity for each of the 267 customers. It does not rename, copy,
regenerate, delete, or rewrite any legacy card, crop, barcode, or `.pkpass`
file. Its reverse operation is deliberately a no-op.

## Design portal

Tenant owners and platform superusers can use:

```text
/dotykacka/c/<tenant-slug>/settings/card-design
```

The page provides organization/brand fields, validated JPG/PNG/WebP uploads,
controlled layout/crop settings, colors, dimensions, DPI, bleed, logo size,
front/back text, and the bundled Barlow font. Uploaded filenames never control
storage paths.

`Generuj podgląd` is an HTMX-enhanced ordinary multipart POST. It renders the
front/back proof on the server without publishing a design. The same form works
as a normal HTML POST. `Opublikuj nową wersję` appends a brand revision, design
version, audit event, and immutable proof artifacts. Existing versions reject
in-place save/delete operations.

Proof/artifact downloads are streamed by an owner-authorized Django view. The
global media tree is not used as the authorization boundary. Production print
packages remain platform-only work for Phase 4.

## One generator implementation

`dotykacka.services.card_designs` owns:

- deterministic center/focal/seeded cover crops;
- logo placement and approved-font text composition;
- Code 128 barcode generation;
- front/back JPEG output and validation;
- proof and card manifests;
- SHA-256 calculation;
- atomic publication to a new immutable run directory.

Paths follow this shape:

```text
tenants/<tenant>/designs/v0001/batch-<id>/runs/<uuid>/cards/<code>/front.jpg
tenants/<tenant>/designs/v0001/proofs/runs/<uuid>/cards/<code>/proof-front.jpg
tenants/<tenant>/designs/v0001/wallet/apple/<serial>/runs/<uuid>/card.pkpass
```

Every retry receives a new UUID run directory. Existing bytes and database
artifact records are never overwritten.

Apple Wallet generation builds tenant-specific pass metadata, uses the stable
database serial, creates the Apple SHA-1 manifest, signs it with the existing
platform certificate through OpenSSL, and stores the resulting `.pkpass` as an
immutable checksummed artifact. Google Wallet keeps one issuer-scoped object ID
per Wallet identity and uses tenant-specific image description/branding.

The old root scripts contain no numeric loops. They delegate to the following
bounded Django commands, which use the same services as the portal:

```bash
python manage.py generate_card_artifacts \
  --tenant <slug> --design-version <n> --start <n> --end <n> --dry-run

python manage.py generate_wallet_passes \
  --tenant <slug> --start <n> --end <n> --wallet apple --dry-run
```

Both commands require an explicit tenant and bounded card/customer selection,
enforce a maximum count, and perform no generation in `--dry-run` mode.

## Verification on the local replica

Before migration, a new compressed MariaDB backup was created and verified.
The read-only legacy preflight reported 267 customers, 262 append-only cached
tokens, 600 complete card asset sets, 267 assigned cards, 333 available cards,
and zero missing/malformed/duplicate items.

After migration:

- migrations `0012` and `0013` are applied;
- one Marta brand revision and one card design exist;
- the legacy batch references Marta design v1;
- all 267 customers have Wallet identity records;
- Wallet/customer/card and batch/design tenant mismatch counts are zero;
- Phase 0 and Phase 1 aggregate verifiers still pass;
- `manage.py check` and `makemigrations --check --dry-run` pass;
- 80 tests pass on the fully migrated isolated database;
- the pinned golden image distinguishes Marta from a synthetic tenant;
- desktop visual inspection passes with no browser-console errors.

Run the non-sensitive verifier at any time:

```bash
python manage.py verify_card_design_backfill
```
