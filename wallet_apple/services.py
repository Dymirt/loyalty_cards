"""Apple Wallet package generation with immutable identities and artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import transaction
from PIL import Image
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import NameOID

from card_artwork.models import CardArtifact, CardDesign
from card_artwork.services import bytes_sha256, render_card, spec_from_design
from integrations.contracts import SystemCheckResult
from wallets.models import WalletPass
from wallets.services import apple_pass_path, wallet_identity


EXCLUDED_MANIFEST_FILES = {
    "manifest.json",
    "signature",
    "certificate.pem",
    "key.pem",
    "AppleWWDR.pem",
}


def generate_manifest(pass_dir) -> dict[str, str]:
    pass_path = Path(pass_dir)
    manifest = {
        path.name: hashlib.sha1(path.read_bytes()).hexdigest()
        for path in sorted(pass_path.iterdir())
        if path.is_file() and path.name not in EXCLUDED_MANIFEST_FILES
    }
    (pass_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return manifest


def sign_manifest(pass_dir):
    template_dir = Path(settings.APPLE_WALLET_TEMPLATE_DIR)
    required = ("AppleWWDR.pem", "certificate.pem", "key.pem")
    missing = [name for name in required if not (template_dir / name).is_file()]
    if missing:
        raise ImproperlyConfigured(
            f"Apple Wallet signing material is incomplete: {', '.join(missing)}"
        )
    subprocess.run(
        [
            "openssl",
            "smime",
            "-binary",
            "-sign",
            "-certfile",
            str(template_dir / "AppleWWDR.pem"),
            "-signer",
            str(template_dir / "certificate.pem"),
            "-inkey",
            str(template_dir / "key.pem"),
            "-in",
            str(Path(pass_dir) / "manifest.json"),
            "-out",
            str(Path(pass_dir) / "signature"),
            "-outform",
            "DER",
        ],
        check=True,
        capture_output=True,
    )


def _rgb(hex_color: str) -> str:
    value = hex_color.lstrip("#")
    return f"rgb({int(value[0:2], 16)}, {int(value[2:4], 16)}, {int(value[4:6], 16)})"


def apple_pass_payload(*, customer, wallet: WalletPass, design: CardDesign) -> dict:
    brand = design.brand_revision
    website_label = (
        brand.website_url.replace("https://", "").replace("http://", "").upper()
    )
    return {
        "formatVersion": 1,
        "passTypeIdentifier": settings.APPLE_WALLET_PASS_TYPE_IDENTIFIER,
        "serialNumber": str(wallet.apple_serial),
        "teamIdentifier": settings.APPLE_WALLET_TEAM_IDENTIFIER,
        "organizationName": brand.public_name,
        "description": f"Karta lojalnościowa {brand.public_name}",
        "foregroundColor": _rgb(design.foreground_color),
        "backgroundColor": _rgb(design.panel_color),
        "logoText": brand.public_name,
        "storeCard": {
            "headerFields": [
                {
                    "key": "customerNumber",
                    "label": "NUMER",
                    "value": customer.klient_id,
                }
            ],
            "secondaryFields": [
                {"key": "website", "label": website_label, "value": ""},
                {
                    "key": "phone",
                    "label": brand.phone,
                    "value": "",
                    "textAlignment": "PKTextAlignmentRight",
                },
            ],
        },
        "barcode": {
            "format": "PKBarcodeFormatCode128",
            "message": customer.klient_id,
            "messageEncoding": "iso-8859-1",
        },
    }


def _write_png(jpeg_bytes: bytes, path: Path):
    with Image.open(BytesIO(jpeg_bytes)) as image:
        image.save(path, format="PNG", optimize=False)


def _write_zip(source_dir: Path, target: Path):
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(source_dir.iterdir()):
            if not source.is_file():
                continue
            info = zipfile.ZipInfo(source.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, source.read_bytes())


def build_apple_pass(*, customer, wallet: WalletPass, design: CardDesign):
    if customer.tenant_id != design.tenant_id or wallet.tenant_id != design.tenant_id:
        raise ValidationError("Customer, Wallet identity and design must share a tenant.")
    if not settings.APPLE_WALLET_PASS_TYPE_IDENTIFIER or not settings.APPLE_WALLET_TEAM_IDENTIFIER:
        raise ImproperlyConfigured("Apple Wallet platform identifiers are not configured.")
    rendered = render_card(spec_from_design(design), customer.klient_id)
    run_id = uuid4().hex
    relative_root = Path(
        f"tenants/{design.tenant.slug}/designs/v{design.version:04d}/wallet/apple/"
        f"{wallet.apple_serial}/runs/{run_id}"
    )
    media_root = Path(settings.MEDIA_ROOT).resolve()
    final_root = (media_root / relative_root).resolve()
    if media_root not in final_root.parents:
        raise ValidationError("Unsafe Apple Wallet artifact path.")
    final_root.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=".generating-", dir=final_root.parent))
    pass_dir = temporary_root / "pass"
    pass_dir.mkdir()
    template_dir = Path(settings.APPLE_WALLET_TEMPLATE_DIR)
    try:
        for filename in ("icon.png", "icon@2x.png", "logo@2x.png"):
            source = template_dir / filename
            if source.is_file():
                shutil.copyfile(source, pass_dir / filename)
        _write_png(rendered.front, pass_dir / "strip@2x.png")
        (pass_dir / "pass.json").write_text(
            json.dumps(
                apple_pass_payload(customer=customer, wallet=wallet, design=design),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        generate_manifest(pass_dir)
        sign_manifest(pass_dir)
        _write_zip(pass_dir, temporary_root / "card.pkpass")
        shutil.rmtree(pass_dir)
        os.replace(temporary_root, final_root)
    except Exception:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)
        raise
    pass_path = final_root / "card.pkpass"
    pass_bytes = pass_path.read_bytes()
    artifact = CardArtifact(
        tenant=design.tenant,
        design=design,
        batch=wallet.physical_card.batch if wallet.physical_card_id else None,
        physical_card=wallet.physical_card,
        kind=CardArtifact.Kind.APPLE_PASS,
        storage_path=str(relative_root / "card.pkpass"),
        sha256=bytes_sha256(pass_bytes),
        size_bytes=len(pass_bytes),
        metadata={"run_id": run_id, "apple_serial": str(wallet.apple_serial)},
    )
    artifact.full_clean()
    artifact.save()
    return pass_path, artifact


@transaction.atomic
def update_wallet_apple_artifact(wallet: WalletPass, artifact: CardArtifact):
    wallet.apple_pass_path = artifact.storage_path
    wallet.apple_pass_sha256 = artifact.sha256
    wallet.save(
        update_fields=("apple_pass_path", "apple_pass_sha256", "updated_at")
    )


class AppleWalletIssuer:
    provider = "apple"

    def issue(self, customer, *, force=False, builder=None, updater=None):
        wallet = wallet_identity(customer)
        if wallet.apple_pass_path:
            stored_path = Path(settings.MEDIA_ROOT) / wallet.apple_pass_path
            if stored_path.is_file() and not force:
                return stored_path
        legacy_path = apple_pass_path(customer.klient_id)
        if legacy_path.is_file() and not force:
            if not wallet.apple_pass_path:
                wallet.apple_pass_path = str(
                    legacy_path.relative_to(settings.MEDIA_ROOT)
                )
                wallet.save(update_fields=("apple_pass_path", "updated_at"))
            return legacy_path
        design = CardDesign.objects.filter(tenant=customer.tenant).first()
        if design is None:
            raise ImproperlyConfigured(
                "No published card design exists for this tenant."
            )
        builder = builder or build_apple_pass
        updater = updater or update_wallet_apple_artifact
        generated_path, artifact = builder(
            customer=customer,
            wallet=wallet,
            design=design,
        )
        updater(wallet, artifact)
        return generated_path


issuer = AppleWalletIssuer()


def system_connection_check():
    if not settings.APPLE_WALLET_PASS_TYPE_IDENTIFIER or not settings.APPLE_WALLET_TEAM_IDENTIFIER:
        return SystemCheckResult(
            ok=False,
            summary="Identyfikatory Apple Wallet nie są kompletne.",
        )
    template_dir = Path(settings.APPLE_WALLET_TEMPLATE_DIR)
    required = ("AppleWWDR.pem", "certificate.pem", "key.pem")
    missing = [name for name in required if not (template_dir / name).is_file()]
    if missing:
        return SystemCheckResult(
            ok=False,
            summary="Brakuje materiałów podpisujących Apple Wallet.",
            details=tuple(f"Brak pliku: {name}" for name in missing),
        )
    certificate = x509.load_pem_x509_certificate(
        (template_dir / "certificate.pem").read_bytes()
    )
    x509.load_pem_x509_certificate((template_dir / "AppleWWDR.pem").read_bytes())
    private_key = serialization.load_pem_private_key(
        (template_dir / "key.pem").read_bytes(), password=None
    )
    certificate_public_key = certificate.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_public_key = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if certificate_public_key != private_public_key:
        return SystemCheckResult(
            ok=False,
            summary="Certyfikat Apple Wallet nie pasuje do klucza prywatnego.",
        )
    pass_type_attributes = certificate.subject.get_attributes_for_oid(NameOID.USER_ID)
    certificate_pass_type = (
        pass_type_attributes[0].value if pass_type_attributes else ""
    )
    if certificate_pass_type != settings.APPLE_WALLET_PASS_TYPE_IDENTIFIER:
        return SystemCheckResult(
            ok=False,
            summary="Certyfikat Apple Wallet należy do innego Pass Type ID.",
            details=(
                f"Oczekiwany Pass Type ID: {settings.APPLE_WALLET_PASS_TYPE_IDENTIFIER}",
            ),
        )
    team_attributes = certificate.subject.get_attributes_for_oid(
        NameOID.ORGANIZATIONAL_UNIT_NAME
    )
    certificate_team = team_attributes[0].value if team_attributes else ""
    if certificate_team != settings.APPLE_WALLET_TEAM_IDENTIFIER:
        return SystemCheckResult(
            ok=False,
            summary="Certyfikat Apple Wallet należy do innego zespołu Apple.",
            details=(f"Oczekiwany Team ID: {settings.APPLE_WALLET_TEAM_IDENTIFIER}",),
        )
    expires_at = getattr(certificate, "not_valid_after_utc", None)
    if expires_at is None:
        expires_at = certificate.not_valid_after.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        return SystemCheckResult(
            ok=False,
            summary="Certyfikat Apple Wallet wygasł.",
            details=(
                f"Pass Type ID: {settings.APPLE_WALLET_PASS_TYPE_IDENTIFIER}",
                f"Certyfikat wygasł: {expires_at:%Y-%m-%d %H:%M UTC}",
                "Utwórz nowy Pass Type ID Certificate w Apple Developer i zainstaluj go z pasującym kluczem prywatnym.",
            ),
        )
    return SystemCheckResult(
        ok=True,
        summary="Identyfikatory i materiały podpisujące Apple Wallet są prawidłowe.",
        details=(f"Certyfikat ważny do: {expires_at:%Y-%m-%d}",),
    )


__all__ = [
    "AppleWalletIssuer",
    "apple_pass_payload",
    "build_apple_pass",
    "generate_manifest",
    "issuer",
    "sign_manifest",
    "system_connection_check",
    "update_wallet_apple_artifact",
]
