import gzip
import hashlib
import hmac
import logging
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dotykacka.tests.base import default_tenant
from operations.logging import JsonLogFormatter, RedactingFilter
from operations.models import RateLimitBucket
from operations.rate_limits import consume_rate_limit, request_identity
from operations.webhooks import WebhookSignatureError, verify_signed_webhook


class SecurityBoundaryTests(TestCase):
    def test_forwarded_client_address_requires_an_explicitly_trusted_proxy(self):
        factory = RequestFactory()
        untrusted = factory.get(
            "/",
            REMOTE_ADDR="203.0.113.7",
            HTTP_X_FORWARDED_FOR="198.51.100.9",
        )
        self.assertIn("ip:203.0.113.7", request_identity(untrusted))
        self.assertNotIn("198.51.100.9", request_identity(untrusted))

        trusted = factory.get(
            "/",
            REMOTE_ADDR="10.0.0.3",
            HTTP_X_FORWARDED_FOR="192.0.2.44, 10.0.0.2",
        )
        with override_settings(LOYALTY_TRUSTED_PROXY_CIDRS=["10.0.0.0/8"]):
            self.assertIn("ip:192.0.2.44", request_identity(trusted))

    def test_public_response_has_correlation_and_browser_security_headers(self):
        response = self.client.get(
            reverse("marketing:home"),
            HTTP_X_REQUEST_ID="unsafe request id with spaces",
        )
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response["X-Request-ID"], r"^[a-f0-9]{32}$")
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("camera=(self)", response["Permissions-Policy"])

    def test_rate_limit_stores_only_hashed_identity_and_blocks_over_limit(self):
        now = timezone.now()
        self.assertEqual(
            consume_rate_limit(
                scope="test.scope",
                identity="ip:192.0.2.10|user:anonymous",
                limit=2,
                window_seconds=3600,
                now=now,
            )[0],
            True,
        )
        self.assertTrue(
            consume_rate_limit(
                scope="test.scope",
                identity="ip:192.0.2.10|user:anonymous",
                limit=2,
                window_seconds=3600,
                now=now + timedelta(seconds=1),
            )[0]
        )
        allowed, retry_after = consume_rate_limit(
            scope="test.scope",
            identity="ip:192.0.2.10|user:anonymous",
            limit=2,
            window_seconds=3600,
            now=now + timedelta(seconds=2),
        )
        self.assertFalse(allowed)
        self.assertGreater(retry_after, 0)
        bucket = RateLimitBucket.objects.get()
        self.assertEqual(bucket.request_count, 3)
        self.assertEqual(bucket.limited_count, 1)
        self.assertNotIn("192.0.2.10", bucket.identity_hash)

    @override_settings(MARKETING_CONTACT_RATE_LIMIT=1, PUBLIC_RATE_LIMIT_WINDOW_SECONDS=60)
    def test_public_contact_returns_retry_after_when_limited(self):
        url = reverse("marketing:contact")
        self.client.post(url, {})
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_structured_logging_redacts_credentials(self):
        record = logging.LogRecord(
            "loyalty.test",
            logging.WARNING,
            __file__,
            1,
            "authorization=Bearer-secret token=refresh-value api_key=key-value",
            (),
            None,
        )
        self.assertTrue(RedactingFilter().filter(record))
        payload = JsonLogFormatter().format(record)
        self.assertNotIn("Bearer-secret", payload)
        self.assertNotIn("refresh-value", payload)
        self.assertNotIn("key-value", payload)
        self.assertIn("[REDACTED]", payload)

    def test_webhook_hmac_has_replay_window_and_constant_time_comparison(self):
        timestamp = 1_700_000_000
        body = b'{"event":"test"}'
        signature = hmac.new(
            b"webhook-secret",
            str(timestamp).encode("ascii") + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        self.assertTrue(
            verify_signed_webhook(
                body=body,
                signature=f"sha256={signature}",
                timestamp=timestamp,
                secret="webhook-secret",
                now=timestamp + 5,
            )
        )
        with self.assertRaises(WebhookSignatureError):
            verify_signed_webhook(
                body=body,
                signature=signature,
                timestamp=timestamp,
                secret="webhook-secret",
                now=timestamp + 301,
            )

    def test_runtime_media_allows_public_brand_only_and_superuser_operational_access(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            root = Path(directory)
            (root / "public.png").write_bytes(b"public-image")
            private = root / "cards" / "card-12" / "MB-12_front.jpg"
            private.parent.mkdir(parents=True)
            private.write_bytes(b"private-card")
            tenant = default_tenant()
            tenant.brand.logo_path = "public.png"
            tenant.brand.save(update_fields=("logo_path", "updated_at"))

            public_response = self.client.get(
                reverse("protected_media", kwargs={"path": "public.png"})
            )
            self.assertEqual(public_response.status_code, 200)
            self.assertEqual(public_response["Cache-Control"], "public, max-age=3600")
            self.assertEqual(
                self.client.get(
                    reverse(
                        "protected_media",
                        kwargs={"path": "cards/card-12/MB-12_front.jpg"},
                    )
                ).status_code,
                404,
            )

            user = get_user_model().objects.create_superuser(
                username="media-admin",
                email="admin@example.test",
                password="strong-password",
            )
            self.client.force_login(user)
            private_response = self.client.get(
                reverse(
                    "protected_media",
                    kwargs={"path": "cards/card-12/MB-12_front.jpg"},
                )
            )
            self.assertEqual(private_response.status_code, 200)
            self.assertEqual(private_response["Cache-Control"], "private, no-store")

    def test_apache_does_not_publish_media_or_log_query_strings(self):
        config = (Path(__file__).parents[2] / "docker/apache/loyalty.conf").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("Alias /media/", config)
        self.assertIn("%m %U %H", config)
        self.assertNotIn("%q", config)
        self.assertIn("LimitRequestBody 67108864", config)
        self.assertIn("WSGIApplicationGroup %{GLOBAL}", config)
