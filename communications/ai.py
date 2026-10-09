"""OpenAI-backed, tenant-scoped campaign copy generation."""

import base64
import json
import re
from io import BytesIO

import requests
from PIL import Image, ImageOps
from django.conf import settings
from django.utils import timezone

from integrations.contracts import (
    IntegrationAuthenticationError,
    IntegrationConfigurationError,
    IntegrationError,
    ProviderResult,
    RetryableIntegrationError,
)
from integrations.models import IntegrationConnection


PROVIDER = "openai"
COPY_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "preheader": {"type": "string"},
        "headline": {"type": "string"},
        "body_paragraphs": {
            "type": "array",
            "items": {"type": "string"},
        },
        "cta_label": {"type": "string"},
        "cta_url_index": {"type": "integer"},
        "accent_color": {"type": "string"},
        "background_color": {"type": "string"},
    },
    "required": [
        "subject",
        "preheader",
        "headline",
        "body_paragraphs",
        "cta_label",
        "cta_url_index",
        "accent_color",
        "background_color",
    ],
    "additionalProperties": False,
}


def get_openai_connection(tenant):
    try:
        connection = IntegrationConnection.objects.get(
            tenant=tenant,
            provider=PROVIDER,
            enabled=True,
        )
    except IntegrationConnection.DoesNotExist as exc:
        raise IntegrationConfigurationError(
            "OpenAI is not enabled for this tenant.",
            error_code="openai_not_enabled",
        ) from exc
    if not connection.has_secret("api_key"):
        raise IntegrationConfigurationError(
            "OpenAI API key is missing.",
            error_code="openai_api_key_missing",
        )
    return connection


def _headers(connection):
    return {
        "Authorization": f"Bearer {connection.get_secret('api_key')}",
        "Content-Type": "application/json",
    }


def _raise_for_openai(response):
    if response.status_code in (401, 403):
        raise IntegrationAuthenticationError(
            "OpenAI API key was rejected.",
            error_code="openai_unauthorized",
        )
    if response.status_code == 429 or 500 <= response.status_code < 600:
        raise RetryableIntegrationError(
            error_code=f"openai_http_{response.status_code}",
            retry_after=5,
        )
    if response.status_code >= 400:
        raise IntegrationError(
            "OpenAI request failed.",
            error_code=f"openai_http_{response.status_code}",
        )


def test_openai_connection(connection, *, session=requests):
    try:
        response = session.get(
            f"{settings.OPENAI_API_BASE_URL.rstrip('/')}/models",
            headers=_headers(connection),
            timeout=settings.OPENAI_HTTP_TIMEOUT,
        )
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise RetryableIntegrationError(error_code="openai_network") from exc
    _raise_for_openai(response)
    body = response.json()
    if not isinstance(body.get("data"), list):
        raise IntegrationError(error_code="openai_invalid_response")
    now = timezone.now()
    connection.last_tested_at = now
    connection.last_success_at = now
    connection.last_error_code = ""
    connection.save(
        update_fields=("last_tested_at", "last_success_at", "last_error_code", "updated_at")
    )
    return ProviderResult(metadata={"models_available": len(body["data"])})


def _asset_data_url(asset):
    asset.image.open("rb")
    try:
        with Image.open(asset.image) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
            content = BytesIO()
            image.save(content, format="JPEG", quality=78, optimize=True)
    finally:
        asset.image.close()
    encoded = base64.b64encode(content.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _output_text(body):
    chunks = []
    for item in body.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                chunks.append(content["text"])
    if not chunks:
        raise IntegrationError(error_code="openai_missing_output")
    return "".join(chunks)


def _validated_copy(raw, link_count):
    if not isinstance(raw, dict):
        raise IntegrationError(error_code="openai_invalid_copy")
    paragraphs = raw.get("body_paragraphs")
    required_strings = (
        "subject",
        "preheader",
        "headline",
        "cta_label",
        "accent_color",
        "background_color",
    )
    if any(not isinstance(raw.get(key), str) for key in required_strings):
        raise IntegrationError(error_code="openai_invalid_copy")
    if not isinstance(paragraphs, list) or not 2 <= len(paragraphs) <= 4:
        raise IntegrationError(error_code="openai_invalid_copy")
    if any(not isinstance(paragraph, str) for paragraph in paragraphs):
        raise IntegrationError(error_code="openai_invalid_copy")
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", raw["accent_color"]):
        raw["accent_color"] = "#9A3C1F"
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", raw["background_color"]):
        raw["background_color"] = "#F5F2EB"
    index = raw.get("cta_url_index")
    if not isinstance(index, int) or index < 0 or index >= link_count:
        raw["cta_url_index"] = -1
        raw["cta_label"] = ""
    return {
        "subject": raw["subject"].strip()[:160],
        "preheader": raw["preheader"].strip()[:180],
        "headline": raw["headline"].strip()[:100],
        "body_paragraphs": [paragraph.strip()[:500] for paragraph in paragraphs],
        "cta_label": raw["cta_label"].strip()[:48],
        "cta_url_index": raw["cta_url_index"],
        "accent_color": raw["accent_color"].upper(),
        "background_color": raw["background_color"].upper(),
    }


def generate_campaign_copy(campaign, *, session=requests):
    connection = get_openai_connection(campaign.tenant)
    brand = campaign.tenant.brand
    model = connection.configuration.get("model") or settings.OPENAI_EMAIL_MODEL
    prompt_context = {
        "brand": {
            "name": brand.public_name or campaign.tenant.name,
            "tagline": brand.tagline,
            "website": brand.website_url,
            "signature": brand.email_signature,
        },
        "communication_goal": campaign.goal,
        "approved_links": campaign.reference_links,
    }
    instructions = (
        "Jesteś polskim redaktorem kampanii e-mail dla programu lojalnościowego. "
        "Przygotuj zwięzłą, naturalną treść zgodną z celem i materiałami marki. "
        "Nie wymyślaj cen, terminów, rabatów, adresów ani linków. "
        "Jeśli cel ich nie podaje, pomiń je. Nie dodawaj HTML. "
        "Wybierz CTA wyłącznie z listy approved_links, podając jego indeks, albo -1. "
        "Kolory muszą zapewniać czytelny, profesjonalny e-mail."
    )
    content = [
        {
            "type": "input_text",
            "text": json.dumps(prompt_context, ensure_ascii=False),
        }
    ]
    for asset in campaign.assets.all()[:3]:
        try:
            content.append(
                {
                    "type": "input_image",
                    "image_url": _asset_data_url(asset),
                    "detail": "low",
                }
            )
        except OSError:
            continue
    payload = {
        "model": model,
        "reasoning": {"effort": "low"},
        "instructions": instructions,
        "input": [{"role": "user", "content": content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "email_campaign_copy",
                "strict": True,
                "schema": COPY_SCHEMA,
            }
        },
        "max_output_tokens": 1200,
        "store": False,
    }
    try:
        response = session.post(
            f"{settings.OPENAI_API_BASE_URL.rstrip('/')}/responses",
            headers=_headers(connection),
            json=payload,
            timeout=settings.OPENAI_HTTP_TIMEOUT,
        )
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise RetryableIntegrationError(error_code="openai_network") from exc
    _raise_for_openai(response)
    try:
        generated = json.loads(_output_text(response.json()))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise IntegrationError(error_code="openai_invalid_response") from exc
    return _validated_copy(generated, len(campaign.reference_links)), model


__all__ = [
    "generate_campaign_copy",
    "get_openai_connection",
    "test_openai_connection",
]
